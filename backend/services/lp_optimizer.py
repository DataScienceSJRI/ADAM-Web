"""
Custom LP optimizer for ModelOptimiser.

Reimplements optimize_weekly_menu_with_constraints without the hard
macronutrient percentage constraints (carbs 45-50%, protein 15-20%,
fiber >= 25g/day) that make the original LP infeasible for Indian food.

Preserved constraints: slot coverage, Main/Main2 pairing, serving bounds,
recipe/category repetition limits, nutrient soft goals, sodium/cholesterol caps.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd


def run_lp(
    self, 
    meal_choices: pd.DataFrame,
    ds: Dict[str, pd.DataFrame],
    age_group_col: str,
    n_days: int = 7,
    weekly_rep: int = 3,
    category_weekly_rep: Optional[int] = 4,
    non_snack_serving_bounds: Tuple[float, float] = (0.5, 1.0),
    snack_serving_bounds: Tuple[float, float] = (0.5, 1.0),
    time_limit_sec: int = 120,
    per_meal_gl_cap: Optional[float] = None,
    per_day_gl_cap: Optional[float] = None,
    per_recipe_max_gl: Optional[float] = None,
    recipe_ing_df: Optional[pd.DataFrame] = None,
    main1_main2_mapping: Optional[pd.DataFrame] = None,
    ear_100: Optional[pd.DataFrame] = None,
    tul: Optional[pd.DataFrame] = None,
    profile: Optional[Dict] = None,
) -> Tuple[pd.DataFrame, Dict]:
    try:
        from pulp import (
            LpProblem, LpMinimize, LpVariable, lpSum,
            PULP_CBC_CMD, LpStatus, value,
        )
    except Exception as exc:
        return pd.DataFrame(), {"status": "missing_pulp", "error": str(exc)}

    if meal_choices is None or (hasattr(meal_choices, "empty") and meal_choices.empty):
        return pd.DataFrame(), {"status": "no_candidates"}

    # Use set-based mapping for Main1→Main2. Prefer explicit mapping if provided.
    if main1_main2_mapping is not None:
        main1_to_main2, main1_to_optional = self._get_main1_main2_map({'main1_main2_mapping': main1_main2_mapping})
    else:
        main1_to_main2, main1_to_optional = self._get_main1_main2_map(ds)

    candidates = meal_choices.copy()#.sort_values("Personalization_Score", ascending=False)
    # Preserve candidates per preference — include Preference_Row_ID in duplicate subset
    dedup_subset = ["Meal_Time", "Dish_Type", "Recipe_Code", "Preference_Row_ID"]
    candidates = candidates.drop_duplicates(subset=dedup_subset).reset_index(drop=True)
    if candidates.empty:
        return pd.DataFrame(), {"status": "no_candidates"}

    # Keep only required columns: Recipe_Category, Code_cooccurence, Preference_Row_ID, Meal_Time, Dish_Type, and nutrient columns
    required_cols = [
        "Recipe_Code","Recipe_Name","Recipe_Category", "Code_cooccurence", "Preferred_SubCategory_code", "Preference_Row_ID", "Meal_Time", "Dish_Type",
        "GL", "Avg_TimeAbove160_pct", "Avg_Delta_Glucose", "Energy_ENERC_Kcal", "Energy_ENERC_KJ",
        "Protein_PROTCNT_g", "TotalFat_FATCE_g", "TotalDietaryFibre_FIBTG_g", "CalciumCa_CA_mg", "ZincZn_ZN_mg",
        "IronFe_FE_mg", "MagnesiumMg_MG_mg", "VA_RAE_mcg", "TotalFolatesB9_FOLSUM_mcg", "VB12_mcg",
        "ThiamineB1_THIA_mg", "RiboflavinB2_RIBF_mg", "NiacinB3_NIA_mg", "TotalB6A_VITB6A_mg", "TotalAscorbicAcid_VITC_mg",
        "Carbohydrate_g", "Sodium_mg", "VITE_mg", "PhosphorusP_mg","PotassiumK_mg","Cholesterol_mg"
    ]
    # Only keep columns that exist in candidates
    keep_cols = [col for col in required_cols if col in candidates.columns]
    candidates = candidates[keep_cols].copy()
    candidates = candidates.drop_duplicates().reset_index(drop=True)

    # Normalize dish type and identifiers to avoid grouping mismatches
    candidates["Dish_Type"] = candidates["Dish_Type"].astype(str).str.strip()
    candidates["Preference_Row_ID"] = candidates["Preference_Row_ID"].astype(str).str.strip()
    candidates["Meal_Time"] = candidates["Meal_Time"].astype(str).str.strip()

    candidates["Main_Category_code"] = (
        candidates.get("MainCategoryCode", candidates.get("Code_cooccurence", ""))
        .astype(str)
        .str.strip()
        .str.upper()
    )
    # Main2_Target_code assignment diagnostics
    # Auto-fill missing Main2 and Side codes using mapping from Main1
    
    if "Category" in candidates.columns:
        candidates["Category_Key"] = candidates["Category"].astype(str).str.strip()
    elif "SubCategory" in candidates.columns:
        candidates["Category_Key"] = candidates["SubCategory"].astype(str).str.strip()
    elif "Subcategories" in candidates.columns:
        candidates["Category_Key"] = candidates["Subcategories"].astype(str).str.strip()
    else:
        candidates["Category_Key"] = ""
    candidates["Category_Key"] = candidates["Category_Key"].replace({"": np.nan})

    nutrient_cols = [
        "Energy_ENERC_Kcal", "Protein_PROTCNT_g", "TotalFat_FATCE_g", "TotalDietaryFibre_FIBTG_g",
        "CalciumCa_CA_mg", "ZincZn_ZN_mg", "IronFe_FE_mg", "MagnesiumMg_MG_mg", "VA_RAE_mcg",
        "TotalFolatesB9_FOLSUM_mcg", "VB12_mcg", "ThiamineB1_THIA_mg", "RiboflavinB2_RIBF_mg",
        "NiacinB3_NIA_mg", "TotalB6A_VITB6A_mg", "TotalAscorbicAcid_VITC_mg",
        "Carbohydrate_g", "Sodium_mg", "VITE_mg", "PhosphorusP_mg","PotassiumK_mg","Cholesterol_mg"
    ]
    for col in nutrient_cols:
        if col in candidates.columns:
            candidates[col] = pd.to_numeric(candidates[col], errors="coerce").fillna(0)

    energy_kj_raw = candidates["Energy_ENERC_KJ"] if "Energy_ENERC_KJ" in candidates.columns else pd.Series(np.nan, index=candidates.index)
    energy_kcal_raw = candidates["Energy_ENERC_Kcal"] if "Energy_ENERC_Kcal" in candidates.columns else pd.Series(np.nan, index=candidates.index)
    energy_kj = pd.to_numeric(energy_kj_raw, errors="coerce")
    energy_kcal = pd.to_numeric(energy_kcal_raw, errors="coerce")
    candidates["Energy_ENERC_Kcal"] = energy_kcal.fillna(energy_kj / 4.184).fillna(0)
    candidates["Energy_ENERC_KJ"] = energy_kj.fillna(candidates["Energy_ENERC_Kcal"] * 4.184).fillna(0)

    required_obj_cols = ["GL", "Avg_TimeAbove160_pct", "Avg_Delta_Glucose"]
    missing_obj_cols = [col for col in required_obj_cols if col not in candidates.columns]
    if missing_obj_cols:
        raise ValueError(f"Missing required objective columns: {missing_obj_cols}")
    for col in required_obj_cols:
        candidates[col] = pd.to_numeric(candidates[col], errors="coerce")
    # Fill missing objective columns with sensible defaults instead of dropping rows.
    # This ensures Main/Main2 candidate pairs aren't removed due to a missing metric.
    # For GL, use the median if available otherwise a small default; for the model metrics use 0.0.
    if candidates["GL"].isna().any():
        gl_median = candidates["GL"].median()
        if pd.isna(gl_median):
            gl_median = 10.0
        candidates["GL"] = candidates["GL"].fillna(gl_median)
    for col in ["Avg_TimeAbove160_pct", "Avg_Delta_Glucose"]:
        if candidates[col].isna().any():
            candidates[col] = candidates[col].fillna(0.0)

    # Compute z-scores for observed metrics only
    for col in ["Avg_TimeAbove160_pct", "Avg_Delta_Glucose"]:
        mean_val = float(candidates[col].mean())
        std_val = float(candidates[col].std(ddof=0))
        if std_val <= 1e-12:
            candidates[f"{col}_z"] = 0.0
        else:
            candidates[f"{col}_z"] = (candidates[col] - mean_val) / std_val

    # Use raw GL, z-scores for the other two
    candidates["Weighted_Objective_Score"] = (
        500 * candidates["GL"]
        + 0.3 * candidates["Avg_TimeAbove160_pct_z"]
        + 0.2 * candidates["Avg_Delta_Glucose_z"]
    )
    objective_metric_col = "Weighted_Objective_Score"

    required_slots = (
        candidates[["Meal_Time", "Dish_Type"]]
        .dropna()
        .drop_duplicates()
        .reset_index(drop=True)
    )
    if required_slots.empty:
        return pd.DataFrame(), {"status": "no_slots"}

    # Build a minimal dict for weekly requirement maps; prefer explicit ear/tul if provided
    req_ds = {}
    if ear_100 is not None:
        req_ds['ear_100'] = ear_100
    else:
        req_ds['ear_100'] = ds.get('ear_100', pd.DataFrame())
    if tul is not None:
        req_ds['tul'] = tul
    else:
        req_ds['tul'] = ds.get('tul', pd.DataFrame())
    weekly_min, weekly_max, daily_energy_kcal = self._get_weekly_requirement_maps(req_ds, age_group_col=age_group_col, n_days=n_days, profile=profile)
    # Compute effective daily energy requirement (`eff_daily`) and the
    # upper multiplier (`upper_mult`) once, based on the profile. This
    # keeps the energy logic centralized and avoids recomputing later.
    eff_daily = None
    upper_mult = 1.2  # default maximum multiplier for daily energy
    try:
        if daily_energy_kcal is not None:
            eff_daily = float(daily_energy_kcal)
            # Apply BMI reduction first
            if profile is not None:
                _bmi = profile.get("bmi")
                if _bmi is not None:
                    try:
                        _bmi_val = float(_bmi)
                        if _bmi_val >= 25.0:
                            eff_daily = eff_daily *1 ### 0.8 ####Jawa
                    except Exception:
                        pass
            # Apply age-based reductions on top of BMI adjustment
            if profile is not None:
                _age = profile.get("age")
                if _age is not None:
                    try:
                        _age_val = float(_age)
                        if _age_val > 60:
                            eff_daily = eff_daily * 1 ### 0.9 ####Jawa
                        elif _age_val > 50:
                            eff_daily = eff_daily * 1 ### 0.95 ####Jawa
                    except Exception:
                        pass
    except Exception:
        # non-fatal; leave eff_daily as None so downstream code can skip
        pass

    # Slot -> candidate indices mapping will be (re)built after index normalization below
    slot_to_ids: Dict[Tuple[str, str], List[int]] = {}

    print(f"[DEBUG] Number of candidates: {len(candidates)}")
    print(f"[DEBUG] Required slots:\n{required_slots}")
    print(f"[DEBUG] Slot to IDs mapping:\n{slot_to_ids}")

    # Profile (external) available for use in constraints/selection
    if profile is not None:
        print(f"[DEBUG] Profile: {profile}")

    #### model starts 
    # Defensive preprocessing: ensure integer 0-based index and numeric objective column
    candidates = candidates.reset_index(drop=True)
    # ensure objective metric exists and is numeric
    if objective_metric_col not in candidates.columns:
        candidates[objective_metric_col] = 0.0
    else:
        candidates[objective_metric_col] = pd.to_numeric(candidates[objective_metric_col], errors="coerce")
        if candidates[objective_metric_col].isna().all():
            candidates[objective_metric_col] = 0.0
        else:
            med = candidates[objective_metric_col].median()
            candidates[objective_metric_col] = candidates[objective_metric_col].fillna(med)

    candidates.to_csv("candidates_debug.csv", index=False)

    # --- Sugar and salt aggregation: compute grams per standard serving per recipe
    # Prefer explicit `recipe_ing_df` parameter; otherwise fall back to `ds` lookup.
    # If ingredient data is unavailable, default sugar/salt per serving to 0.0.
    if recipe_ing_df is not None and isinstance(recipe_ing_df, pd.DataFrame) and not recipe_ing_df.empty:
        rig_df = recipe_ing_df.copy()
    else:
        rig = ds.get('recipe_ing') or ds.get('recipe_ing_db') or ds.get('recipe_ingredients')
        if isinstance(rig, pd.DataFrame) and not rig.empty:
            rig_df = rig.copy()
        else:
            rig_df = pd.DataFrame()

    if not rig_df.empty:
        rig_df['Ing_raw_amounts_g'] = pd.to_numeric(rig_df.get('Ing_raw_amounts_g', 0), errors='coerce')
        rig_valid = rig_df.dropna(subset=['Ing_raw_amounts_g', 'Food Group']).copy()
        # normalize food group labels
        rig_valid['Food Group'] = rig_valid['Food Group'].astype(str).str.strip().str.lower()
        # Sugar per serving (grams)
        sugars = (
            rig_valid.loc[rig_valid['Food Group'] == 'sugars']
            .groupby('Recipe_Code', dropna=False)['Ing_raw_amounts_g']
            .sum()
            .rename('Sugar_per_serving_g')
        )
        if not sugars.empty:
            sug_df = sugars.reset_index()
            candidates = candidates.merge(sug_df, on='Recipe_Code', how='left')
        else:
            candidates['Sugar_per_serving_g'] = 0.0

        # Salt per serving (grams) — prefer Ingredients text, otherwise detect Food Group
        if 'Ingredients' in rig_df.columns:
            mask_salt = rig_df['Ingredients'].astype(str).str.contains(r"\bSalt\b", case=False, na=False)
            salt_series = (
                rig_df.loc[mask_salt]
                .groupby('Recipe_Code', dropna=False)['Ing_raw_amounts_g']
                .sum()
                .rename('Salt_per_serving_g')
            )
        else:
            mask_salt = rig_valid['Food Group'].astype(str).str.contains('salt', case=False, na=False)
            salt_series = (
                rig_valid.loc[mask_salt]
                .groupby('Recipe_Code', dropna=False)['Ing_raw_amounts_g']
                .sum()
                .rename('Salt_per_serving_g')
            )
        if not salt_series.empty:
            salt_df = salt_series.reset_index()
            candidates = candidates.merge(salt_df, on='Recipe_Code', how='left')
        else:
            candidates['Salt_per_serving_g'] = 0.0
    else:
        # no ingredient data available — default sugar and salt to zero
        candidates['Sugar_per_serving_g'] = 0.0
        candidates['Salt_per_serving_g'] = 0.0

    # Apply optional per-recipe GL filter (drop very high-GL recipes entirely)
    if per_recipe_max_gl is not None:
        try:
            _per = float(per_recipe_max_gl)
            candidates = candidates[pd.to_numeric(candidates.get("GL", 0), errors="coerce") <= _per].reset_index(drop=True)
        except Exception:
            # if conversion fails, ignore the filter
            pass

    # Rebuild slot -> ids mapping now that indices are stable (0..N-1)
    slot_to_ids = {}
    for idx, row in candidates.iterrows():
        slot_to_ids.setdefault((str(row["Meal_Time"]), str(row["Dish_Type"])), []).append(int(idx))

    print(f"[DEBUG] Rebuilt slot_to_ids after index reset: {slot_to_ids}")

    days = list(range(1, int(n_days) + 1))
    model = LpProblem("weekly_menu_min_weighted_gl_time_delta", LpMinimize)

    y = {}
    x = {}
    for d in days:
        for idx, _ in candidates.iterrows():
            i = int(idx)
            y[(d, i)] = LpVariable(f"y_d{d}_r{i}", lowBound=0, upBound=1, cat="Binary")
            x[(d, i)] = LpVariable(f"x_d{d}_r{i}", lowBound=0)
    model += lpSum(float(candidates.loc[i, objective_metric_col]) * x[(d, int(i))] for d in days for i in candidates.index)

    for d in days:
        for _, slot_row in required_slots.iterrows():
            slot = (str(slot_row["Meal_Time"]), str(slot_row["Dish_Type"]))
            ids = slot_to_ids.get(slot, [])
            if not ids:
                continue
            dtype = str(slot_row["Dish_Type"]).strip()
            # Make certain dish types optional with upper bounds; other required slots remain mandatory (==1).
            if dtype == "Snacks":
                # Allow up to 2 snack selections per slot
                model += lpSum(y[(d, i)] for i in ids) <= 2
                model += lpSum(y[(d, i)] for i in ids) >= 1
            elif dtype in ("Main 2", "Side", "Beverage"):
                # These remain optional but limited to 1
                model += lpSum(y[(d, i)] for i in ids) <= 1
            else:
                model += lpSum(y[(d, i)] for i in ids) == 1

    # Enforce meal-specific allowed dish types:
    # - `Side` must NOT appear for Breakfast; allowed only for Lunch and Dinner.
    # - `Beverage` is allowed ONLY for Breakfast (disallow in other meals).
    for d in days:
        for i in candidates.index:
            mt = str(candidates.loc[i, "Meal_Time"]).strip()
            dt = str(candidates.loc[i, "Dish_Type"]).strip().lower()
            # disallow Side in Breakfast
            if dt == "side" and mt.lower() == "breakfast":
                model += y[(d, int(i))] == 0
            # Side only in Lunch/Dinner
            if dt == "side" and mt.lower() not in ("lunch", "dinner"):
                model += y[(d, int(i))] == 0
            # Beverage only for Breakfast
            if dt == "beverage" and mt.lower() != "breakfast":
                model += y[(d, int(i))] == 0
        
    # Conditional pairing constraints: If a Preference row has both Main and Main 2,
    # their selections must be identical. If only Main exists, it's free to be chosen.
    for d in days:
        for meal_time in candidates["Meal_Time"].dropna().unique():
            meal_mask = candidates["Meal_Time"] == meal_time
            for pref_id, group in candidates[meal_mask].groupby("Preference_Row_ID"):
                mains = group[group["Dish_Type"].astype(str).str.strip() == "Main"].index.tolist()
                mains2 = group[group["Dish_Type"].astype(str).str.strip() == "Main 2"].index.tolist()

                if mains and mains2:
                    # If this ID has both, their selection must be identical (1 and 1, or 0 and 0)
                    model += lpSum(y[(d, i)] for i in mains) == lpSum(y[(d, j)] for j in mains2)
                    # Ensure servings for Main are at least servings for Main 2 (Main >= Main2)
                    model += lpSum(x[(d, i)] for i in mains) >= lpSum(x[(d, j)] for j in mains2)
                else:
                    # If there is no Main available for this preference+meal, explicitly
                    # disallow selecting Main 2 or Side items so they don't appear without Main.
                    if not mains and mains2:
                        model += lpSum(y[(d, j)] for j in mains2) == 0
                    # also disallow sides for this pref+meal when no Main exists
                    sides = group[group["Dish_Type"].astype(str).str.strip().str.lower() == "side"].index.tolist()
                    if not mains and sides:
                        model += lpSum(y[(d, s)] for s in sides) == 0

    # Write pairing constraint debug info (which candidate indices were considered for each pref+meal)
    try:
        pairing_debug_rows = []
        for d in days:
            for meal_time in sorted(candidates["Meal_Time"].dropna().astype(str).unique().tolist()):
                slot_candidates = candidates[candidates["Meal_Time"].astype(str) == str(meal_time)]
                for pref_id, group in slot_candidates.groupby("Preference_Row_ID"):
                    main_ids = group[group["Dish_Type"].astype(str).str.strip() == "Main"].index.tolist()
                    main2_ids = group[group["Dish_Type"].astype(str).str.strip() == "Main 2"].index.tolist()
                    pairing_debug_rows.append({
                        "Day": d,
                        "Meal_Time": meal_time,
                        "Preference_Row_ID": pref_id,
                        "main_ids": ";".join([str(x) for x in main_ids]),
                        "main2_ids": ";".join([str(x) for x in main2_ids]),
                        "has_main": bool(len(main_ids) > 0),
                        "has_main2": bool(len(main2_ids) > 0),
                    })
        out_dir = self.config.outputs_dir
        out_dir.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(pairing_debug_rows).to_csv(out_dir / "pairing_constraints_debug.csv", index=False)
    except Exception:
        pass


    for d in days:
        for idx, row in candidates.iterrows():
            i = int(idx)
            meal_time = str(row.get("Meal_Time", ""))
            lb, ub = snack_serving_bounds if meal_time == "Snacks" else non_snack_serving_bounds
            model += x[(d, i)] <= float(ub) * y[(d, i)]
            model += x[(d, i)] >= float(lb) * y[(d, i)]

    # GL-cap constraints: per-meal and per-day (if provided)
    if per_meal_gl_cap is not None:
        try:
            pmeal = float(per_meal_gl_cap)
            for d in days:
                for _, slot_row in required_slots.iterrows():
                    slot = (str(slot_row["Meal_Time"]), str(slot_row["Dish_Type"]))
                    ids = slot_to_ids.get(slot, [])
                    if not ids:
                        continue
                    model += lpSum(float(candidates.loc[i, "GL"]) * x[(d, int(i))] for i in ids) <= float(pmeal)
        except Exception:
            pass

    if per_day_gl_cap is not None:
        try:
            pday = float(per_day_gl_cap)
            for d in days:
                model += lpSum(float(candidates.loc[i, "GL"]) * x[(d, int(i))] for i in candidates.index) <= float(pday)
        except Exception:
            pass

    for _, group_df in candidates.groupby(["Meal_Time", "Dish_Type", "Recipe_Code"], dropna=False):
        ids = [int(i) for i in group_df.index.tolist()]
        model += lpSum(y[(d, i)] for d in days for i in ids) <= int(weekly_rep)

    # Relax category weekly rep constraint if infeasible
    if category_weekly_rep is None:
        category_weekly_rep = 0
    if category_weekly_rep > 0:
        category_df = candidates.dropna(subset=["Category_Key"]).copy()
        for _, group_df in category_df.groupby(["Dish_Type", "Category_Key"], dropna=False):
            dish_type_u = str(group_df["Dish_Type"].iloc[0]).strip().upper() if not group_df.empty else ""
            if dish_type_u != "MAIN":
                continue
            ids = [int(i) for i in group_df.index.tolist()]
            if ids:
                # Use a relaxed upper bound (double the rep)
                model += lpSum(y[(d, i)] for d in days for i in ids) <= int(category_weekly_rep)
    #### old
    # Elastic (goal) constraints for nutrients: add slack variables and penalize shortfall
    # nutrient_slacks = {}
    # penalty_weight = 100.0  # Lower penalty to allow more flexibility
    # for col, req in weekly_min.items():
    # 	if col not in candidates.columns or req <= 0:
    # 		continue
    # 	# Slack variable for shortfall (>=0)
    # 	slack = LpVariable(f"nutrient_shortfall_{col}", lowBound=0)
    # 	nutrient_slacks[col] = slack
        
    # 	if profile and isinstance(profile, dict):
    # 		dt = str(profile.get("diet_type", "")).strip().lower()
    # 		# for all diets except explicit 'Non-veg', drop VB12 requirement
    # 		if dt and dt != "non-veg" and "VB12_mcg" in col:
    # 			continue
    # 		else:
    # 			# Allow shortfall, but penalize in objective
    # 			model += lpSum(float(candidates.loc[i, col]) * x[(d, int(i))] for d in days for i in candidates.index) + slack >= float(req)

    # # Add penalty for all nutrient shortfalls to the objective
    # if nutrient_slacks:
    # 	model += penalty_weight * lpSum(slack for slack in nutrient_slacks.values())

    ###new
    nutrient_slacks = {}
    penalty_terms = []
    penalty_weight = 100.0

    for col, req in weekly_min.items():
        if col not in candidates.columns or req <= 0:
            continue

        # Skip VB12 for diets other than explicit 'Non-veg'
        if profile and isinstance(profile, dict):
            dt = str(profile.get("diet_type", "")).strip().lower()
            if dt and dt != "non-veg" and col == "VB12_mcg":
                continue

        # Slack variable for shortfall (>=0)
        safe_col = col.replace(" ", "_").replace("-", "_")
        slack = LpVariable(f"nutrient_shortfall_{safe_col}", lowBound=0)
        nutrient_slacks[col] = slack

        model += lpSum(float(candidates.loc[i, col]) * x[(d, int(i))] for d in days for i in candidates.index) + slack >= float(req)
        print(f"Added constraint for {col} with requirement {req} and slack variable {slack.name}")
        penalty_terms.append(penalty_weight * slack)

    # After building other objective parts, add penalties (merge with existing objective)
    if penalty_terms:
        model += lpSum(penalty_terms)


    # Enforce per-day kcal bounds using the previously computed `eff_daily` and `upper_mult`.
    if eff_daily is not None and "Energy_ENERC_Kcal" in candidates.columns:
        for d in days:
            daily_kcal = lpSum(float(candidates.loc[i, "Energy_ENERC_Kcal"]) * x[(d, int(i))] for i in candidates.index)
            model += daily_kcal >= float(eff_daily)
            model += daily_kcal <= float(eff_daily) * float(upper_mult)

    # Macronutrient percentage constraints (per-day):
    # Carbohydrates 45–50% energy, Protein 15–20% energy, Fat 25–35% energy.
    # Use energy conversions: carbs=4 kcal/g, protein=4 kcal/g, fat=9 kcal/g.
    # Assume required macro columns exist in `candidates`.
    candidates["Carb_g"] = pd.to_numeric(candidates.get("Carbohydrate_g", 0), errors="coerce").fillna(0.0)
    candidates["Prot_g"] = pd.to_numeric(candidates.get("Protein_PROTCNT_g", 0), errors="coerce").fillna(0.0)
    candidates["Fat_g"] = pd.to_numeric(candidates.get("TotalFat_FATCE_g", 0), errors="coerce").fillna(0.0)
    candidates["Energy_kcal"] = pd.to_numeric(candidates.get("Energy_ENERC_Kcal", 0), errors="coerce").fillna(0.0)
    for d in days:
        # Carbs: 45-50% of E_d
        model += lpSum((4.0 * candidates.loc[i, "Carb_g"] - 0.45 * candidates.loc[i, "Energy_kcal"]) * x[(d, int(i))] for i in candidates.index) >= 0.0
        model += lpSum((4.0 * candidates.loc[i, "Carb_g"] - 0.50 * candidates.loc[i, "Energy_kcal"]) * x[(d, int(i))] for i in candidates.index) <= 0.0

        # Protein: 15-20% of E_d
        model += lpSum((4.0 * candidates.loc[i, "Prot_g"] - 0.15 * candidates.loc[i, "Energy_kcal"]) * x[(d, int(i))] for i in candidates.index) >= 0.0
        model += lpSum((4.0 * candidates.loc[i, "Prot_g"] - 0.20 * candidates.loc[i, "Energy_kcal"]) * x[(d, int(i))] for i in candidates.index) <= 0.0

        # Fat: 25-35% of E_d
        model += lpSum((9.0 * candidates.loc[i, "Fat_g"] - 0.25 * candidates.loc[i, "Energy_kcal"]) * x[(d, int(i))] for i in candidates.index) >= 0.0
        model += lpSum((9.0 * candidates.loc[i, "Fat_g"] - 0.35 * candidates.loc[i, "Energy_kcal"]) * x[(d, int(i))] for i in candidates.index) <= 0.0

        # Minimum carbohydrates per day (grams)
        min_carbs_per_day = 130.0
        model += lpSum(candidates.loc[i, "Carb_g"] * x[(d, int(i))] for i in candidates.index) >= float(min_carbs_per_day)


    # --- Fiber constraints (separate block):
    # 1) Energy-based: at least 14 g fiber per 1000 kcal per day
    #    (i.e. 4 * sugar_energy example; here: 1000 * daily_fiber >= 14 * daily_energy)
    # 2) Gender-based absolute minimum per day: male >=30 g, female >=25 g
    candidates["Fiber_g"] = pd.to_numeric(candidates.get("TotalDietaryFibre_FIBTG_g", 0), errors="coerce").fillna(0.0)
    # determine gender-based minimum (None if unknown)
    _gender_min = None
    if profile is not None:
        _g = profile.get("gender")
        if isinstance(_g, str):
            _gs = _g.strip().lower()
            if _gs.startswith("m"):
                _gender_min = 30.0
            elif _gs.startswith("f"):
                _gender_min = 25.0

    for d in days:
        daily_fiber = lpSum(float(candidates.loc[i, "Fiber_g"]) * x[(d, int(i))] for i in candidates.index)
        daily_energy = lpSum(float(candidates.loc[i, "Energy_ENERC_Kcal"]) * x[(d, int(i))] for i in candidates.index)
        # energy-based requirement: 1000 * fiber_g >= 14 * energy_kcal  => daily_fiber >= 14/1000 * daily_energy
        model += daily_fiber * 1000.0 >= 14.0 * daily_energy
        # enforce gender absolute minimum if known
        if _gender_min is not None:
            model += daily_fiber >= float(_gender_min)

    for col, max_req in weekly_max.items():
        if col not in candidates.columns or max_req <= 0:
            continue
        # Relax max constraints by 20%
        model += lpSum(float(candidates.loc[i, col]) * x[(d, int(i))] for d in days for i in candidates.index) <= float(max_req) * 1.2

    # Sugar constraint linked to energy: ensure sugar energy <= 5% of daily energy
    # i.e., for each day d: 4 * sum(Sugar_per_serving_g * x[d,i]) <= 0.05 * sum(Energy_ENERC_Kcal * x[d,i])
    if 'Sugar_per_serving_g' in candidates.columns and 'Energy_ENERC_Kcal' in candidates.columns:
        for d in days:
            sugar_energy = lpSum(4.0 * float(candidates.loc[i, 'Sugar_per_serving_g']) * x[(d, int(i))] for i in candidates.index)
            daily_energy = lpSum(float(candidates.loc[i, 'Energy_ENERC_Kcal']) * x[(d, int(i))] for i in candidates.index)
            model += sugar_energy <= 0.05 * daily_energy

    # Hard sodium constraint: enforce daily sodium <= 2000 mg (applied across the week)
    sodium_limit_per_day_mg = 1500.0
    if 'Sodium_mg' in candidates.columns:
        model += lpSum(float(candidates.loc[i, 'Sodium_mg']) * x[(d, int(i))] for d in days for i in candidates.index) <= float(sodium_limit_per_day_mg) * float(n_days)

    # Hard cholesterol constraint: per-day cholesterol < 300 mg
    cholesterol_limit_per_day_mg = 300.0
    if 'Cholesterol_mg' in candidates.columns:
        for d in days:
            model += lpSum(float(candidates.loc[i, 'Cholesterol_mg']) * x[(d, int(i))] for i in candidates.index) <= float(cholesterol_limit_per_day_mg)

    # Hard salt quantity constraint: total salt (grams) per day <= 5 g (applied across the week)
    salt_limit_per_day_g = 5
    if 'Salt_per_serving_g' in candidates.columns:
        model += lpSum(float(candidates.loc[i, 'Salt_per_serving_g']) * x[(d, int(i))] for d in days for i in candidates.index) <= float(salt_limit_per_day_g) * float(n_days)

    solver = PULP_CBC_CMD(timeLimit=int(time_limit_sec))
    _ = model.solve(solver)
    status = str(LpStatus.get(model.status, model.status))

    selected_rows: List[Dict[str, object]] = []
    for d in days:
        for i in candidates.index:
            if float(y[(d, int(i))].value() or 0) > 0.5:
                row = candidates.loc[i].to_dict()
                row["Day"] = d
                row["Serving"] = float(x[(d, int(i))].value() or 0)
                selected_rows.append(row)

    # Dump post-solve variable values for diagnostics (y and x)
    try:
        vars_rows = []
        for d in days:
            for i in candidates.index:
                y_val = float(y[(d, int(i))].value() or 0)
                x_val = float(x[(d, int(i))].value() or 0)
                vars_rows.append({
                    "Day": d,
                    "Candidate_Index": int(i),
                    "y_var": f"y_d{d}_r{int(i)}",
                    "y_val": y_val,
                    "x_var": f"x_d{d}_r{int(i)}",
                    "x_val": x_val,
                })
        out_dir = self.config.outputs_dir
        out_dir.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(vars_rows).to_csv(out_dir / "y_x_values_postsolve.csv", index=False)
    except Exception:
        pass

    weekly_menu = pd.DataFrame(selected_rows)
    if not weekly_menu.empty:
        weekly_menu = weekly_menu.sort_values(["Day", "Meal_Time", "Dish_Type"]).reset_index(drop=True)
    else:
        # Fallback: select top candidates for each slot
        fallback_rows = []
        for d in days:
            for _, slot_row in required_slots.iterrows():
                slot = (str(slot_row["Meal_Time"]), str(slot_row["Dish_Type"]))
                ids = slot_to_ids.get(slot, [])
                if ids:
                    i = ids[0]
                    row = candidates.loc[i].to_dict()
                    row["Day"] = d
                    row["Serving"] = 1.0
                    fallback_rows.append(row)
        weekly_menu = pd.DataFrame(fallback_rows)

    summary = {
        "status": status,
        "objective": float(value(model.objective)) if model.objective is not None else np.nan,
        "objective_metric": objective_metric_col,
        "objective_formula": "0.5*z(GL) + 0.3*z(Avg_TimeAbove160_pct) + 0.2*z(Avg_Delta_Glucose)",
        "category_weekly_rep": int(category_weekly_rep) if category_weekly_rep is not None else None,
        "rows": int(len(weekly_menu)),
        "days": int(n_days),
        "required_slots": int(len(required_slots)),
    }
    print(weekly_menu)
    weekly_menu.to_csv("weekly_menu_lp_output.csv", index=False)
    print(summary)
    return weekly_menu, summary
