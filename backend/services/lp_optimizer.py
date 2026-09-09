"""
Custom LP optimizer for ModelOptimiser.

Reimplements optimize_weekly_menu_with_constraints without the hard
macronutrient percentage constraints (carbs 45-50%, protein 15-20%,
fiber >= 25g/day) that make the original LP infeasible for Indian food.

Preserved constraints: slot coverage, Main/Main2 pairing, serving bounds,
recipe/category repetition limits, nutrient soft goals, sodium/cholesterol caps.
"""

from __future__ import annotations

import logging
import os
import tempfile
import time
import uuid
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger("backend.services.lp_optimizer")


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
    time_limit_sec: int = 600,
    per_meal_gl_cap: int = 30,
    per_day_gl_cap: int = 90,
    per_recipe_max_gl: int = 20,
    liked_recipe_bonus: float = 2000.0,
    recipe_ing_df: Optional[pd.DataFrame] = None,
    main1_main2_mapping: Optional[pd.DataFrame] = None,
    ear_100: Optional[pd.DataFrame] = None,
    tul: Optional[pd.DataFrame] = None,
    profile: Optional[Dict] = None,
) -> Tuple[pd.DataFrame, Dict]:
    debug_dir: Path | None = None

    def _write_debug_csv(df: pd.DataFrame, filename: str) -> None:
        nonlocal debug_dir
        if os.getenv("DEBUG_OPTIMIZER") != "1":
            return
        if debug_dir is None:
            root = Path(os.getenv("OPTIMIZER_DEBUG_DIR", tempfile.gettempdir()))
            debug_dir = root / "adam_optimizer_debug" / f"lp_{int(time.time())}_{uuid.uuid4().hex[:8]}"
            debug_dir.mkdir(parents=True, exist_ok=True)
            logger.info("Writing optimizer debug CSVs to %s", debug_dir)
        df.to_csv(debug_dir / filename, index=False)

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
        "Vegetarian", "Ovo-vegetarian",
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

    # Sanity-clip Sodium_mg: a subset of the source Recipe nutrient data has
    # physically implausible sodium values (up to 35,580mg/serving, for a
    # plain dosa) — confirmed data/unit errors affecting a batch of entries
    # across unrelated dish types (a coconut-water chutney and a smoothie
    # both show 10,000+mg), not a real food property. Cholesterol was
    # checked too and found clean (its high values are all legitimately
    # egg/organ-meat dishes) — this clip is sodium-only. Values above the
    # ceiling are replaced with the column median rather than dropped, so
    # the LP's sodium constraints and downstream reporting aren't driven by
    # corrupted numbers without having to hand-identify every bad row.
    if "Sodium_mg" in candidates.columns:
        _sodium_ceiling = 3000.0
        _sodium_median = float(candidates["Sodium_mg"].median())
        _sodium_outliers = candidates["Sodium_mg"] > _sodium_ceiling
        if _sodium_outliers.any():
            candidates.loc[_sodium_outliers, "Sodium_mg"] = _sodium_median

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

    _write_debug_csv(candidates, "candidates_pre_objective.csv")
    
    candidates["Weighted_Objective_Score"] = (
        500 * candidates["GL"]
        + 0.3 * candidates["Avg_TimeAbove160_pct_z"]
        + 0.2 * candidates["Avg_Delta_Glucose_z"]
    )

    # Give the user's explicitly-liked recipes (ds["liked_recipe_codes"], set by
    # services/data_loader.py) a discount on their objective score, so the LP
    # actually prefers them over an equally-valid alternative in the same slot
    # instead of just making them eligible candidates. Sized to flip a choice
    # between recipes of similar GL (a handful of GL units, at 500/unit) without
    # overriding a much-healthier option — GL still wins in extreme cases, since
    # this is a diabetes meal planner and preference shouldn't trump safety.
    liked_codes = {str(c).strip().upper() for c in (ds.get("liked_recipe_codes") or set())}
    if liked_codes and liked_recipe_bonus:
        is_liked = candidates["Recipe_Code"].astype(str).str.strip().str.upper().isin(liked_codes)
        candidates.loc[is_liked, "Weighted_Objective_Score"] -= float(liked_recipe_bonus)

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

    # Weeks 1-2 taper: routers/plan.py sets profile["_bmi_age_reduction_strength"]
    # to dampen how much of the BMI/age downward scaling below actually
    # applies — 0.0 skips it entirely (week 1: target stays the full,
    # unreduced TDEE-based number), 0.5 applies half of each normal cut
    # (week 2), 1.0 (the default when unset, i.e. week 3+) is the full,
    # untouched system behavior. Blending is per reduction step, so e.g. the
    # BMI≥25 rule's normal 30%-cut (×0.7) becomes a 15%-cut (×0.85) at 0.5.
    reduction_strength = float((profile or {}).get("_bmi_age_reduction_strength", 1.0))

    def _dampened_mult(normal_mult: float) -> float:
        return 1.0 - reduction_strength * (1.0 - normal_mult)

    if daily_energy_kcal is not None:
        eff_daily = float(daily_energy_kcal)
        if profile is not None and reduction_strength > 0:
            _bmi = profile.get("bmi")
            if _bmi is not None:
                _bmi_val = float(_bmi)
                # Both BMI brackets now cut by the same 10% (x0.9) at full
                # strength -- previously 20%/30% (x0.8/x0.7) depending on how
                # far over the threshold. Still phased in by reduction_strength
                # same as before (0%/50%/100% across week1/2/3), just a
                # smaller ceiling on the cut itself.
                if _bmi_val >= 23.0 and _bmi_val < 25.0:
                    m = _dampened_mult(0.9)
                    eff_daily = eff_daily * m
                    weekly_min = {k: v * m for k, v in weekly_min.items()}
                if _bmi_val >= 25.0:
                    m = _dampened_mult(0.9)
                    eff_daily = eff_daily * m
                    weekly_min = {k: v * m for k, v in weekly_min.items()}

        if profile is not None and reduction_strength > 0:
            _age = profile.get("age")
            if _age is not None:
                _age_val = float(_age)
                if _age_val > 60:
                    m = _dampened_mult(0.9)
                    eff_daily = eff_daily * m
                    weekly_min = {k: v * m for k, v in weekly_min.items()}
                elif _age_val > 50:
                    m = _dampened_mult(0.95)
                    eff_daily = eff_daily * m
                    weekly_min = {k: v * m for k, v in weekly_min.items()}

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
        rig_valid = rig_df.dropna(subset=['Ing_raw_amounts_g', 'Food_Group']).copy()
        rig_valid['Food_Group'] = rig_valid['Food_Group'].astype(str).str.strip().str.lower()
        
        sugars = (
            rig_valid.loc[rig_valid['Food_Group'] == 'sugars']
            .groupby('Recipe_Code', dropna=False)['Ing_raw_amounts_g']
            .sum()
            .rename('Sugar_per_serving_g')
        )
        if not sugars.empty:
            sug_df = sugars.reset_index()
            candidates = candidates.merge(sug_df, on='Recipe_Code', how='left')
            candidates['Sugar_per_serving_g'] = candidates['Sugar_per_serving_g'].fillna(0.0)
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
            mask_salt = rig_valid['Food_Group'].astype(str).str.contains('salt', case=False, na=False)
            salt_series = (
                rig_valid.loc[mask_salt]
                .groupby('Recipe_Code', dropna=False)['Ing_raw_amounts_g']
                .sum()
                .rename('Salt_per_serving_g')
            )
        if not salt_series.empty:
            salt_df = salt_series.reset_index()
            candidates = candidates.merge(salt_df, on='Recipe_Code', how='left')
            candidates['Salt_per_serving_g'] = candidates['Salt_per_serving_g'].fillna(0.0)
        else:
            candidates['Salt_per_serving_g'] = 0.0
    else:
        candidates['Sugar_per_serving_g'] = 0.0
        candidates['Salt_per_serving_g'] = 0.0

    # if per_recipe_max_gl is not None:
    #     _per = float(per_recipe_max_gl)
    #     candidates = candidates[pd.to_numeric(candidates.get("GL", 0), errors="coerce") <= _per].reset_index(drop=True)
    
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

                if mains3:
                    if mains2:
                        for main3 in mains3:
                            model += y[(d, main3)] <= lpSum(y[(d, j)] for j in mains2)
                    else:
                        model += lpSum(y[(d, k)] for k in mains3) == 0

    if os.getenv("DEBUG_OPTIMIZER") == "1":
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
        _write_debug_csv(pd.DataFrame(pairing_debug_rows), "pairing_constraints_debug.csv")

    # First-weeks portion taper: routers/plan.py stashes (lb, ub) overrides
    # for a plan's early weeks, raising the *minimum* serving so the LP is
    # forced toward larger real-world portions (matching what users already
    # tend to eat) instead of just permitting them — a higher upper bound
    # alone wouldn't change anything, since the GL-minimizing objective would
    # still settle on the smallest feasible serving. Three independent
    # profile keys since Main, Main2/Main3, and Snacks can each need a
    # different range: _main_taper_bounds (Dish_Type=="Main" only),
    # _other_taper_bounds (Main2/Main3), _snack_taper_bounds (Snacks). Falls
    # back to the flat _portion_taper_bounds (both Main and Main2/Main3
    # together) when the per-dish-type keys aren't set, then to the normal
    # system default once routers/plan.py stops setting any override.
    main_taper_bounds = (profile or {}).get("_main_taper_bounds")
    other_taper_bounds = (profile or {}).get("_other_taper_bounds")
    taper_bounds = (profile or {}).get("_portion_taper_bounds")
    snack_taper_bounds = (profile or {}).get("_snack_taper_bounds")

    for d in days:
        for idx, row in candidates.iterrows():
            i = int(idx)
            meal_time = str(row.get("Meal_Time", ""))
            dish_type = str(row.get("Dish_Type", "")).strip()
            if meal_time == "Snacks":
                lb, ub = snack_taper_bounds if snack_taper_bounds else snack_serving_bounds
            elif dish_type in ("Optional", "Beverage"):
                # Fixed regardless of week/taper — a beverage/side attached
                # to a main meal (e.g. Black Coffee alongside Breakfast) was
                # otherwise inheriting the wide Main2/Main3 taper range,
                # letting it scale up to "2 glasses of coffee" in week 1.
                lb, ub = snack_serving_bounds
            elif dish_type == "Main" and main_taper_bounds:
                lb, ub = main_taper_bounds
            elif dish_type != "Main" and other_taper_bounds:
                lb, ub = other_taper_bounds
            elif taper_bounds:
                lb, ub = taper_bounds
            else:
                lb, ub = non_snack_serving_bounds
            model += x[(d, i)] <= float(ub) * y[(d, i)]
            model += x[(d, i)] >= float(lb) * y[(d, i)]

    # Early-week GL cap/floor relaxation: routers/plan.py overrides these via
    # profile so weeks 1-2 can carry the bigger mandated portions above
    # without the caps/floors contradicting the serving bounds set above.
    # _per_meal_gl_cap_by_slot lets a week tighten specific meal times (e.g.
    # Breakfast) independently of the flat fallback, since a single uniform
    # cap wasn't enough to keep every slot's realized GL tapering down
    # cleanly week over week — some slots settle well under a loose flat cap
    # regardless, while others need a tighter one to actually move.
    # _per_meal_gl_cap_override / _per_day_gl_cap_override (below) are part of
    # TAPER_OVERRIDE_KEYS in routers/plan.py and get popped by the
    # retry-without-taper fallback if the first solve fails — fine for a
    # taper-week override, wrong for a permanent per-user override (which
    # should survive that retry). _user_per_meal_gl_cap_override /
    # _user_per_day_gl_cap_override are the same mechanism under distinct
    # names outside TAPER_OVERRIDE_KEYS, so a per-user override (e.g. A002's
    # hard-mandate accommodation) isn't silently stripped mid-retry.
    effective_per_meal_gl_cap = (
        (profile or {}).get("_user_per_meal_gl_cap_override")
        or (profile or {}).get("_per_meal_gl_cap_override", per_meal_gl_cap)
    )
    per_meal_gl_cap_by_slot = (profile or {}).get("_per_meal_gl_cap_by_slot") or {}
    for d in days:
        for _, slot_row in required_slots.iterrows():
            meal_time = str(slot_row["Meal_Time"])
            slot = (meal_time, str(slot_row["Dish_Type"]))
            ids = slot_to_ids.get(slot, [])
            if not ids:
                continue
            pmeal = per_meal_gl_cap_by_slot.get(meal_time, effective_per_meal_gl_cap)
            if pmeal is not None:
                model += lpSum(float(candidates.loc[i, "GL"]) * x[(d, int(i))] for i in ids) <= float(pmeal)

    effective_per_day_gl_cap = (
        (profile or {}).get("_user_per_day_gl_cap_override")
        or (profile or {}).get("_per_day_gl_cap_override", per_day_gl_cap)
    )
    if effective_per_day_gl_cap is not None:
        pday = float(effective_per_day_gl_cap)
        for d in days:
            model += lpSum(float(candidates.loc[i, "GL"]) * x[(d, int(i))] for i in candidates.index) <= float(pday)

    # Per-meal minimum GL — normally Breakfast/Dinner only, floor 15; weeks 1
    # can raise the floor and extend it to Lunch too via profile overrides.
    # _meal_gl_floor_by_slot allows a per-slot floor (e.g. keeping week 2's
    # Dinner floor high enough that it doesn't dip below week 3's typical
    # value), independent of the flat _meal_gl_floor_override fallback.
    meal_gl_floor = float((profile or {}).get("_meal_gl_floor_override", 15.0))
    meal_gl_floor_by_slot = (profile or {}).get("_meal_gl_floor_by_slot") or {}
    include_lunch_gl_floor = bool((profile or {}).get("_meal_gl_floor_include_lunch"))

    bf_ids = [i for i in candidates.index if str(candidates.loc[i, "Meal_Time"]).strip().lower() == "breakfast"]
    if bf_ids:
        bf_floor = float(meal_gl_floor_by_slot.get("Breakfast", meal_gl_floor))
        for d in days:
            model += lpSum(float(candidates.loc[i, "GL"]) * x[(d, int(i))] for i in bf_ids) >= bf_floor

    d_ids = [i for i in candidates.index if str(candidates.loc[i, "Meal_Time"]).strip().lower() == "dinner"]
    if d_ids:
        dn_floor = float(meal_gl_floor_by_slot.get("Dinner", meal_gl_floor))
        for d in days:
            model += lpSum(float(candidates.loc[i, "GL"]) * x[(d, int(i))] for i in d_ids) >= dn_floor

    ln_ids = [i for i in candidates.index if str(candidates.loc[i, "Meal_Time"]).strip().lower() == "lunch"]
    if include_lunch_gl_floor and ln_ids:
        for d in days:
            model += lpSum(float(candidates.loc[i, "GL"]) * x[(d, int(i))] for i in ln_ids) >= meal_gl_floor

    # Snacks maximum GL: each day's snacks must not exceed 20 GL units
    s_ids = [i for i in candidates.index if str(candidates.loc[i, "Meal_Time"]).strip().lower() == "snacks"]
    if s_ids:
        for d in days:
            model += lpSum(float(candidates.loc[i, "GL"]) * x[(d, int(i))] for i in s_ids) <= 20.0

    # Meal-to-meal energy balance: without this, a day's total energy can
    # concentrate heavily in one meal (e.g. Lunch far outweighing Breakfast)
    # even when the day's aggregate energy target is met — part of why
    # per-meal-slot averages don't taper cleanly week over week even though
    # day-level totals do. Bounds are a % of that day's own realized total
    # (not a fixed kcal number), so they scale correctly across users/weeks
    # without per-week tuning. With snacks: each of Breakfast/Lunch/Dinner
    # gets 18-38%, Snacks gets 4-17%. Without snacks: each of the three
    # mains gets 22-42%. Soft (penalized slack), not hard — a hard version
    # of this made even the plain baseline case infeasible (timed out at
    # 600s with no usable menu) once stacked on top of the GL caps/floors
    # and every other existing constraint. Bands/penalty weight (35) tuned
    # as a middle ground between an earlier tight version (50 weight, 20-35%/
    # 25-40% bands) that reliably balanced meals but took 600s+, and a looser
    # one (20 weight, 15-40%/20-45% bands) that solved in ~110s but allowed
    # large violations (up to 55%) — the solver is
    # nudged toward balance but can still produce a valid plan quickly.
    meal_balance_penalty_terms = []
    if "Energy_ENERC_Kcal" in candidates.columns:
        has_snacks_slot = bool(s_ids) or any(
            str(mt).strip().lower() == "snacks" for mt in required_slots["Meal_Time"].unique()
        )
        if has_snacks_slot:
            main_lo, main_hi = 0.18, 0.38
        else:
            main_lo, main_hi = 0.22, 0.42
        meal_balance_penalty_weight = 35.0

        for d in days:
            daily_total_kcal = lpSum(
                float(candidates.loc[i, "Energy_ENERC_Kcal"]) * x[(d, int(i))] for i in candidates.index
            )
            for slot_name, meal_ids in (("Breakfast", bf_ids), ("Lunch", ln_ids), ("Dinner", d_ids)):
                if not meal_ids:
                    continue
                meal_kcal = lpSum(float(candidates.loc[i, "Energy_ENERC_Kcal"]) * x[(d, int(i))] for i in meal_ids)
                safe_slot = slot_name.replace(" ", "_")
                under = LpVariable(f"meal_balance_under_{safe_slot}_{d}", lowBound=0)
                over = LpVariable(f"meal_balance_over_{safe_slot}_{d}", lowBound=0)
                model += meal_kcal + under >= main_lo * daily_total_kcal
                model += meal_kcal - over <= main_hi * daily_total_kcal
                meal_balance_penalty_terms.append(meal_balance_penalty_weight * (under + over))

            if has_snacks_slot and s_ids:
                snack_kcal = lpSum(float(candidates.loc[i, "Energy_ENERC_Kcal"]) * x[(d, int(i))] for i in s_ids)
                sn_under = LpVariable(f"meal_balance_under_Snacks_{d}", lowBound=0)
                sn_over = LpVariable(f"meal_balance_over_Snacks_{d}", lowBound=0)
                model += snack_kcal + sn_under >= 0.04 * daily_total_kcal
                model += snack_kcal - sn_over <= 0.17 * daily_total_kcal
                meal_balance_penalty_terms.append(meal_balance_penalty_weight * (sn_under + sn_over))



    # =================================================================
    # OPTIMIZED SOFT PENALTY + MULTI-LAYER DYNAMIC VARIETY CONTROLS
    # =================================================================
    recipe_penalty_weight = 2000.0
    category_penalty_weight = 1000.0
    variety_penalties = []

    # Pre-calculate unique recipe availability per slot for the dynamic guardrails
    slot_recipe_counts = candidates.groupby(["Meal_Time", "Dish_Type"])["Recipe_Code"].nunique().to_dict()

    # Per-user override: profile["_boiled_egg_daily_hard"] (A002-specific) —
    # exempts "Boiled egg" recipe codes from every repetition ceiling below
    # (per-slot hard cap, per-slot soft penalty, global per-recipe cap) and
    # hard-mandates at least one boiled-egg selection every day. Scoped to
    # this recipe name only so no other user or recipe is affected.
    boiled_egg_daily_hard = bool((profile or {}).get("_boiled_egg_daily_hard"))
    boiled_egg_ids: set = set()
    if boiled_egg_daily_hard and "Recipe_Name" in candidates.columns:
        boiled_egg_ids = set(
            int(i) for i in candidates.index
            if str(candidates.loc[i, "Recipe_Name"]).strip().lower() == "boiled egg"
        )

    # 1) Recipe Repetition: Combined Soft Penalty + Dynamic Hard Ceiling
    for (meal_time, dish_type, recipe_code), group_df in candidates.groupby(["Meal_Time", "Dish_Type", "Recipe_Code"], dropna=False):
        ids = [int(i) for i in group_df.index.tolist()]
        if not ids:
            continue
        if boiled_egg_ids and set(ids) <= boiled_egg_ids:
            continue  # boiled egg exempted from repetition ceilings for this user

        # --- LAYER A: Dynamic Hard Guardrail ---
        # Look up how many unique recipes are competing for this specific slot
        unique_recipes = slot_recipe_counts.get((meal_time, dish_type), 1)
        if unique_recipes <= 2:
            max_recipe_rep = 3  # Scarce choices: allow repeating up to 3 times if forced by macros
        elif unique_recipes <= 5:
            max_recipe_rep = 2  # Medium variety: allow up to 2 times absolute maximum
        else:
            max_recipe_rep = 1  # Abundant choices: force high variety (strict cap of 1 time)

        # Apply the absolute upper ceiling
        model += lpSum(y[(d, i)] for d in days for i in ids) <= max_recipe_rep

        # --- LAYER B: Soft Repetition Penalty ---
        # Only create penalty variables if the recipe has enough data entries to actually repeat
        if len(ids) > 1:
            safe_mt = str(meal_time).replace(" ", "_").replace("-", "_")
            safe_dt = str(dish_type).replace(" ", "_").replace("-", "_")
            safe_rc = str(recipe_code).replace(" ", "_").replace("-", "_")
            
            v_recipe = LpVariable(f"recipe_excess_{safe_mt}_{safe_dt}_{safe_rc}", lowBound=0)
            # First appearance is free, subsequent appearances add to v_recipe penalty
            model += lpSum(y[(d, i)] for d in days for i in ids) <= 1 + v_recipe
            variety_penalties.append(recipe_penalty_weight * v_recipe)


    # Global per-recipe hard cap — scales with Main subcategory pool size (Snacks excluded)
    main_df = candidates[candidates["Dish_Type"].astype(str).str.strip() == "Main"].copy()
    main_subcats = main_df["Preferred_SubCategory_code"].dropna().nunique()
    global_recipe_cap = 2 if main_subcats <= 5 else 1
    for recipe_code, recipe_df in candidates.groupby("Recipe_Code", dropna=False):
        non_snack_ids = [int(i) for i in recipe_df.index.tolist()
                         if str(candidates.loc[i, "Dish_Type"]).strip().lower() != "snacks"]
        if boiled_egg_ids and set(non_snack_ids) <= boiled_egg_ids:
            continue  # boiled egg exempted from the global cap for this user
        if non_snack_ids:
            model += lpSum(y[(d, i)] for d in days for i in non_snack_ids) <= global_recipe_cap

    # When pool is small (≤5 subcategories), ensure any selected subcategory appears at most 14 times
    if main_subcats <= 5 and main_subcats > 1:
        for subcat, subcat_df in main_df.groupby("Preferred_SubCategory_code", dropna=False):
            subcat_ids = [int(i) for i in subcat_df.index.tolist()]
            if subcat_ids:
                model += lpSum(y[(d, i)] for d in days for i in subcat_ids) <= 14

    # Snacks must appear every day when snack candidates exist
    snack_candidate_ids = [i for i in candidates.index
                           if str(candidates.loc[i, "Dish_Type"]).strip().lower() == "snacks"]
    if snack_candidate_ids:
        for d in days:
            model += lpSum(y[(d, int(i))] for i in snack_candidate_ids) >= 1

    # 2) Category Repetition: Fast Soft Penalty
    category_df = candidates.dropna(subset=["Category_Key"]).copy()
    for (dish_type, category_key), group_df in category_df.groupby(["Dish_Type", "Category_Key"], dropna=False):
        dish_type_u = str(dish_type).strip().upper()
        if dish_type_u not in ("MAIN", "MAIN 2", "MAIN 3"):
            continue
            
        ids = [int(i) for i in group_df.index.tolist()]
        if len(ids) > 2: 
            safe_dt = str(dish_type).replace(" ", "_").replace("-", "_")
            safe_ck = str(category_key).replace(" ", "_").replace("-", "_").replace("/", "_")
            
            v_category = LpVariable(f"category_excess_{safe_dt}_{safe_ck}", lowBound=0)
            model += lpSum(y[(d, i)] for d in days for i in ids) <= 2 + v_category
            variety_penalties.append(category_penalty_weight * v_category)


    # 3) Intra-Meal Variety: Hard Subcategory Constraint (No duplicate types in a single slot)
    if "Preferred_SubCategory_code" in candidates.columns:
        subcat_df = candidates.dropna(subset=["Preferred_SubCategory_code"]).copy()
        subcat_df["Preferred_SubCategory_code"] = subcat_df["Preferred_SubCategory_code"].astype(str).str.strip()
        subcat_df = subcat_df[subcat_df["Preferred_SubCategory_code"] != ""]

        for d in days:
            for (meal_time, subcat_code), group_df in subcat_df.groupby(["Meal_Time", "Preferred_SubCategory_code"]):
                ids = [int(i) for i in group_df.index.tolist()]
                # If multiple items in this subcategory exist, ensure only 1 can be chosen on day 'd' at this 'meal_time'
                if len(ids) > 1:
                    model += lpSum(y[(d, i)] for i in ids) <= 1 




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

    # ==========================================
    # # DYNAMIC RECIPE REPETITION CONSTRAINT
    # # ==========================================
    # # Group by structural slot to see how many unique recipes are competing for it
    # for (meal_time, dish_type), slot_group in candidates.groupby(["Meal_Time", "Dish_Type"]):
    #     unique_recipes = slot_group["Recipe_Code"].nunique()
        
    #     # Dynamically calculate the safe maximum repetition cap based on total unique choices:
    #     if unique_recipes <= 2:
    #         max_recipe_rep = 7  # Critically low choices: allow it every single day if forced
    #     elif unique_recipes <= 5:
    #         max_recipe_rep = 3  # Low variety: allow a single recipe up to 3 times a week
    #     else:
    #         max_recipe_rep = 2  # Healthy variety pool: cap a single recipe at max 2 times a week

    #     # Apply the dynamically calculated cap to each unique recipe inside this slot
    #     for recipe_code, sub_group in slot_group.groupby("Recipe_Code"):
    #         ids = [int(i) for i in sub_group.index.tolist()]
    #         model += lpSum(y[(d, i)] for d in days for i in ids) <= max_recipe_rep



    # Step 3: Track Nutrient Penalties
    # Energy is handled separately as a per-day hard constraint — exclude it here
    weekly_min.pop("Energy_ENERC_Kcal", None)

    # Carb floor: soft weekly target instead of a hard per-day 130g minimum.
    # A fixed 130g/day floor combined with the hard 45-50% carb-of-energy band
    # below is only satisfiable when eff_daily >= ~945 kcal (130g*4kcal / 0.50);
    # BMI/age scaling (up to eff_daily*0.63) routinely pushes overweight/older
    # profiles under that, making the LP provably infeasible on these three
    # constraints alone. Capping the target at 45%*eff_daily/4 keeps it
    # consistent with the band's own lower bound, so it never asks for more
    # than the band already permits, and shortfalls are penalized, not fatal.
    daily_carb_floor = 130.0
    if eff_daily is not None:
        daily_carb_floor = min(130.0, 0.45 * float(eff_daily) / 4.0)
    weekly_min["Carbohydrate_g"] = daily_carb_floor * float(n_days)

    # Protein is no longer floored from the EAR table at all — it's now
    # regulated directly by body-weight bounds instead (1.0-1.4g/kg/day),
    # replacing both the EAR-based floor and the old Protein/Energy ratio
    # band (10-20% of energy, removed above). Popped before the generic
    # weekly_min soft-penalty loop below so it never re-enters as an EAR
    # floor; the g/kg bounds are applied as their own hard constraint further
    # down (candidates["Prot_g"]/PROTEIN_G_PER_KG_MIN/MAX).
    weekly_min.pop("Protein_PROTCNT_g", None)

    nutrient_slacks = {}
    penalty_terms = []
    penalty_weight = 100.0

    # Fiber: three-tier bound, for all users — popped out of the generic
    # weekly_min soft-penalty loop below, same treatment as protein above.
    #   - Hard floor at EAR*1.3 (mandated, no slack) — this is the level that
    #     stays feasible even under week1's taper bounds (EAR*1.5 as a hard
    #     floor was found to conflict with A004's week1 taper, forcing an
    #     unwanted retry-to-defaults that silently cancelled the taper).
    #   - Hard ceiling at EAR*1.7 (mandated, no slack) — prevents fiber
    #     climbing arbitrarily high once it's no longer the binding floor.
    #   - Soft target at EAR*1.5 (penalized shortfall, not hard) — still
    #     pushes the solver toward the higher fiber level whenever the rest
    #     of the model has room for it, without making 1.5x a hard
    #     requirement that can conflict with taper bounds.
    # This is separate from (and in addition to) the existing per-day
    # 14g/1000kcal and gender-based (25g women / 30g men) fiber floors.
    fiber_ear_weekly = weekly_min.pop("TotalDietaryFibre_FIBTG_g", None)
    if fiber_ear_weekly and "TotalDietaryFibre_FIBTG_g" in candidates.columns:
        fiber_hard_min_g = float(fiber_ear_weekly) * 1.3
        fiber_hard_max_g = float(fiber_ear_weekly) * 1.7
        fiber_soft_target_g = float(fiber_ear_weekly) * 1.5
        weekly_fiber = lpSum(
            float(candidates.loc[i, "TotalDietaryFibre_FIBTG_g"]) * x[(d, int(i))]
            for d in days for i in candidates.index
        )
        model += weekly_fiber >= fiber_hard_min_g
        model += weekly_fiber <= fiber_hard_max_g
        fiber_shortfall = LpVariable("fiber_shortfall_below_1_5x_ear", lowBound=0)
        model += weekly_fiber + fiber_shortfall >= fiber_soft_target_g
        penalty_terms.append(penalty_weight * fiber_shortfall)

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

    # Millet-recipe soft-forced inclusion: require at least 1 (or 2, if more
    # than 4 millet candidate slots exist) millet selections across the week,
    # absorbed by a heavily-penalized slack if that's genuinely infeasible
    # alongside every other hard constraint — so the plan still solves, just
    # without a millet recipe, rather than failing to generate at all.
    # Separate from liked_recipe_bonus (an objective discount that applies to
    # every liked recipe, millets included) — this stronger requirement is
    # millet-only, driven by ds["millet_recipe_codes"] (services/data_loader.py).
    millet_penalty_terms = []
    millet_codes = {str(c).strip().upper() for c in (ds.get("millet_recipe_codes") or set())}
    if millet_codes:
        millet_ids = [
            int(i) for i in candidates.index
            if str(candidates.loc[i, "Recipe_Code"]).strip().upper() in millet_codes
        ]
        if millet_ids:
            required_millet_count = min(5, len(millet_ids))
            millet_shortfall = LpVariable("millet_inclusion_shortfall", lowBound=0)
            model += (
                lpSum(y[(d, i)] for d in days for i in millet_ids) + millet_shortfall
                >= required_millet_count
            )
            millet_penalty_weight = 1_000_000.0
            millet_penalty_terms.append(millet_penalty_weight * millet_shortfall)

    # Non-veg-days soft-forced inclusion: the user selected specific weekdays
    # they're OK having non-veg on (profile["non_veg_days"], resolved to Day
    # 1-7 numbers in routers/plan.py._run_plan_background — the only place
    # that knows the plan's actual calendar dates before this runs). Requires
    # at least half of those eligible days to include >=1 non-veg recipe, not
    # every one of them (an eligible day is still fine to end up vegetarian) —
    # absorbed by a heavily-penalized slack, same pattern as the millet
    # requirement above, so this never makes the whole week infeasible.
    # "Non-veg" here means true meat/fish/poultry — egg (Ovo-vegetarian=1) is
    # excluded from nonveg_ids on purpose. Egg recipes have Vegetarian=0, so
    # without this exclusion they satisfy both the non-veg-day requirement
    # below AND slip through the vegetarian-only-day exclusion further down —
    # in practice the GL-minimizing objective leans on egg (near-zero GI) so
    # heavily that non-veg-eligible days ended up filled almost entirely with
    # egg instead of actual non-veg, while veg-only days couldn't include egg
    # at all. Treating egg as its own thing (allowed every day, doesn't count
    # toward the non-veg quota) fixes both.
    ovo_col = candidates["Ovo-vegetarian"] if "Ovo-vegetarian" in candidates.columns else pd.Series(0, index=candidates.index)
    is_egg = pd.to_numeric(ovo_col, errors="coerce") == 1

    # Non-veg-day-count mandate: hard, no penalty, for every non-veg-diet
    # user (nonveg_eligible_days/nonveg_required_count are only populated in
    # routers/plan.py when profile["diet_type"] == "non-veg"). More than half
    # of the user's preferred non-veg days must carry real non-veg — this
    # used to fall back to a heavily-penalized slack if infeasible; now it's
    # mandatory. Per-user override: profile["_nonveg_main2_only_hard"]
    # (A002-specific) further restricts which dish types count toward the
    # day, to Main/Main2 only instead of any non-veg dish type.
    nonveg_main2_only_hard = bool((profile or {}).get("_nonveg_main2_only_hard"))

    nonveg_eligible_days = [d for d in ((profile or {}).get("_nonveg_eligible_days") or []) if d in days]
    nonveg_required_count = int((profile or {}).get("_nonveg_required_count") or 0)
    if nonveg_eligible_days and nonveg_required_count > 0 and "Vegetarian" in candidates.columns:
        nonveg_ids = [
            int(i) for i in candidates.index
            if pd.to_numeric(candidates.loc[i, "Vegetarian"], errors="coerce") != 1
            and not is_egg.loc[i]
        ]
        # nonveg_ids above still drives the vegetarian-only-day exclusion
        # below (that side stays scoped to ALL non-veg dish types, not just
        # Main/Main2 — a Main3/Snack non-veg item should never leak onto a
        # veg-only day either). Only the day-count *requirement* narrows.
        nonveg_count_ids = nonveg_ids
        if nonveg_main2_only_hard and "Dish_Type" in candidates.columns:
            nonveg_count_ids = [
                i for i in nonveg_ids
                if str(candidates.loc[i, "Dish_Type"]).strip() in ("Main", "Main 2")
            ]
        if nonveg_ids:
            day_ok = {}
            for d in nonveg_eligible_days:
                day_ok[d] = LpVariable(f"nonveg_day_ok_{d}", lowBound=0, upBound=1, cat="Binary")
                # day_ok[d] can only be 1 if at least one qualifying non-veg
                # recipe was actually selected that day; the aggregate
                # constraint below is what gives the solver a reason to turn
                # it on.
                model += day_ok[d] <= lpSum(y[(d, i)] for i in nonveg_count_ids)
            model += lpSum(day_ok[d] for d in nonveg_eligible_days) >= nonveg_required_count

            # non_veg_days means true non-veg (meat/fish/poultry) is ONLY
            # allowed on those days — every other day is vegetarian-or-egg,
            # not strictly vegetarian (egg isn't in nonveg_ids, so it's never
            # excluded here). Hard (not penalized): a vegetarian-or-egg day is
            # always feasible on its own (the model already runs fine
            # end-to-end for fully-vegetarian users across all 7 days), so
            # this can't introduce infeasibility.
            for d in days:
                if d not in nonveg_eligible_days:
                    model += lpSum(y[(d, i)] for i in nonveg_ids) == 0

    # Non-veg-type variety: when the user selected more than one non-veg type
    # (profile["non_veg_types"], e.g. ["Chicken","Fish","Egg"]), softly
    # discourage any single type from dominating the week's non-veg
    # selections. Without this, GL-minimization alone tends to always pick
    # whichever type happens to have the lowest (sometimes exactly 0) GI in
    # the reference data — e.g. every "Egg and omlettes" recipe currently has
    # GI_Avg=0 — regardless of what the user actually selected.
    # Free allowance: any one type can be at most half of the week's total
    # non-veg selections; going over that is absorbed by a penalized slack
    # per type (same pattern as everywhere else here), so a pool dominated
    # by one type can never make the week infeasible.
    nonveg_type_penalty_terms = []
    selected_types = {
        str(t).strip().lower() for t in ((profile or {}).get("non_veg_types") or []) if str(t).strip()
    }
    nonveg_type_map = ds.get("nonveg_type_map") or {}
    if len(selected_types) > 1 and nonveg_type_map and "Vegetarian" in candidates.columns:
        all_nonveg_ids = [
            int(i) for i in candidates.index
            if pd.to_numeric(candidates.loc[i, "Vegetarian"], errors="coerce") != 1
        ]
        if all_nonveg_ids:
            total_nonveg_selected = lpSum(y[(d, i)] for d in days for i in all_nonveg_ids)
            type_penalty_weight = 3000.0
            for t in selected_types:
                type_ids = [
                    i for i in all_nonveg_ids
                    if t in nonveg_type_map.get(str(candidates.loc[i, "Recipe_Code"]).strip().upper(), set())
                ]
                if not type_ids:
                    continue
                safe_t = t.replace(" ", "_")
                v_type = LpVariable(f"nonveg_type_excess_{safe_t}", lowBound=0)
                model += (
                    lpSum(y[(d, i)] for d in days for i in type_ids) - 0.5 * total_nonveg_selected
                    <= v_type
                )
                nonveg_type_penalty_terms.append(type_penalty_weight * v_type)

    # Egg-inclusion minimum: hard only for A002 (every day, no penalty, per
    # explicit override). Everyone else who listed "Egg" among their
    # preferred non-veg food types gets the original soft version back: at
    # least 2 days across the whole week (any day — egg is allowed
    # everywhere, not just non-veg-eligible days) should include >=1 egg
    # recipe, absorbed by a heavily-penalized shortfall slack rather than a
    # hard requirement — this was one of 4 mandates found (via isolation
    # testing) to jointly make A001 week1/2's taper genuinely Infeasible, and
    # disabling any one of the 4 alone was enough to restore feasibility.
    # Per-user override: profile["_egg_every_day_hard"] (A002-specific)
    # raises the requirement to every single day, hard.
    egg_every_day_hard = bool((profile or {}).get("_egg_every_day_hard"))

    egg_penalty_terms = []
    if "egg" in selected_types and is_egg.any():
        egg_ids = [int(i) for i in candidates.index if is_egg.loc[i]]
        if egg_ids:
            if egg_every_day_hard:
                for d in days:
                    model += lpSum(y[(d, i)] for i in egg_ids) >= 1
            else:
                egg_day_ok = {}
                for d in days:
                    egg_day_ok[d] = LpVariable(f"egg_day_ok_{d}", lowBound=0, upBound=1, cat="Binary")
                    model += egg_day_ok[d] <= lpSum(y[(d, i)] for i in egg_ids)
                egg_shortfall = LpVariable("egg_days_shortfall", lowBound=0)
                egg_min_days = 2
                model += lpSum(egg_day_ok[d] for d in days) + egg_shortfall >= egg_min_days
                egg_penalty_weight = 1_000_000.0
                egg_penalty_terms.append(egg_penalty_weight * egg_shortfall)

    # Boiled-egg-every-day mandate (A002-specific, see boiled_egg_ids above):
    # stricter than the general egg mandate — requires the "Boiled egg"
    # recipe specifically, not just any egg dish, on every single day.
    if boiled_egg_daily_hard and boiled_egg_ids:
        for d in days:
            model += lpSum(y[(d, i)] for i in boiled_egg_ids) >= 1

    # Step 4: Safely combine ALL penalties using += to avoid erasing the GL objective
    if variety_penalties:
        model.objective += lpSum(variety_penalties)
    if penalty_terms:
        model.objective += lpSum(penalty_terms)
    if millet_penalty_terms:
        model.objective += lpSum(millet_penalty_terms)
    if nonveg_type_penalty_terms:
        model.objective += lpSum(nonveg_type_penalty_terms)
    if egg_penalty_terms:
        model.objective += lpSum(egg_penalty_terms)
    if meal_balance_penalty_terms:
        model.objective += lpSum(meal_balance_penalty_terms)



    # Energy: per-day constraint, normally ±10% around eff_daily. Weeks 1-2
    # override this via profile to a wider, asymmetric band (80%-130% for
    # week 1, 80%-120% for week 2) instead of the tight symmetric ±10%, so
    # the mandated bigger portions above have room to land without being
    # squeezed back down.
    energy_band_override = (profile or {}).get("_energy_band_override")
    band_lo, band_hi = energy_band_override if energy_band_override else (0.9, 1.1)
    if eff_daily is not None and "Energy_ENERC_Kcal" in candidates.columns:
        for d in days:
            daily_kcal = lpSum(float(candidates.loc[i, "Energy_ENERC_Kcal"]) * x[(d, int(i))] for i in candidates.index)
            model += daily_kcal >= float(eff_daily) * band_lo
            model += daily_kcal <= float(eff_daily) * band_hi

    candidates["Carb_g"] = pd.to_numeric(candidates.get("Carbohydrate_g", 0), errors="coerce").fillna(0.0)
    candidates["Fat_g"] = pd.to_numeric(candidates.get("TotalFat_FATCE_g", 0), errors="coerce").fillna(0.0)
    candidates["Energy_kcal"] = pd.to_numeric(candidates.get("Energy_ENERC_Kcal", 0), errors="coerce").fillna(0.0)
    for d in days:
        model += lpSum((4.0 * candidates.loc[i, "Carb_g"] - 0.40 * candidates.loc[i, "Energy_kcal"]) * x[(d, int(i))] for i in candidates.index) >= 0.0
        model += lpSum((4.0 * candidates.loc[i, "Carb_g"] - 0.50 * candidates.loc[i, "Energy_kcal"]) * x[(d, int(i))] for i in candidates.index) <= 0.0

        # Protein/Energy ratio band (10-20% of energy from protein) removed —
        # protein is now regulated directly by body-weight bounds (below)
        # instead of an energy-ratio band. The ratio itself is still worth
        # reporting in summaries (see Functions_Base.py), just no longer
        # enforced as a solver constraint.

        model += lpSum((9.0 * candidates.loc[i, "Fat_g"] - 0.25 * candidates.loc[i, "Energy_kcal"]) * x[(d, int(i))] for i in candidates.index) >= 0.0
        model += lpSum((9.0 * candidates.loc[i, "Fat_g"] - 0.35 * candidates.loc[i, "Energy_kcal"]) * x[(d, int(i))] for i in candidates.index) <= 0.0

    # Protein: hard weekly bounds directly on body weight (1.0-1.4g/kg/day)
    # instead of the EAR table or a Protein/Energy ratio band (both removed
    # above). Replaces the EAR-based floor entirely — protein is no longer
    # taken from BaseEar at all. Per-user override: profile["_protein_g_per_kg_min"]
    # / profile["_protein_g_per_kg_max"] (A002-specific: 1.3-1.7 instead of
    # the 1.0-1.4 default).
    PROTEIN_G_PER_KG_MIN = float((profile or {}).get("_protein_g_per_kg_min", 1.0))
    PROTEIN_G_PER_KG_MAX = float((profile or {}).get("_protein_g_per_kg_max", 1.4))
    if "Protein_PROTCNT_g" in candidates.columns and profile and profile.get("weight"):
        candidates["Prot_g"] = pd.to_numeric(candidates.get("Protein_PROTCNT_g", 0), errors="coerce").fillna(0.0)
        _weight_kg = float(profile["weight"])
        protein_weekly_min_g = PROTEIN_G_PER_KG_MIN * _weight_kg * float(n_days)
        protein_weekly_max_g = PROTEIN_G_PER_KG_MAX * _weight_kg * float(n_days)
        weekly_protein = lpSum(candidates.loc[i, "Prot_g"] * x[(d, int(i))] for d in days for i in candidates.index)
        model += weekly_protein >= protein_weekly_min_g
        model += weekly_protein <= protein_weekly_max_g

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

    # weekly_max[col] is a weekly total (TUL-per-day * n_days, see
    # Functions_Base._get_weekly_requirement_maps) — divide back down and
    # enforce per day, not as a weekly sum. A weekly-aggregate cap lets one
    # day spike well over the tolerable upper limit as long as other days
    # compensate, which defeats the point of a per-day safety ceiling. The
    # 1.2x slack (unchanged, still undocumented in origin) is kept as-is.
    for col, max_req in weekly_max.items():
        if col not in candidates.columns or max_req <= 0:
            continue
        per_day_max = float(max_req) / float(n_days)
        for d in days:
            model += lpSum(float(candidates.loc[i, col]) * x[(d, int(i))] for i in candidates.index) <= per_day_max * 1.2

    if 'Sugar_per_serving_g' in candidates.columns and 'Energy_ENERC_Kcal' in candidates.columns:
        for d in days:
            sugar_energy = lpSum(4.0 * float(candidates.loc[i, 'Sugar_per_serving_g']) * x[(d, int(i))] for i in candidates.index)
            daily_energy = lpSum(float(candidates.loc[i, 'Energy_ENERC_Kcal']) * x[(d, int(i))] for i in candidates.index)
            model += sugar_energy <= 0.05 * daily_energy

    # Sodium/salt were previously summed across all 7 days and compared
    # against limit*n_days — a weekly-aggregate cap, despite the "_per_day"
    # naming, that let a single day spike well above the intended daily
    # limit as long as other days compensated. Fixed to match cholesterol's
    # already-correct per-day enforcement below.
    #
    # Sodium specifically is kept as a SOFT per-day cap (penalized slack,
    # same pattern as the nutrient-floor penalties above) rather than hard:
    # isolation testing on A002 showed the hard 1500mg/day cap, stacked with
    # tightened taper bounds, was the dominant cause of slow/infeasible
    # solves — removing it alone brought a stuck 200s+ solve back down to
    # ~66s. 1500mg is a dietary target, not a hard medical limit for most
    # users, so a heavily-penalized overage is preferable to failing to
    # generate a plan at all.
    sodium_limit_per_day_mg = 1500.0
    sodium_penalty_weight = 5000.0
    sodium_penalty_terms = []
    if 'Sodium_mg' in candidates.columns:
        for d in days:
            sodium_slack = LpVariable(f"sodium_over_day_{d}", lowBound=0)
            model += lpSum(float(candidates.loc[i, 'Sodium_mg']) * x[(d, int(i))] for i in candidates.index) <= float(sodium_limit_per_day_mg) + sodium_slack
            sodium_penalty_terms.append(sodium_penalty_weight * sodium_slack)
    if sodium_penalty_terms:
        model.objective += lpSum(sodium_penalty_terms)

    # Cholesterol and salt, like sodium above, are kept as SOFT per-day caps
    # (penalized slack) rather than hard: isolation testing on A002 week3
    # showed TUL+cholesterol+salt together leave only a razor-thin feasible
    # region for some users (proven Infeasible in one run, then feasible on
    # an identical retry — a knife-edge case sensitive to minor candidate-pool
    # variation), with no single constraint uniquely responsible. Softening
    # cholesterol/salt adds slack to that margin so the plan still generates
    # reliably. TUL is left hard — it wasn't included in this softening.
    cholesterol_limit_per_day_mg = 300.0
    cholesterol_penalty_weight = 5000.0
    cholesterol_penalty_terms = []
    if 'Cholesterol_mg' in candidates.columns:
        for d in days:
            cholesterol_slack = LpVariable(f"cholesterol_over_day_{d}", lowBound=0)
            model += lpSum(float(candidates.loc[i, 'Cholesterol_mg']) * x[(d, int(i))] for i in candidates.index) <= float(cholesterol_limit_per_day_mg) + cholesterol_slack
            cholesterol_penalty_terms.append(cholesterol_penalty_weight * cholesterol_slack)
    if cholesterol_penalty_terms:
        model.objective += lpSum(cholesterol_penalty_terms)

    # Salt is measured in grams (cap=5g/day) vs sodium/cholesterol's
    # milligrams (cap=1500/300mg/day) — using the same 5000 weight here would
    # barely penalize salt overage (a 1g overage costing only 5000, vs. a
    # 1mg sodium overage costing the same). Scaled up by the cap ratio
    # (1500mg/5g = 300x) so a given fraction of overage is penalized
    # comparably to sodium's.
    salt_limit_per_day_g = 5
    salt_penalty_weight = 5000.0 * 300.0
    salt_penalty_terms = []
    if 'Salt_per_serving_g' in candidates.columns:
        for d in days:
            salt_slack = LpVariable(f"salt_over_day_{d}", lowBound=0)
            model += lpSum(float(candidates.loc[i, 'Salt_per_serving_g']) * x[(d, int(i))] for i in candidates.index) <= float(salt_limit_per_day_g) + salt_slack
            salt_penalty_terms.append(salt_penalty_weight * salt_slack)
    if salt_penalty_terms:
        model.objective += lpSum(salt_penalty_terms)

    # gapRel widens on each successive taper-relaxation retry (see
    # routers/plan.py's graduated fallback), since a retry has already
    # accepted a degraded taper in exchange for a usable result — letting
    # CBC accept a looser (still feasible) solution there trades a small
    # amount of solution quality for a real reduction in wall-clock time on
    # exactly the hardest, already-failing-once cases, without touching the
    # primary/first-attempt solve's quality at all.
    gap_rel = float((profile or {}).get("_solver_gap_rel_override", 0.3))
    solver = PULP_CBC_CMD(timeLimit=int(time_limit_sec), gapRel=gap_rel, threads=6)
    t_lp = time.time()
    _ = model.solve(solver)
    status = str(LpStatus.get(model.status, model.status))
    logger.info("LP solver finished: status=%s [%.1fs]", status, time.time() - t_lp)

    # A "Not Solved" status (time limit hit) can still carry a real, fully
    # constraint-satisfying incumbent that CBC found before running out of
    # time — use it instead of discarding all solver work. "Infeasible" is
    # excluded even when values are present: those are leftover/relaxation
    # values, not a confirmed feasible integer solution, so they aren't safe
    # to trust.
    usable_status = status in ("Optimal", "Not Solved")
    has_incumbent = usable_status and any(
        y[(d, int(i))].value() is not None for d in days for i in candidates.index
    )

    selected_rows: List[Dict[str, object]] = []
    if has_incumbent:
        for d in days:
            for i in candidates.index:
                if float(y[(d, int(i))].value() or 0) > 0.5:
                    row = candidates.loc[i].to_dict()
                    row.pop("__candidate_id__", None)
                    row["Day"] = d
                    row["Serving"] = float(x[(d, int(i))].value() or 0)
                    selected_rows.append(row)

    _write_debug_csv(candidates, "candidates_with_metrics.csv")
    if os.getenv("DEBUG_OPTIMIZER") == "1":
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
        _write_debug_csv(pd.DataFrame(vars_rows), "final_y_x_values_postsolve.csv")

    # No naive fallback menu on a failed/unusable solve — a "first available
    # candidate at Serving=1.0" menu ignores GL, nutrition, variety, and
    # non-veg placement entirely, and looks like a real plan to any caller
    # that doesn't check `status`. Callers must treat an empty weekly_menu
    # (paired with a non-"Optimal" status and this `message`) as a failed
    # solve, not a usable-but-suboptimal one.
    weekly_menu = pd.DataFrame(selected_rows)
    if not weekly_menu.empty:
        weekly_menu = weekly_menu.sort_values(["Day", "Meal_Time", "Dish_Type"]).reset_index(drop=True)
        message = None
    else:
        message = (
            f"No feasible weekly menu found (solver status: {status}). "
            "Returning an empty menu instead of a naive placeholder."
        )

    summary = {
        "status": status,
        "message": message,
        "objective": float(value(model.objective)) if model.objective is not None else np.nan,
        "objective_metric": objective_metric_col,
        "objective_formula": "0.5*z(GL) + 0.3*z(Avg_TimeAbove160_pct) + 0.2*z(Avg_Delta_Glucose) - liked_recipe_bonus",
        "category_weekly_rep": int(category_weekly_rep) if category_weekly_rep is not None else None,
        "rows": int(len(weekly_menu)),
        "days": int(n_days),
        "required_slots": int(len(required_slots)),
        # Exposed so routers/plan.py's post-rounding quantity correction can
        # re-check the same per-day energy floor this LP already enforced on
        # the continuous Serving values — item-level quantity rounding
        # happens after this function returns and isn't re-validated here.
        "eff_daily": float(eff_daily) if eff_daily is not None else None,
        "energy_band_lo": float(band_lo),
        "energy_band_hi": float(band_hi),
    }
    return weekly_menu, summary, weekly_min_100
