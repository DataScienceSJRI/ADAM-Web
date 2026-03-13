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

    # ── Main1→Main2 mapping ───────────────────────────────────────────────────
    if main1_main2_mapping is not None:
        main1_to_main2, main1_to_optional = self._get_main1_main2_map(
            {"main1_main2_mapping": main1_main2_mapping}
        )
    else:
        main1_to_main2, main1_to_optional = self._get_main1_main2_map(ds)

    # ── Candidate prep ────────────────────────────────────────────────────────
    candidates = meal_choices.copy()
    dedup_subset = ["Meal_Time", "Dish_Type", "Recipe_Code", "Preference_Row_ID"]
    candidates = candidates.drop_duplicates(
        subset=[c for c in dedup_subset if c in candidates.columns]
    ).reset_index(drop=True)
    if candidates.empty:
        return pd.DataFrame(), {"status": "no_candidates"}

    required_cols = [
        "Recipe_Code", "Recipe_Name", "Recipe_Category", "Code_cooccurence",
        "Preferred_SubCategory_code", "Preference_Row_ID", "Meal_Time", "Dish_Type",
        "GL", "Avg_TimeAbove160_pct", "Avg_Delta_Glucose",
        "Energy_ENERC_Kcal", "Energy_ENERC_KJ",
        "Protein_PROTCNT_g", "TotalFat_FATCE_g", "TotalDietaryFibre_FIBTG_g",
        "CalciumCa_CA_mg", "ZincZn_ZN_mg", "IronFe_FE_mg", "MagnesiumMg_MG_mg",
        "VA_RAE_mcg", "TotalFolatesB9_FOLSUM_mcg", "VB12_mcg",
        "ThiamineB1_THIA_mg", "RiboflavinB2_RIBF_mg", "NiacinB3_NIA_mg",
        "TotalB6A_VITB6A_mg", "TotalAscorbicAcid_VITC_mg",
        "Carbohydrate_g", "Sodium_mg", "VITE_mg", "PhosphorusP_mg",
        "PotassiumK_mg", "Cholesterol_mg",
    ]
    candidates = candidates[[c for c in required_cols if c in candidates.columns]].copy()
    candidates = candidates.drop_duplicates().reset_index(drop=True)

    candidates["Dish_Type"] = candidates["Dish_Type"].astype(str).str.strip()
    candidates["Preference_Row_ID"] = candidates["Preference_Row_ID"].astype(str).str.strip()
    candidates["Meal_Time"] = candidates["Meal_Time"].astype(str).str.strip()

    candidates["Main_Category_code"] = (
        candidates.get("Code_cooccurence", pd.Series("", index=candidates.index))
        .astype(str).str.strip().str.upper()
    )

    for col in ["Category", "SubCategory", "Subcategories"]:
        if col in candidates.columns:
            candidates["Category_Key"] = candidates[col].astype(str).str.strip()
            break
    else:
        candidates["Category_Key"] = ""
    candidates["Category_Key"] = candidates["Category_Key"].replace({"": np.nan})

    nutrient_cols = [
        "Energy_ENERC_Kcal", "Protein_PROTCNT_g", "TotalFat_FATCE_g",
        "TotalDietaryFibre_FIBTG_g", "CalciumCa_CA_mg", "ZincZn_ZN_mg",
        "IronFe_FE_mg", "MagnesiumMg_MG_mg", "VA_RAE_mcg",
        "TotalFolatesB9_FOLSUM_mcg", "VB12_mcg", "ThiamineB1_THIA_mg",
        "RiboflavinB2_RIBF_mg", "NiacinB3_NIA_mg", "TotalB6A_VITB6A_mg",
        "TotalAscorbicAcid_VITC_mg", "Carbohydrate_g", "Sodium_mg", "VITE_mg",
        "PhosphorusP_mg", "PotassiumK_mg", "Cholesterol_mg",
    ]
    for col in nutrient_cols:
        if col in candidates.columns:
            candidates[col] = pd.to_numeric(candidates[col], errors="coerce").fillna(0)

    # Energy: prefer kcal, fall back from kJ
    if "Energy_ENERC_KJ" in candidates.columns:
        energy_kj = pd.to_numeric(candidates["Energy_ENERC_KJ"], errors="coerce")
    else:
        energy_kj = pd.Series(np.nan, index=candidates.index)
    if "Energy_ENERC_Kcal" in candidates.columns:
        energy_kcal = pd.to_numeric(candidates["Energy_ENERC_Kcal"], errors="coerce")
    else:
        energy_kcal = pd.Series(np.nan, index=candidates.index)
    candidates["Energy_ENERC_Kcal"] = energy_kcal.fillna(energy_kj / 4.184).fillna(0)

    # Objective columns
    for col in ["GL", "Avg_TimeAbove160_pct", "Avg_Delta_Glucose"]:
        candidates[col] = pd.to_numeric(candidates.get(col, 0), errors="coerce")
    gl_median = candidates["GL"].median()
    candidates["GL"] = candidates["GL"].fillna(gl_median if not pd.isna(gl_median) else 10.0)
    for col in ["Avg_TimeAbove160_pct", "Avg_Delta_Glucose"]:
        candidates[col] = candidates[col].fillna(0.0)

    for col in ["Avg_TimeAbove160_pct", "Avg_Delta_Glucose"]:
        mean_val = float(candidates[col].mean())
        std_val = float(candidates[col].std(ddof=0))
        candidates[f"{col}_z"] = (
            0.0 if std_val <= 1e-12
            else (candidates[col] - mean_val) / std_val
        )

    candidates["Weighted_Objective_Score"] = (
        500 * candidates["GL"]
        + 0.3 * candidates["Avg_TimeAbove160_pct_z"]
        + 0.2 * candidates["Avg_Delta_Glucose_z"]
    )
    objective_metric_col = "Weighted_Objective_Score"

    required_slots = (
        candidates[["Meal_Time", "Dish_Type"]]
        .dropna().drop_duplicates().reset_index(drop=True)
    )
    if required_slots.empty:
        return pd.DataFrame(), {"status": "no_slots"}

    # ── Nutrient requirements ─────────────────────────────────────────────────
    req_ds: Dict = {}
    req_ds["ear_100"] = ear_100 if ear_100 is not None else ds.get("ear_100", pd.DataFrame())
    req_ds["tul"] = tul if tul is not None else ds.get("tul", pd.DataFrame())
    weekly_min, weekly_max, daily_energy_kcal = self._get_weekly_requirement_maps(
        req_ds, age_group_col=age_group_col, n_days=n_days, profile=profile
    )

    # ── Ingredient-based sugar / salt ─────────────────────────────────────────
    candidates = candidates.reset_index(drop=True)
    if objective_metric_col not in candidates.columns:
        candidates[objective_metric_col] = 0.0
    else:
        candidates[objective_metric_col] = pd.to_numeric(
            candidates[objective_metric_col], errors="coerce"
        ).fillna(candidates[objective_metric_col].median())

    rig_df: pd.DataFrame = pd.DataFrame()
    if recipe_ing_df is not None and not recipe_ing_df.empty:
        rig_df = recipe_ing_df.copy()
    else:
        for key in ("recipe_ing", "recipe_ing_db", "recipe_ingredients"):
            _r = ds.get(key)
            if isinstance(_r, pd.DataFrame) and not _r.empty:
                rig_df = _r.copy()
                break

    if not rig_df.empty:
        rig_df["Ing_raw_amounts_g"] = pd.to_numeric(
            rig_df.get("Ing_raw_amounts_g", 0), errors="coerce"
        )
        rig_valid = rig_df.dropna(subset=["Ing_raw_amounts_g", "Food Group"]).copy()
        rig_valid["Food Group"] = rig_valid["Food Group"].astype(str).str.strip().str.lower()
        sugars = (
            rig_valid[rig_valid["Food Group"] == "sugars"]
            .groupby("Recipe_Code", dropna=False)["Ing_raw_amounts_g"]
            .sum().rename("Sugar_per_serving_g")
        )
        candidates = candidates.merge(sugars.reset_index(), on="Recipe_Code", how="left") if not sugars.empty else candidates.assign(Sugar_per_serving_g=0.0)
        if "Ingredients" in rig_df.columns:
            mask_salt = rig_df["Ingredients"].astype(str).str.contains(r"\bSalt\b", case=False, na=False)
        else:
            mask_salt = rig_valid["Food Group"].str.contains("salt", case=False, na=False)
        salt_series = (
            rig_df[mask_salt].groupby("Recipe_Code", dropna=False)["Ing_raw_amounts_g"]
            .sum().rename("Salt_per_serving_g")
        )
        candidates = candidates.merge(salt_series.reset_index(), on="Recipe_Code", how="left") if not salt_series.empty else candidates.assign(Salt_per_serving_g=0.0)
    else:
        candidates["Sugar_per_serving_g"] = 0.0
        candidates["Salt_per_serving_g"] = 0.0

    # ── Build slot → candidate indices mapping ────────────────────────────────
    slot_to_ids: Dict[Tuple[str, str], List[int]] = {}
    for idx, row in candidates.iterrows():
        slot_to_ids.setdefault((str(row["Meal_Time"]), str(row["Dish_Type"])), []).append(int(idx))

    days = list(range(1, int(n_days) + 1))

    # ── LP model ──────────────────────────────────────────────────────────────
    model = LpProblem("weekly_menu_indian_relaxed", LpMinimize)

    y: Dict = {}
    x: Dict = {}
    for d in days:
        for idx in candidates.index:
            i = int(idx)
            y[(d, i)] = LpVariable(f"y_d{d}_r{i}", cat="Binary")
            x[(d, i)] = LpVariable(f"x_d{d}_r{i}", lowBound=0)

    # Objective: minimise weighted GL / glucose scores
    model += lpSum(
        float(candidates.loc[i, objective_metric_col]) * x[(d, int(i))]
        for d in days for i in candidates.index
    )

    # ── Slot coverage constraints ─────────────────────────────────────────────
    for d in days:
        for _, slot_row in required_slots.iterrows():
            slot = (str(slot_row["Meal_Time"]), str(slot_row["Dish_Type"]))
            ids = slot_to_ids.get(slot, [])
            if not ids:
                continue
            dtype = str(slot_row["Dish_Type"]).strip()
            if dtype == "Snacks":
                model += lpSum(y[(d, i)] for i in ids) <= 2
                model += lpSum(y[(d, i)] for i in ids) >= 1
            elif dtype in ("Main 2", "Side", "Beverage"):
                model += lpSum(y[(d, i)] for i in ids) <= 1
            else:
                model += lpSum(y[(d, i)] for i in ids) == 1

    # ── Meal-type restrictions ────────────────────────────────────────────────
    for d in days:
        for i in candidates.index:
            mt = str(candidates.loc[i, "Meal_Time"]).strip().lower()
            dt = str(candidates.loc[i, "Dish_Type"]).strip().lower()
            if dt == "side" and mt == "breakfast":
                model += y[(d, int(i))] == 0
            if dt == "side" and mt not in ("lunch", "dinner"):
                model += y[(d, int(i))] == 0
            if dt == "beverage" and mt != "breakfast":
                model += y[(d, int(i))] == 0

    # ── Main / Main 2 pairing constraints ─────────────────────────────────────
    for d in days:
        for meal_time in candidates["Meal_Time"].dropna().unique():
            meal_mask = candidates["Meal_Time"] == meal_time
            for _, group in candidates[meal_mask].groupby("Preference_Row_ID"):
                mains = group[group["Dish_Type"].str.strip() == "Main"].index.tolist()
                mains2 = group[group["Dish_Type"].str.strip() == "Main 2"].index.tolist()
                if mains and mains2:
                    model += lpSum(y[(d, i)] for i in mains) == lpSum(y[(d, j)] for j in mains2)
                    model += lpSum(x[(d, i)] for i in mains) >= lpSum(x[(d, j)] for j in mains2)
                else:
                    sides = group[group["Dish_Type"].str.strip().str.lower() == "side"].index.tolist()
                    if not mains and mains2:
                        model += lpSum(y[(d, j)] for j in mains2) == 0
                    if not mains and sides:
                        model += lpSum(y[(d, s)] for s in sides) == 0

    # ── Serving bounds ────────────────────────────────────────────────────────
    for d in days:
        for idx, row in candidates.iterrows():
            i = int(idx)
            mt = str(row.get("Meal_Time", ""))
            lb, ub = snack_serving_bounds if mt == "Snacks" else non_snack_serving_bounds
            model += x[(d, i)] <= float(ub) * y[(d, i)]
            model += x[(d, i)] >= float(lb) * y[(d, i)]

    # ── Recipe repetition limits ──────────────────────────────────────────────
    for _, group_df in candidates.groupby(
        ["Meal_Time", "Dish_Type", "Recipe_Code"], dropna=False
    ):
        ids = [int(i) for i in group_df.index.tolist()]
        model += lpSum(y[(d, i)] for d in days for i in ids) <= int(weekly_rep)

    # ── Category repetition limits (Main dishes only) ─────────────────────────
    if category_weekly_rep and category_weekly_rep > 0:
        cat_df = candidates.dropna(subset=["Category_Key"]).copy()
        for _, group_df in cat_df.groupby(["Dish_Type", "Category_Key"], dropna=False):
            if str(group_df["Dish_Type"].iloc[0]).strip().upper() != "MAIN":
                continue
            ids = [int(i) for i in group_df.index.tolist()]
            if ids:
                model += lpSum(y[(d, i)] for d in days for i in ids) <= int(category_weekly_rep)

    # ── Nutrient soft goals (elastic, penalty for shortfall) ──────────────────
    nutrient_slacks: Dict = {}
    penalty_weight = 100.0
    for col, req in weekly_min.items():
        if col not in candidates.columns or req <= 0:
            continue
        slack = LpVariable(f"nutrient_shortfall_{col}", lowBound=0)
        nutrient_slacks[col] = slack
        if profile and isinstance(profile, dict):
            dt = str(profile.get("diet_type", "")).strip().lower()
            if dt and dt != "non-veg" and "VB12_mcg" in col:
                continue
        model += (
            lpSum(
                float(candidates.loc[i, col]) * x[(d, int(i))]
                for d in days for i in candidates.index
            ) + slack >= float(req)
        )
    if nutrient_slacks:
        model += penalty_weight * lpSum(s for s in nutrient_slacks.values())

    # ── Weekly nutrient max (relaxed 20%) ─────────────────────────────────────
    for col, max_req in weekly_max.items():
        if col not in candidates.columns or max_req <= 0:
            continue
        model += (
            lpSum(
                float(candidates.loc[i, col]) * x[(d, int(i))]
                for d in days for i in candidates.index
            ) <= float(max_req) * 1.2
        )

    # ── Sodium limit (weekly total) ───────────────────────────────────────────
    if "Sodium_mg" in candidates.columns:
        model += (
            lpSum(
                float(candidates.loc[i, "Sodium_mg"]) * x[(d, int(i))]
                for d in days for i in candidates.index
            ) <= 2000.0 * float(n_days)
        )

    # ── Cholesterol limit (per day) ───────────────────────────────────────────
    if "Cholesterol_mg" in candidates.columns:
        for d in days:
            model += (
                lpSum(
                    float(candidates.loc[i, "Cholesterol_mg"]) * x[(d, int(i))]
                    for i in candidates.index
                ) <= 300.0
            )

    # ── Solve ─────────────────────────────────────────────────────────────────
    print(f"[LP] Solving with {len(candidates)} candidates, {len(required_slots)} slots, {n_days} days")
    solver = PULP_CBC_CMD(timeLimit=int(time_limit_sec), msg=0)
    model.solve(solver)
    status = str(LpStatus.get(model.status, model.status))
    print(f"[LP] Status: {status}")

    selected_rows: List[Dict] = []
    for d in days:
        for i in candidates.index:
            if float(y[(d, int(i))].varValue or 0) > 0.5:
                row = candidates.loc[i].to_dict()
                row["Day"] = d
                row["Serving"] = float(x[(d, int(i))].varValue or 0)
                selected_rows.append(row)

    weekly_menu = pd.DataFrame(selected_rows)
    if not weekly_menu.empty:
        weekly_menu = weekly_menu.sort_values(
            ["Day", "Meal_Time", "Dish_Type"]
        ).reset_index(drop=True)
        print(f"[LP] Optimal plan: {len(weekly_menu)} rows across {n_days} days")
    else:
        # Fallback: top candidate per slot per day
        print(f"[LP] Falling back to top-candidate plan (LP status: {status})")
        fallback_rows = []
        for d in days:
            for _, slot_row in required_slots.iterrows():
                slot = (str(slot_row["Meal_Time"]), str(slot_row["Dish_Type"]))
                ids = slot_to_ids.get(slot, [])
                if ids:
                    row = candidates.loc[ids[0]].to_dict()
                    row["Day"] = d
                    row["Serving"] = 1.0
                    fallback_rows.append(row)
        weekly_menu = pd.DataFrame(fallback_rows)
        print(f"[LP] Fallback plan: {len(weekly_menu)} rows")

    summary = {
        "status": status,
        "objective": float(value(model.objective)) if model.objective is not None else np.nan,
        "objective_metric": objective_metric_col,
        "category_weekly_rep": int(category_weekly_rep) if category_weekly_rep else None,
        "rows": int(len(weekly_menu)),
        "days": int(n_days),
        "required_slots": int(len(required_slots)),
    }
    return weekly_menu, summary
