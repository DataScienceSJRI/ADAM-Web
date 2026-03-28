import traceback
import sys
import os
import tempfile
import json
from pathlib import Path
import numpy as np
import pandas as pd
from fastapi import APIRouter, Depends, HTTPException
from core.auth import get_current_user
from models.schemas import GeneratePlanRequest, GeneratePlanResponse, PlanStatusResponse
from services.data_loader import _fetch, load_data_from_supabase
from services.profile_builder import build_profile
from services.recommendation_writer import (
    write_recommendations,
    write_final_summary,
    write_final_nutrient_summary,
    get_plan_status,
)
import logging


logger = logging.getLogger("backend.routers.plan")
from services.lp_optimizer import run_lp

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from Functions_Base import ADAMPersonalizationModel

router = APIRouter(prefix="/plan", tags=["plan"])


def _write_plan_status(onboarding_id: str | None, status: str, plan_id: str | None = None) -> None:
    """Persist plan generation result to BE_Onboarding_Sessions.plan_status."""
    if not onboarding_id:
        return
    try:
        from core.supabase import get_supabase
        payload: dict = {"plan_status": status}
        if plan_id:
            payload["plan_id"] = plan_id
        get_supabase().table("BE_Onboarding_Sessions").update(payload).eq("onboarding_id", onboarding_id).execute()
    except Exception as _e:
        logger.warning("Could not write plan_status for onboarding_id=%s: %s", onboarding_id, _e)


class ModelOptimiser(ADAMPersonalizationModel):
    """
    Subclass that overrides load_data() to fetch from Supabase
    instead of local CSV files. Everything else in Functions_Base is untouched.

    """

    def __init__(self, user_id: str, workspace: str | None = None, onboarding_id: str | None = None):
        super().__init__(workspace=workspace)
        self._user_id = user_id
        self._onboarding_id = onboarding_id

    def load_data(self, profile=None):
        return load_data_from_supabase(self._user_id, profile, onboarding_id=self._onboarding_id)

    def build_preference_map(self, ds, uid=None):
        prefs = super().build_preference_map(ds, uid=uid)
        # Drop sub_category_code to prevent a duplicate column: Functions_Base.run() later
        # merges subcat_df and renames its 'Code' column to 'sub_category_code'. If prefs
        # already carries that column, pandas produces two columns with the same name and
        # row["sub_category_code"] returns a 2-element Series instead of a scalar, breaking
        # all recipe lookups inside score_personalization. The second code path
        # (merge_preferences_with_subcategory) overwrites it safely via assignment.
        if "sub_category_code" in prefs.columns:
            prefs = prefs.drop(columns=["sub_category_code"])
        return prefs

    def optimize_weekly_menu_with_constraints(self, meal_choices, ds, age_group_col, **kwargs):
        kwargs.setdefault("per_recipe_max_gl", None)
        kwargs.setdefault("per_meal_gl_cap", None)
        return run_lp(self, meal_choices, ds, age_group_col, **kwargs)


