import logging
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Query
from core.auth import get_current_user
from core.supabase import get_supabase

router = APIRouter(prefix="/kpi", tags=["kpi"])
logger = logging.getLogger("backend.routers.kpi")


def _latest_plan_id(sb, user_id: str) -> Optional[str]:
    resp = (
        sb.table("BE_Onboarding_Sessions")
        .select("plan_id")
        .eq("user_id", user_id)
        .not_.is_("plan_id", "null")
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    return resp.data[0]["plan_id"] if resp.data else None


@router.get("")
def get_kpi(
    plan_date: Optional[str] = Query(None, description="YYYY-MM-DD, defaults to today"),
    user_id: str = Depends(get_current_user),
):
    """
    Returns blood sugar control score and today's nutrition totals
    (carbs, protein, fat, fibre) from the user's active meal plan.
    """
    sb = get_supabase()
    target_date = plan_date or str(date.today())
    plan_id = _latest_plan_id(sb, user_id)

    if not plan_id:
        return {
            "date": target_date,
            "blood_sugar_control_score": None,
            "gl_per_day": None,
            "nutrition": {"carbs_g": 0, "protein_g": 0, "fat_g": 0, "fibre_g": 0},
            "message": "No plan found.",
        }

    # Fetch today's rows from FinalSummary
    summary_resp = (
        sb.table("FinalSummary")
        .select("Recipe_Code, Optimal_proportion, Carbohydrate_g, TotalDietaryFibre_FIBTG_g, GL")
        .eq("user_id", user_id)
        .eq("plan_id", plan_id)
        .eq("Date", target_date)
        .execute()
    )
    rows = summary_resp.data or []

    if not rows:
        return {
            "date": target_date,
            "blood_sugar_control_score": None,
            "gl_per_day": None,
            "nutrition": {"carbs_g": 0, "protein_g": 0, "fat_g": 0, "fibre_g": 0},
            "message": "No meals found for this date.",
        }

    # Fetch protein + fat from Recipe for today's recipe codes
    recipe_codes = list({r["Recipe_Code"] for r in rows if r.get("Recipe_Code")})
    recipe_resp = (
        sb.table("Recipe")
        .select("Recipe_Code, Protein_PROTCNT_g, TotalFat_FATCE_g")
        .in_("Recipe_Code", recipe_codes)
        .execute()
    )
    nutrient_map = {
        r["Recipe_Code"]: {
            "protein": float(r.get("Protein_PROTCNT_g") or 0),
            "fat": float(r.get("TotalFat_FATCE_g") or 0),
        }
        for r in (recipe_resp.data or [])
    }

    # Aggregate
    total_carbs = total_fibre = total_protein = total_fat = total_gl = 0.0
    for r in rows:
        prop = float(r.get("Optimal_proportion") or 1.0)
        total_carbs  += float(r.get("Carbohydrate_g") or 0)           # already weighted in FinalSummary
        total_fibre  += float(r.get("TotalDietaryFibre_FIBTG_g") or 0)
        total_gl     += float(r.get("GL") or 0)
        rc = r.get("Recipe_Code", "")
        total_protein += nutrient_map.get(rc, {}).get("protein", 0) * prop
        total_fat     += nutrient_map.get(rc, {}).get("fat", 0) * prop

    # Blood sugar control score: 100 = perfect (GL=0), 0 = at/above daily cap (GL≥90)
    score = round(max(0.0, min(100.0, (1 - total_gl / 90.0) * 100)), 1)

    return {
        "date": target_date,
        "blood_sugar_control_score": score,
        "gl_per_day": round(total_gl, 1),
        "nutrition": {
            "carbs_g": round(total_carbs, 1),
            "protein_g": round(total_protein, 1),
            "fat_g": round(total_fat, 1),
            "fibre_g": round(total_fibre, 1),
        },
    }
