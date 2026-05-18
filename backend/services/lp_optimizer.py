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
    weekly_rep: int = 10,
    category_weekly_rep: Optional[int] = 10,
    non_snack_serving_bounds: Tuple[float, float] = (0.5, 1.0),
    snack_serving_bounds: Tuple[float, float] = (0.5, 1.0),
    time_limit_sec: int = 300,
    per_meal_gl_cap: int = 30,
    per_day_gl_cap: int = 90,
    per_recipe_max_gl: int = 20,
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

    candidates = meal_choices.copy()
    dedup_subset = ["Meal_Time", "Dish_Type", "Recipe_Code", "Preference_Row_ID"]
    candidates = candidates.drop_duplicates(subset=dedup_subset).reset_index(drop=True)
    if candidates.empty:
        return pd.DataFrame(), {"status": "no_candidates"}

    required_cols = [
        "Recipe_Code","Recipe_Name","Recipe_Category", "Code_cooccurence", "Preferred_SubCategory_code", "Preference_Row_ID", "Meal_Time", "Dish_Type",
        "GL", "Avg_TimeAbove160_pct", "Avg_Delta_Glucose", "Energy_ENERC_Kcal", "Energy_ENERC_KJ",
        "Protein_PROTCNT_g", "TotalFat_FATCE_g", "TotalDietaryFibre_FIBTG_g", "CalciumCa_CA_mg", "ZincZn_ZN_mg",
        "IronFe_FE_mg", "MagnesiumMg_MG_mg", "VA_RAE_mcg", "TotalFolatesB9_FOLSUM_mcg", "VB12_mcg",
        "ThiamineB1_THIA_mg", "RiboflavinB2_RIBF_mg", "NiacinB3_NIA_mg", "TotalB6A_VITB6A_mg", "TotalAscorbicAcid_VITC_mg",
        "Carbohydrate_g", "Sodium_mg", "VITE_mg", "PhosphorusP_mg","PotassiumK_mg","Cholesterol_mg"
    ]
    
    keep_cols = [col for col in required_cols if col in candidates.columns]
    candidates = candidates[keep_cols].copy()
    candidates = candidates.drop_duplicates().reset_index(drop=True)
    candidates["__candidate_id__"] = np.arange(len(candidates), dtype=np.int64)

    candidates["Dish_Type"] = candidates["Dish_Type"].astype(str).str.strip()
    candidates["Preference_Row_ID"] = candidates["Preference_Row_ID"].astype(str).str.strip()
    candidates["Meal_Time"] = candidates["Meal_Time"].astype(str).str.strip()

    candidates["Main_Category_code"] = (
        candidates.get("MainCategoryCode", candidates.get("Code_cooccurence", ""))
        .astype(str)
        .str.strip()
        .str.upper()
    )
    
    if "Recipe_Category" in candidates.columns:
        candidates["Category_Key"] = candidates["Recipe_Category"].astype(str).str.strip()
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

    if candidates["GL"].isna().any():
        gl_median = candidates["GL"].median()
        if pd.isna(gl_median):
            gl_median = 10.0
        candidates["GL"] = candidates["GL"].fillna(gl_median)
    for col in ["Avg_TimeAbove160_pct", "Avg_Delta_Glucose"]:
        if candidates[col].isna().any():
            candidates[col] = candidates[col].fillna(0.0)

    for col in ["Avg_TimeAbove160_pct", "Avg_Delta_Glucose"]:
        mean_val = float(candidates[col].mean())
        std_val = float(candidates[col].std(ddof=0))
        if std_val <= 1e-12:
            candidates[f"{col}_z"] = 0.0
        else:
            candidates[f"{col}_z"] = (candidates[col] - mean_val) / std_val

    candidates.to_csv("candidates_pre_objective.csv", index=False)
    
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
    weekly_min_100 = weekly_min.copy()
    
    eff_daily = None
    upper_mult = 1.2  
    
    if daily_energy_kcal is not None:
        eff_daily = float(daily_energy_kcal)
        if profile is not None:
            _bmi = profile.get("bmi")
            if _bmi is not None:
                _bmi_val = float(_bmi)
                if _bmi_val >= 23.0 and _bmi_val < 25.0:
                    eff_daily = eff_daily * 0.8 
                    weekly_min = {k: v * 0.8 for k, v in weekly_min.items()}
                if _bmi_val >= 25.0:
                    eff_daily = eff_daily * 0.7 
                    weekly_min = {k: v * 0.7 for k, v in weekly_min.items()}

        if profile is not None:
            _age = profile.get("age")
            if _age is not None:
                _age_val = float(_age)
                if _age_val > 60:
                    eff_daily = eff_daily * 0.9 
                    weekly_min = {k: v * 0.9 for k, v in weekly_min.items()}
                elif _age_val > 50:
                    eff_daily = eff_daily * 0.95 
                    weekly_min = {k: v * 0.95 for k, v in weekly_min.items()}

    slot_to_ids: Dict[Tuple[str, str], List[int]] = {}

    candidates = candidates.copy(deep=True)
    candidates = candidates.reset_index(drop=True)
    if "__candidate_id__" not in candidates.columns:
        raise RuntimeError("Missing stable candidate id before model build")
    if candidates["__candidate_id__"].duplicated().any():
        raise RuntimeError("Duplicate stable candidate ids detected")

    if objective_metric_col not in candidates.columns:
        candidates[objective_metric_col] = 0.0
    else:
        candidates[objective_metric_col] = pd.to_numeric(candidates[objective_metric_col], errors="coerce")
        if candidates[objective_metric_col].isna().all():
            candidates[objective_metric_col] = 0.0
        else:
            med = candidates[objective_metric_col].median()
            candidates[objective_metric_col] = candidates[objective_metric_col].fillna(med)

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
        rig_valid['Food Group'] = rig_valid['Food Group'].astype(str).str.strip().str.lower()
        
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
        candidates['Sugar_per_serving_g'] = 0.0
        candidates['Salt_per_serving_g'] = 0.0

    if per_recipe_max_gl is not None:
        _per = float(per_recipe_max_gl)
        candidates = candidates[pd.to_numeric(candidates.get("GL", 0), errors="coerce") <= _per].reset_index(drop=True)
    
    slot_to_ids = {}
    for _, row in candidates.iterrows():
        cid = int(row["__candidate_id__"])
        slot_to_ids.setdefault((str(row["Meal_Time"]), str(row["Dish_Type"])), []).append(cid)

    candidates = candidates.set_index("__candidate_id__", drop=False)
    candidate_ids = candidates.index.to_list()

    days = list(range(1, int(n_days) + 1))
    model = LpProblem("weekly_menu_min_weighted_gl_time_delta", LpMinimize)

    y = {}
    x = {}
    for d in days:
        for i in candidate_ids:
            y[(d, i)] = LpVariable(f"y_d{d}_r{i}", lowBound=0, upBound=1, cat="Binary")
            x[(d, i)] = LpVariable(f"x_d{d}_r{i}", lowBound=0)
            
    # Step 1: Initialize baseline objective function (GL minimization)
    model += lpSum(float(candidates.loc[i, objective_metric_col]) * x[(d, i)] for d in days for i in candidate_ids)

    for d in days:
        for _, slot_row in required_slots.iterrows():
            slot = (str(slot_row["Meal_Time"]), str(slot_row["Dish_Type"]))
            ids = slot_to_ids.get(slot, [])
            if not ids:
                continue
            dtype = str(slot_row["Dish_Type"]).strip()
            if dtype == "Snacks":
                model += lpSum(y[(d, i)] for i in ids) <= 2
                model += lpSum(y[(d, i)] for i in ids) >= 0
            elif dtype in ("Main 2","Main 3", "Optional", "Beverage"):
                model += lpSum(y[(d, i)] for i in ids) <= 1
            else:
                model += lpSum(y[(d, i)] for i in ids) == 1

    snack_ids = []
    for _, slot_row in required_slots.iterrows():
        if str(slot_row["Dish_Type"]).strip() == "Snacks":
            slot = (str(slot_row["Meal_Time"]), str(slot_row["Dish_Type"]))
            snack_ids.extend(slot_to_ids.get(slot, []))
    if snack_ids:
        model += lpSum(y[(d, i)] for d in days for i in snack_ids) >= 5

    for d in days:
        for i in candidates.index:
            mt = str(candidates.loc[i, "Meal_Time"]).strip()
            dt = str(candidates.loc[i, "Dish_Type"]).strip().lower()
            if mt.lower() == "breakfast":
                if dt.lower() == "main 3":
                    model += y[(d, int(i))] == 0
                if dt.lower() == "optional":
                    model += y[(d, int(i))] <= 1
            elif mt.lower() == "lunch": 
                pass
            elif mt.lower() == "dinner":
                if dt.lower() == "main 3":
                    model += y[(d, int(i))] == 0
                if dt.lower() == "optional":
                    model += y[(d, int(i))] <= 1

    # =================================================================
    # INTRA-MEAL SUBCATEGORY VARIETY CONSTRAINT (NO DUPLICATES IN A SLOT)
    # =================================================================
    # Ensures that for a given Day and Meal Time, the same subcategory
    # code (e.g., Sandwiches, Parathas) cannot be chosen more than once.
    if "Preferred_SubCategory_code" in candidates.columns:
        # Filter out empty or missing subcategory rows to avoid matching nulls
        subcat_df = candidates.dropna(subset=["Preferred_SubCategory_code"]).copy()
        subcat_df["Preferred_SubCategory_code"] = subcat_df["Preferred_SubCategory_code"].astype(str).str.strip()
        subcat_df = subcat_df[subcat_df["Preferred_SubCategory_code"] != ""]

        for d in days:
            # Group candidates by Meal Time and Subcategory Code
            for (meal_time, subcat_code), group_df in subcat_df.groupby(["Meal_Time", "Preferred_SubCategory_code"]):
                ids = [int(i) for i in group_df.index.tolist()]
                
                if len(ids) > 1:
                    # The sum of binary activation variables 'y' for this subcategory 
                    # in this specific meal time on this day cannot exceed 1
                    model += lpSum(y[(d, i)] for i in ids) <= 1

    for d in days:
        for meal_time in candidates["Meal_Time"].dropna().unique():
            meal_mask = candidates["Meal_Time"] == meal_time
            for pref_id, group in candidates[meal_mask].groupby("Preference_Row_ID"):
                mains = group[group["Dish_Type"].astype(str).str.strip() == "Main"].index.tolist()
                mains2 = group[group["Dish_Type"].astype(str).str.strip() == "Main 2"].index.tolist()
                mains3 = group[group["Dish_Type"].astype(str).str.strip() == "Main 3"].index.tolist()
                sides = group[group["Dish_Type"].astype(str).str.strip().str.lower() == "Optional"].index.tolist()

                if mains and mains2:
                    model += lpSum(y[(d, i)] for i in mains) == lpSum(y[(d, j)] for j in mains2)
                    model += lpSum(x[(d, i)] for i in mains) >= lpSum(x[(d, j)] for j in mains2)
                else:
                    if not mains and mains2:
                        model += lpSum(y[(d, j)] for j in mains2) == 0
                    if not mains and mains3:
                        model += lpSum(y[(d, k)] for k in mains3) == 0
                    if not mains and sides:
                        model += lpSum(y[(d, s)] for s in sides) == 0

                if mains:
                    model += lpSum(y[(d, i)] for i in mains) <= 1
                if mains2:
                    model += lpSum(y[(d, j)] for j in mains2) <= 1
                if mains3:
                    model += lpSum(y[(d, k)] for k in mains3) <= 1
                if sides:
                    model += lpSum(y[(d, s)] for s in sides) <= 1

                if mains and sides:
                    main_selected = lpSum(y[(d, i)] for i in mains)
                    sides_selected = lpSum(y[(d, s)] for s in sides)
                    model += sides_selected <= main_selected

                if mains2 and mains3:
                    for main3 in mains3:
                        model += y[(d, main3)] <= lpSum(y[(d, j)] for j in mains2)

    pairing_debug_rows = []
    for d in days:
        for meal_time in sorted(candidates["Meal_Time"].dropna().astype(str).unique().tolist()):
            slot_candidates = candidates[candidates["Meal_Time"].astype(str) == str(meal_time)]
            for pref_id, group in slot_candidates.groupby("Preference_Row_ID"):
                main_ids = group[group["Dish_Type"].astype(str).str.strip() == "Main"].index.tolist()
                main2_ids = group[group["Dish_Type"].astype(str).str.strip() == "Main 2"].index.tolist()
                main3_ids = group[group["Dish_Type"].astype(str).str.strip() == "Main 3"].index.tolist()
                pairing_debug_rows.append({
                    "Day": d,
                    "Meal_Time": meal_time,
                    "Preference_Row_ID": pref_id,
                    "main_ids": ";".join([str(x) for x in main_ids]),
                    "main2_ids": ";".join([str(x) for x in main2_ids]),
                    "main3_ids": ";".join([str(x) for x in main3_ids]),
                    "has_main": bool(len(main_ids) > 0),
                    "has_main2": bool(len(main2_ids) > 0),
                    "has_main3": bool(len(main3_ids) > 0),
                })
    pd.DataFrame(pairing_debug_rows).to_csv("pairing_constraints_debug.csv", index=False)

    for d in days:
        for idx, row in candidates.iterrows():
            i = int(idx)
            meal_time = str(row.get("Meal_Time", ""))
            lb, ub = snack_serving_bounds if meal_time == "Snacks" else non_snack_serving_bounds
            model += x[(d, i)] <= float(ub) * y[(d, i)]
            model += x[(d, i)] >= float(lb) * y[(d, i)]

    if per_meal_gl_cap is not None:
        pmeal = float(per_meal_gl_cap)
        for d in days:
            for _, slot_row in required_slots.iterrows():
                slot = (str(slot_row["Meal_Time"]), str(slot_row["Dish_Type"]))
                ids = slot_to_ids.get(slot, [])
                if not ids:
                    continue
                model += lpSum(float(candidates.loc[i, "GL"]) * x[(d, int(i))] for i in ids) <= float(pmeal)

    if per_day_gl_cap is not None:
        pday = float(per_day_gl_cap)
        for d in days:
            model += lpSum(float(candidates.loc[i, "GL"]) * x[(d, int(i))] for i in candidates.index) <= float(pday)




    # ========================================================
    # OPTIMIZED SOFT PENALTY FOR RECIPE & CATEGORY REPETITION
    # ========================================================
    recipe_penalty_weight = 2000.0   
    category_penalty_weight = 1000.0 
    variety_penalties = []

    # 1) Fast Recipe Repetition Penalty
    # We only create penalty variables for recipes that have enough entries to actually repeat
    for (meal_time, dish_type, recipe_code), group_df in candidates.groupby(["Meal_Time", "Dish_Type", "Recipe_Code"], dropna=False):
        ids = [int(i) for i in group_df.index.tolist()]
        
        # If there's only 1 candidate entry total, it physically cannot repeat past 1, so skip creating a variable!
        if len(ids) <= 1:
            continue
            
        safe_mt = str(meal_time).replace(" ", "_").replace("-", "_")
        safe_dt = str(dish_type).replace(" ", "_").replace("-", "_")
        safe_rc = str(recipe_code).replace(" ", "_").replace("-", "_")
        
        v_recipe = LpVariable(f"recipe_excess_{safe_mt}_{safe_dt}_{safe_rc}", lowBound=0)
        model += lpSum(y[(d, i)] for d in days for i in ids) <= 1 + v_recipe
        variety_penalties.append(recipe_penalty_weight * v_recipe)

    # 2) Fast Category Repetition Penalty 
    category_df = candidates.dropna(subset=["Category_Key"]).copy()
    for (dish_type, category_key), group_df in category_df.groupby(["Dish_Type", "Category_Key"], dropna=False):
        dish_type_u = str(dish_type).strip().upper()
        
        # Only apply category variety penalties to core Mains (skipping sides/beverages saves massive solver time)
        if dish_type_u not in ("MAIN", "MAIN 2", "MAIN 3"):
            continue
            
        ids = [int(i) for i in group_df.index.tolist()]
        if len(ids) > 2: # Only penalize if there are enough items to actually exceed the limit
            safe_dt = str(dish_type).replace(" ", "_").replace("-", "_")
            safe_ck = str(category_key).replace(" ", "_").replace("-", "_").replace("/", "_")
            
            v_category = LpVariable(f"category_excess_{safe_dt}_{safe_ck}", lowBound=0)
            model += lpSum(y[(d, i)] for d in days for i in ids) <= 2 + v_category
            variety_penalties.append(category_penalty_weight * v_category)




    ##### faster with hard repetation constraints 
    # ==========================================
    # INSERT THIS NEW FAST DYNAMIC BOUNDS BLOCK:
    # ==========================================
    # # Step 2: Fast Dynamic Recipe Repetition Constraints
    # variety_penalties = [] # Initialized empty so Step 4 doesn't break

    # # Group by slot to see how many unique recipes are actually competing
    # for (meal_time, dish_type), slot_group in candidates.groupby(["Meal_Time", "Dish_Type"]):
    #     unique_recipes = slot_group["Recipe_Code"].nunique()
        
    #     # Dynamically set a safe hard cap based on availability
    #     if unique_recipes <= 2:
    #         max_rep = 7  # Scarce choices: allow repeating all week
    #     elif unique_recipes <= 5:
    #         max_rep = 3  # Medium choices: allow up to 3 times
    #     else:
    #         max_rep = 2  # Abundant choices: force high variety (max 2 times)

    #     for recipe_code, sub_group in slot_group.groupby("Recipe_Code"):
    #         ids = [int(i) for i in sub_group.index.tolist()]
    #         model += lpSum(y[(d, i)] for d in days for i in ids) <= max_rep

    # # Fast Dynamic Category Repetition Constraints
    # if category_weekly_rep is not None and category_weekly_rep > 0:
    #     category_df = candidates.dropna(subset=["Category_Key"]).copy()
    #     for dish_type, dish_group in category_df.groupby("Dish_Type"):
    #         dish_type_u = str(dish_type).strip().upper()
    #         if dish_type_u not in ("MAIN", "MAIN 2", "MAIN 3"):
    #             continue
                
    #         unique_categories = dish_group["Category_Key"].nunique()
    #         if unique_categories == 1:
    #             max_cat_rep = 7
    #         elif unique_categories == 2:
    #             max_cat_rep = 4
    #         else:
    #             max_cat_rep = 3  # Fallback safe variety threshold

    #         for category_key, sub_group in dish_group.groupby("Category_Key"):
    #             ids = [int(i) for i in sub_group.index.tolist()]
    #             if ids:
    #                 model += lpSum(y[(d, i)] for d in days for i in ids) <= max_cat_rep


    # Step 3: Track Nutrient Penalties
    nutrient_slacks = {}
    penalty_terms = []
    penalty_weight = 100.0

    for col, req in weekly_min.items():
        if col not in candidates.columns or req <= 0:
            continue

        if profile and isinstance(profile, dict):
            dt = str(profile.get("diet_type", "")).strip().lower()
            if dt and dt != "non-veg" and col == "VB12_mcg":
                continue

        safe_col = col.replace(" ", "_").replace("-", "_")
        slack = LpVariable(f"nutrient_shortfall_{safe_col}", lowBound=0)
        nutrient_slacks[col] = slack

        model += lpSum(float(candidates.loc[i, col]) * x[(d, int(i))] for d in days for i in candidates.index) + slack >= float(req)
        penalty_terms.append(penalty_weight * slack)

    # Step 4: Safely combine ALL penalties using += to avoid erasing the GL objective
    if variety_penalties:
        model.objective += lpSum(variety_penalties)
    if penalty_terms:
        model.objective += lpSum(penalty_terms)

    if eff_daily is not None and "Energy_ENERC_Kcal" in candidates.columns:
        for d in days:
            daily_kcal = lpSum(float(candidates.loc[i, "Energy_ENERC_Kcal"]) * x[(d, int(i))] for i in candidates.index)
            model += daily_kcal >= float(eff_daily)
            model += daily_kcal <= float(eff_daily) * float(upper_mult)

    candidates["Carb_g"] = pd.to_numeric(candidates.get("Carbohydrate_g", 0), errors="coerce").fillna(0.0)
    candidates["Prot_g"] = pd.to_numeric(candidates.get("Protein_PROTCNT_g", 0), errors="coerce").fillna(0.0)
    candidates["Fat_g"] = pd.to_numeric(candidates.get("TotalFat_FATCE_g", 0), errors="coerce").fillna(0.0)
    candidates["Energy_kcal"] = pd.to_numeric(candidates.get("Energy_ENERC_Kcal", 0), errors="coerce").fillna(0.0)
    for d in days:
        model += lpSum((4.0 * candidates.loc[i, "Carb_g"] - 0.45 * candidates.loc[i, "Energy_kcal"]) * x[(d, int(i))] for i in candidates.index) >= 0.0
        model += lpSum((4.0 * candidates.loc[i, "Carb_g"] - 0.50 * candidates.loc[i, "Energy_kcal"]) * x[(d, int(i))] for i in candidates.index) <= 0.0

        model += lpSum((4.0 * candidates.loc[i, "Prot_g"] - 0.15 * candidates.loc[i, "Energy_kcal"]) * x[(d, int(i))] for i in candidates.index) >= 0.0
        model += lpSum((4.0 * candidates.loc[i, "Prot_g"] - 0.20 * candidates.loc[i, "Energy_kcal"]) * x[(d, int(i))] for i in candidates.index) <= 0.0

        model += lpSum((9.0 * candidates.loc[i, "Fat_g"] - 0.25 * candidates.loc[i, "Energy_kcal"]) * x[(d, int(i))] for i in candidates.index) >= 0.0
        model += lpSum((9.0 * candidates.loc[i, "Fat_g"] - 0.35 * candidates.loc[i, "Energy_kcal"]) * x[(d, int(i))] for i in candidates.index) <= 0.0

        min_carbs_per_day = 130.0
        model += lpSum(candidates.loc[i, "Carb_g"] * x[(d, int(i))] for i in candidates.index) >= float(min_carbs_per_day)

    candidates["Fiber_g"] = pd.to_numeric(candidates.get("TotalDietaryFibre_FIBTG_g", 0), errors="coerce").fillna(0.0)
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
        model += daily_fiber * 1000.0 >= 14.0 * daily_energy
        if _gender_min is not None:
            model += daily_fiber >= float(_gender_min)

    for col, max_req in weekly_max.items():
        if col not in candidates.columns or max_req <= 0:
            continue
        model += lpSum(float(candidates.loc[i, col]) * x[(d, int(i))] for d in days for i in candidates.index) <= float(max_req) * 1.2

    if 'Sugar_per_serving_g' in candidates.columns and 'Energy_ENERC_Kcal' in candidates.columns:
        for d in days:
            sugar_energy = lpSum(4.0 * float(candidates.loc[i, 'Sugar_per_serving_g']) * x[(d, int(i))] for i in candidates.index)
            daily_energy = lpSum(float(candidates.loc[i, 'Energy_ENERC_Kcal']) * x[(d, int(i))] for i in candidates.index)
            model += sugar_energy <= 0.05 * daily_energy

    sodium_limit_per_day_mg = 1500.0
    if 'Sodium_mg' in candidates.columns:
        model += lpSum(float(candidates.loc[i, 'Sodium_mg']) * x[(d, int(i))] for d in days for i in candidates.index) <= float(sodium_limit_per_day_mg) * float(n_days)

    cholesterol_limit_per_day_mg = 300.0
    if 'Cholesterol_mg' in candidates.columns:
        for d in days:
            model += lpSum(float(candidates.loc[i, 'Cholesterol_mg']) * x[(d, int(i))] for i in candidates.index) <= float(cholesterol_limit_per_day_mg)

    salt_limit_per_day_g = 5
    if 'Salt_per_serving_g' in candidates.columns:
        model += lpSum(float(candidates.loc[i, 'Salt_per_serving_g']) * x[(d, int(i))] for d in days for i in candidates.index) <= float(salt_limit_per_day_g) * float(n_days)

    # solver = PULP_CBC_CMD(timeLimit=int(time_limit_sec))
    solver = PULP_CBC_CMD(timeLimit=int(time_limit_sec), gapRel=0.1, threads=4)
    _ = model.solve(solver)
    status = str(LpStatus.get(model.status, model.status))

    selected_rows: List[Dict[str, object]] = []
    if status == "Optimal":
        for d in days:
            for i in candidates.index:
                if float(y[(d, int(i))].value() or 0) > 0.5:
                    row = candidates.loc[i].to_dict()
                    row.pop("__candidate_id__", None)
                    row["Day"] = d
                    row["Serving"] = float(x[(d, int(i))].value() or 0)
                    selected_rows.append(row)

    candidates.to_csv("candidates_with_metrics.csv", index=False)
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
    pd.DataFrame(vars_rows).to_csv("final_y_x_values_postsolve.csv", index=False)

    weekly_menu = pd.DataFrame(selected_rows)
    if not weekly_menu.empty:
        weekly_menu = weekly_menu.sort_values(["Day", "Meal_Time", "Dish_Type"]).reset_index(drop=True)
    else:
        fallback_rows = []
        for d in days:
            for _, slot_row in required_slots.iterrows():
                slot = (str(slot_row["Meal_Time"]), str(slot_row["Dish_Type"]))
                ids = slot_to_ids.get(slot, [])
                if ids:
                    i = ids[0]
                    row = candidates.loc[i].to_dict()
                    row.pop("__candidate_id__", None)
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
    return weekly_menu, summary, weekly_min_100