@router.post("", response_model=GeneratePlanResponse)
def generate_plan(
    body: GeneratePlanRequest = GeneratePlanRequest(),
    user_id: str = Depends(get_current_user),
):
    """Generate a 7-day personalised meal plan for the authenticated user."""
    profile = build_profile(user_id, onboarding_id=body.onboarding_id)

    if profile is None:
        raise HTTPException(
            status_code=404,
            detail=f"No basic details found for user {user_id}. Complete onboarding first.",
        )

    finall_summary = None
    final_nut_summary = None
    opt_summary: dict = {}

    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            model = ModelOptimiser(user_id=user_id, workspace=tmpdir, onboarding_id=body.onboarding_id)
            output_paths = model.run(
                uid=user_id,
                top_n=20,
                ear_group_col=profile["age_group_col"],
                category_weekly_rep=4,
                user_preference="yes",
                profile=profile,
            )

            # weekly_menu and top_personalized_choices are DataFrames in the returned dict.
            # weekly_optimization_summary is a JSON file path — read it while tmpdir exists.
            weekly_menu = output_paths.get("weekly_menu")
            recipe_name_changed = _fetch("USER_Recipes_name_changed")

            # Create mapping (Recipe_Code → New Recipe_Name)
            name_map = dict(zip(recipe_name_changed['Recipe_Code'], recipe_name_changed['Recipe_Name']))
            # Update ONLY matched rows
            weekly_menu.loc[
                weekly_menu['Recipe_Code'].isin(name_map.keys()),
                'Recipe_Name'
            ] = weekly_menu['Recipe_Code'].map(name_map)

            top_choices = output_paths.get("top_personalized_choices")
            weekly_min = output_paths.get("weekly_min")
            summary = output_paths.get("weekly_optimization_summary")
            if summary.get("status") == "Optimal":
                if len(weekly_menu) > 0:
                    finall_summary = Recomendation_formatting(weekly_menu)
                    final_nut_summary = build_weekly_nutrient_summary(weekly_menu, weekly_min)


                os_path = output_paths.get("weekly_optimization_summary")
                opt_summary: dict = {}
                if isinstance(os_path, str) and Path(os_path).exists():
                    with open(os_path) as f:
                        opt_summary = json.load(f)
                elif isinstance(os_path, dict):
                    opt_summary = os_path   
            else:
                _write_plan_status(body.onboarding_id, "No solution please try again")
                return GeneratePlanResponse(
                    status="No solution found please try again with different preferences or check dataset coverage.",
                    rows_written=0,
                    plan_id=None,
                    optimization_status="No solution please try again",
                    message="Model ran but produced no menu. Check preferences and dataset coverage.",
                )
            
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Model error: {str(e)}")

    if weekly_menu is None or weekly_menu.empty:
        _write_plan_status(body.onboarding_id, "Model ran but produced no menu. Check preferences and dataset coverage.")
        return GeneratePlanResponse(
            status="no_output",
            rows_written=0,
            plan_id=None,
            optimization_status=opt_summary.get("status"),
            message="Model ran but produced no menu. Check preferences and dataset coverage.",
        )

    try:
        if top_choices is not None and not top_choices.empty and "Meal_Time" in top_choices.columns:
            present_times = set(weekly_menu["Meal_Time"].astype(str).str.strip().unique())
            all_slots = (
                top_choices[["Meal_Time", "Dish_Type"]]
                .dropna()
                .drop_duplicates()
                .values.tolist()
            )
            days = sorted(weekly_menu["Day"].dropna().unique()) if "Day" in weekly_menu.columns else list(range(1, 8))
            extra_rows = []
            for meal_time, dish_type in all_slots:
                if str(meal_time).strip() not in present_times:
                    slot_cands = top_choices[
                        (top_choices["Meal_Time"].astype(str).str.strip() == str(meal_time).strip()) &
                        (top_choices["Dish_Type"].astype(str).str.strip() == str(dish_type).strip())
                    ]
                    if slot_cands.empty:
                        continue
                    best = slot_cands.iloc[0].to_dict()
                    for d in days:
                        row = dict(best)
                        row["Day"] = d
                        row.setdefault("Serving", 1.0)
                        extra_rows.append(row)
            if extra_rows:
                weekly_menu = pd.concat(
                    [weekly_menu, pd.DataFrame(extra_rows)], ignore_index=True
                ).sort_values(["Day", "Meal_Time", "Dish_Type"]).reset_index(drop=True)
                logger.info("Supplemented weekly_menu with %d rows for missing meal times: %s",
                            len(extra_rows), [m for m, _ in all_slots if str(m).strip() not in present_times])
    except Exception as _supp_err:
        logger.warning("Could not supplement missing meal times: %s", _supp_err)

    try:
        unique_days = sorted(weekly_menu["Day"].dropna().unique().tolist()) if weekly_menu is not None and "Day" in weekly_menu.columns else []
        logger.info("Writing %d rows to recommendations for user_id=%s | unique days: %s", len(weekly_menu) if weekly_menu is not None else 0, user_id, unique_days)
        rows_written, plan_id = write_recommendations(
            user_id=user_id,
            weekly_menu=weekly_menu,
            week_no=body.week_no,
            onboarding_id=body.onboarding_id,
        )
        logger.info("Write completed: rows_written=%d, plan_id=%s, user_id=%s", rows_written, plan_id, user_id)
    except Exception as e:
        logger.exception("Failed to write recommendations for user_id=%s: %s", user_id, e)
        raise HTTPException(status_code=500, detail=f"Failed to write recommendations: {str(e)}")

    try:
        write_final_summary(user_id=user_id, plan_id=plan_id, final_summary_df=finall_summary)
        write_final_nutrient_summary(user_id=user_id, plan_id=plan_id, nutrient_summary_df=final_nut_summary)
    except Exception as e:
        logger.exception("Failed to write summary tables for plan_id=%s: %s", plan_id, e)

    _write_plan_status(body.onboarding_id, f"ok:{opt_summary.get('status', 'unknown')}", plan_id=plan_id)
    return GeneratePlanResponse(
        status="ok",
        rows_written=rows_written,
        plan_id=plan_id,
        onboarding_id=body.onboarding_id,
        optimization_status=opt_summary.get("status"),
        message=None,
    )


