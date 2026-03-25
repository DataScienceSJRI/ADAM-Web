import traceback
import sys
import os
import tempfile
import json
from pathlib import Path

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException
from core.auth import get_current_user
from models.schemas import GeneratePlanRequest, GeneratePlanResponse, PlanStatusResponse
from services.data_loader import _fetch, load_data_from_supabase
from services.profile_builder import build_profile
from services.recommendation_writer import write_recommendations, get_plan_status
import logging


logger = logging.getLogger("backend.routers.plan")
from services.lp_optimizer import run_lp

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from Functions_Base import ADAMPersonalizationModel

router = APIRouter(prefix="/plan", tags=["plan"])


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

    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            model = ModelOptimiser(user_id=user_id, workspace=tmpdir, onboarding_id=body.onboarding_id)
            output_paths = model.run(
                uid=user_id,
                top_n=10,
                ear_group_col=profile["age_group_col"],
                category_weekly_rep=4,
                user_preference="yes",
                profile=profile,
            )

            recipes_df = _fetch("Recipes")
            recdf = _fetch("Rec_ADAM_yes_no")

            # weekly_menu and top_personalized_choices are DataFrames in the returned dict.
            # weekly_optimization_summary is a JSON file path — read it while tmpdir exists.
            weekly_menu = output_paths.get("weekly_menu")
            top_choices = output_paths.get("top_personalized_choices")

            os_path = output_paths.get("weekly_optimization_summary")
            opt_summary: dict = {}
            if isinstance(os_path, str) and Path(os_path).exists():
                with open(os_path) as f:
                    opt_summary = json.load(f)
            elif isinstance(os_path, dict):
                opt_summary = os_path

    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Model error: {str(e)}")

    if weekly_menu is None or weekly_menu.empty:
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
                print(f"[INFO] Supplemented weekly_menu with {len(extra_rows)} rows for missing meal times: "
                      f"{[m for m, _ in all_slots if str(m).strip() not in present_times]}")
    except Exception as _supp_err:
        logger.warning("Could not supplement missing meal times: %s", _supp_err)

    try:
        logger.info("Writing %d rows to recommendations for user_id=%s", len(weekly_menu) if weekly_menu is not None else 0, user_id)
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