@router.get("/status", response_model=PlanStatusResponse)
async def plan_status(user_id: str = Depends(get_current_user)):
    result = get_plan_status(user_id)
    return PlanStatusResponse(**result)


@router.delete("")
async def delete_plan(user_id: str = Depends(get_current_user)):
    from core.supabase import get_supabase
    get_supabase().table("Recommendation").delete().eq("user_id", user_id).execute()
    return {"status": "deleted", "user_id": user_id}


def Recomendation_formatting(weekly_menu_df):
    if not weekly_menu_df.empty:
        tag_df = _fetch("RecipeTagging")
        tag_df = tag_df.rename(
			columns={
				"Recipe code": "Recipe_Code",
				"Recipe Name": "Recipe_Name",
			}
		)
        # Ensure Serving numeric
        weekly_menu_df["Serving"] = pd.to_numeric(weekly_menu_df.get("Serving", 0.0), errors="coerce").fillna(0.0)
        # Select tagging columns if present
        tag_sel_cols = [c for c in ["Recipe_Code", "Portion", "Portion weight (g)", "Description","Subcategories"] if c in tag_df.columns]
        tag_sel = tag_df[tag_sel_cols].copy() if not tag_df.empty else pd.DataFrame()
        merged = weekly_menu_df.merge(tag_sel, left_on="Recipe_Code", right_on="Recipe_Code", how="left")

        # Numeric portion weight
        merged["Portion weight (g)"] = pd.to_numeric(merged.get("Portion weight (g)"), errors="coerce")
        merged["Recipe weight Original (g)"] = merged["Portion weight (g)"]
        merged["Portion original"] = merged.get("Portion")

        merged["Optimal proportion"] = merged.get("Serving", 0.0)
        merged["Recipe weight Optimal (g)"] = (merged["Recipe weight Original (g)"].fillna(0.0) * merged["Optimal proportion"].fillna(0.0)).round(2)

        # Parse numeric portion count from 'Portion' (e.g. '2.0 Number' -> 2.0)
        try:
            merged["Portion_count_original"] = pd.to_numeric(merged.get("Portion", "").astype(str).str.extract(r'([-+]?\d*\.?\d+)')[0], errors="coerce")
        except Exception:
            merged["Portion_count_original"] = pd.Series([pd.NA] * len(merged))
        # Compute numeric Portion optimal = Portion_count_original * Optimal proportion
        _raw_portion_opt = (
            merged["Portion_count_original"].fillna(0.0).astype(float)
            * merged["Optimal proportion"].fillna(0.0).astype(float)
        )
        # Round to nearest 0.25 for user-friendly portions
        merged["Portion optimal"] = (np.round(_raw_portion_opt / 0.25) * 0.25).round(2)
        merged["Description_tagging"] = merged.get("Description")
        merged["OPTIMAL_STATUS"] = merged["Optimal proportion"].apply(lambda v: "selected" if (pd.notna(v) and float(v) > 0) else "not selected")

        out_cols = [
            "Day",
            "Meal_Time",
            "Recipe_Code",
            "Code_cooccurence",
            "Subcategories",
            "Dish_Type",
            "Recipe_Name",
            "Optimal proportion",
            "Recipe weight Original (g)",
            "Portion original",
            "Recipe weight Optimal (g)",
            "Portion optimal",
            "Description_tagging",
            "OPTIMAL_STATUS",
        ]
        final_df = merged.reindex(columns=[c for c in out_cols if c in merged.columns])

        # Merge SubCategory GI averages from Excel (Code, GI_Avg) if available
        try:
            sub_gi = _fetch("SubCategory_foods_GI_GL")
            if len(sub_gi)>0:
                if "Code" in sub_gi.columns and "GI_Avg" in sub_gi.columns:
                    sg = sub_gi[["Code", "GI_Avg"]].copy()
                    sg["Code"] = sg["Code"].astype(str).str.strip().str.upper()
                    final_df["Subcategories_norm"] = final_df.get("Subcategories", "").astype(str).str.strip().str.upper()
                    final_df = final_df.merge(sg, left_on="Subcategories_norm", right_on="Code", how="left")
                    # rename merged Code to Subcategory_Code for clarity
                    if "Code" in final_df.columns:
                        final_df = final_df.rename(columns={"Code": "Subcategory_Code"})
                    # drop helper column
                    final_df = final_df.drop(columns=[c for c in ["Subcategories_norm"] if c in final_df.columns])
                    # Attach human-readable subcategory name from SubCategory.csv (if available)
                    try:
                        sub_ref = _fetch("SubCategory")
                        if len(sub_ref) > 0:
                            if "Code" in sub_ref.columns and "SubCategory" in sub_ref.columns:
                                # Normalize codes for matching
                                sub_ref["Code"] = sub_ref["Code"].astype(str).str.strip().str.upper()
                                final_df["Subcategory_Code"] = final_df.get("Subcategory_Code", "").astype(str).str.strip().str.upper()
                                final_df = final_df.merge(sub_ref[["Code", "SubCategory"]], left_on="Subcategory_Code", right_on="Code", how="left")
                                # keep the name under a clear column and drop the merge helper
                                if "SubCategory" in final_df.columns:
                                    final_df = final_df.rename(columns={"SubCategory": "Subcategory_Name"})
                                final_df = final_df.drop(columns=[c for c in ["Code"] if c in final_df.columns])
                    except Exception:
                        # non-fatal: proceed without subcategory name
                        pass

            # Enrich final_df with nutrition from Recipes and compute GL at optimal serving
            try:
                rec_df = _fetch("Recipe")
                if len(rec_df)>0:
                    # find recipe code column in recipes
                    code_col = None
                    for c in ["Recipe code", "Recipe_Code", "Recipe Code", "Code"]:
                        if c in rec_df.columns:
                            code_col = c
                            break
                    if code_col is not None:
                        rec_sel = rec_df[[code_col] + [col for col in ["Energy_ENERC_KJ","Carbohydrate_g", "TotalDietaryFibre_FIBTG_g"] if col in rec_df.columns]].copy()
                        rec_sel = rec_sel.rename(columns={code_col: "Recipe_Code"})
                        final_df = final_df.merge(rec_sel, on="Recipe_Code", how="left")
                    
                    final_df["Energy_ENERC_Kcal"] = final_df["Energy_ENERC_KJ"] / 4.184
                    # STEP 1: Create _opt_prop FIRST
                    final_df["_opt_prop"] = pd.to_numeric(final_df.get("Optimal proportion"), errors="coerce").fillna(0.0)

                    #Convert ALL relevant columns to numeric
                    num_cols = ["Energy_ENERC_Kcal", "Carbohydrate_g", "TotalDietaryFibre_FIBTG_g", "GI_Avg"]
                    for col in num_cols:
                        if col in final_df.columns:
                            final_df[col] = pd.to_numeric(final_df[col], errors="coerce")

                    #Multiply by optimal proportion
                    final_df["Energy_ENERC_Kcal"] = final_df["Energy_ENERC_Kcal"] * final_df["_opt_prop"]
                    final_df["Carbohydrate_g"] = final_df["Carbohydrate_g"] * final_df["_opt_prop"]
                    final_df["TotalDietaryFibre_FIBTG_g"] = final_df["TotalDietaryFibre_FIBTG_g"] * final_df["_opt_prop"]

                    # ensure numeric carbs, GI and optimal proportion
                    final_df["_carb_g"] = pd.to_numeric(final_df.get("Carbohydrate_g"), errors="coerce")
                    final_df["_gi"] = pd.to_numeric(final_df.get("GI_Avg"), errors="coerce")
                    final_df["_fiber_for_gl"] = pd.to_numeric(final_df["TotalDietaryFibre_FIBTG_g"], errors="coerce").fillna(0.0)

                    # compute GL at optimal serving: GI * ((Carbs - fiber)) / 100
                    carb_minus_fiber = (final_df["_carb_g"].fillna(0.0) - final_df["_fiber_for_gl"].fillna(0.0)).clip(lower=0.0)
                    final_df["GL"] = (final_df["_gi"].fillna(np.nan) * (carb_minus_fiber)) / 100.0
                    # if GI or carbs missing, leave GL as NaN
                else:
                    # recipes file missing — set GL to NaN
                    final_df["GL"] = np.nan
            except Exception:
                # non-fatal; leave GL unset
                final_df["GL"] = final_df.get("GL", np.nan)
        
        
        except Exception:
            # non-fatal; proceed without GI merge
            pass

        # Ensure all expected columns are present (fill missing with NaN)
        expected_cols = [
            "Day",
            "Meal_Time",
            "Recipe_Code",
            "Code_cooccurence",
            "Subcategories",
            "Dish_Type",
            "Recipe_Name",
            "Optimal proportion",
            "Recipe weight Original (g)",
            "Portion original",
            "Recipe weight Optimal (g)",
            "Portion optimal",
            "Description_tagging",
            "OPTIMAL_STATUS",
            "Subcategory_Code",
            "GI_Avg",
            "Energy_ENERC_Kcal",
            "Carbohydrate_g",
            "TotalDietaryFibre_FIBTG_g",
            "_fiber_for_gl",
            "_carb_g",
            "_gi",
            "_opt_prop",
            "GL",
        ]
        for c in expected_cols:
            if c not in final_df.columns:
                final_df[c] = pd.NA

        # Ensure numeric columns have numeric dtypes where possible
        numeric_cols = ["Energy_ENERC_Kcal","Carbohydrate_g", "TotalDietaryFibre_FIBTG_g", "_fiber_for_gl", "_carb_g", "_gi", "_opt_prop", "GL"]
        for nc in numeric_cols:
            if nc in final_df.columns:
                final_df[nc] = pd.to_numeric(final_df[nc], errors="coerce")

        #Aggregate GL per meal (Day + Meal_Time)
        try:
            meal_gl_df = (
                final_df.groupby(["Day", "Meal_Time"], as_index=False)["GL"]
                .sum()
                .rename(columns={"GL": "Meal_GL"})
            )
            #Merge back to main dataframe
            final_df = final_df.merge(meal_gl_df, on=["Day", "Meal_Time"], how="left")

        except Exception:
            # non-fatal
            final_df["Meal_GL"] = pd.NA

    else:
        final_df = pd.DataFrame()
    
    return final_df



def build_weekly_nutrient_summary(weekly_menu,weekly_min):
    menu = weekly_menu.copy()
    if menu.empty:
        return pd.DataFrame([
            {
                "Nutrient": nutrient_col,
                "Weekly_Requirement": float(required_val),
                "Achieved_From_Menu": 0.0,
                "Percent_Requirement_Met": 0.0,
            }
            for nutrient_col, required_val in weekly_min.items()
        ])

    serving = pd.to_numeric(menu.get("Serving", 1.0), errors="coerce").fillna(1.0)
    # Only retain a fixed set of reported nutrients (nutrient_cols) and the
    # three macro energy-ratio rows as requested.
    nutrient_cols = [
        "Energy_ENERC_Kcal", "Protein_PROTCNT_g", "TotalFat_FATCE_g", "TotalDietaryFibre_FIBTG_g",
        "CalciumCa_CA_mg", "ZincZn_ZN_mg", "IronFe_FE_mg", "MagnesiumMg_MG_mg", "VA_RAE_mcg",
        "TotalFolatesB9_FOLSUM_mcg", "VB12_mcg", "ThiamineB1_THIA_mg", "RiboflavinB2_RIBF_mg",
        "NiacinB3_NIA_mg", "TotalB6A_VITB6A_mg", "TotalAscorbicAcid_VITC_mg",
        "Carbohydrate_g", "Sodium_mg", "VITE_mg", "PhosphorusP_mg", "PotassiumK_mg", "Cholesterol_mg"
    ]

    rows = []
    # helper to safely get column total (serving-weighted)
    def _total(col_name: str) -> float:
        if col_name in menu.columns:
            vals = pd.to_numeric(menu[col_name], errors="coerce").fillna(0.0)
            return float((vals * serving).sum())
        return 0.0

    for col in nutrient_cols:
        req = weekly_min.get(col, None)
        req_val = float(req) if req is not None else np.nan
        ach = _total(col)
        pct = (100.0 * ach / req_val) if (not pd.isna(req_val) and req_val > 0) else np.nan
        rows.append({
            "Nutrient": col,
            "Weekly_Requirement": req_val,
            "Achieved_From_Menu": ach,
            "Percent_Requirement_Met": pct,
        })

    # Add macro percentage rows
    total_energy = _total("Energy_ENERC_Kcal")
    total_carb_g = _total("Carbohydrate_g")
    total_prot_g = _total("Protein_PROTCNT_g")
    total_fat_g = _total("TotalFat_FATCE_g")
    carb_energy = 4.0 * total_carb_g
    prot_energy = 4.0 * total_prot_g
    fat_energy = 9.0 * total_fat_g
    energy_den = total_energy if total_energy > 1e-6 else (carb_energy + prot_energy + fat_energy)
    if energy_den > 1e-6:
        carb_pct = 100.0 * carb_energy / energy_den
        prot_pct = 100.0 * prot_energy / energy_den
        fat_pct = 100.0 * fat_energy / energy_den
    else:
        carb_pct = prot_pct = fat_pct = np.nan

    rows.append({"Nutrient": "Carbohydrate_pct_energy", "Weekly_Requirement": np.nan, "Achieved_From_Menu": carb_pct, "Percent_Requirement_Met": np.nan})
    rows.append({"Nutrient": "Protein_pct_energy", "Weekly_Requirement": np.nan, "Achieved_From_Menu": prot_pct, "Percent_Requirement_Met": np.nan})
    rows.append({"Nutrient": "Fat_pct_energy", "Weekly_Requirement": np.nan, "Achieved_From_Menu": fat_pct, "Percent_Requirement_Met": np.nan})

    return pd.DataFrame(rows).reset_index(drop=True)

