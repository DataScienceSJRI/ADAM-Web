import logging
from datetime import date as date_type
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from core.auth import get_current_user
from core.supabase import get_supabase
from models.schemas import (
    DailyPlanResponse,
    MealSlot,
    OnDemandReplacementRequest,
    OnDemandReplacementResponse,
    ReplacementsResponse,
)
from services.replacement import get_preapproved_replacements, request_on_demand_replacement

logger = logging.getLogger("backend.routers.daily")

router = APIRouter(prefix="/plan", tags=["plan"])


def _latest_plan_id(user_id: str) -> Optional[str]:
    """Return the most recently created successful plan_id for the user."""
    sb = get_supabase()
    resp = (
        sb.table("BE_Onboarding_Sessions")
        .select("plan_id, created_at")
        .eq("user_id", user_id)
        .not_.is_("plan_id", "null")
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    if resp.data:
        return resp.data[0]["plan_id"]
    return None


@router.get("/daily", response_model=DailyPlanResponse)
def get_daily_plan(
    plan_date: Optional[str] = Query(None, description="YYYY-MM-DD, defaults to today"),
    plan_id: Optional[str] = Query(None, description="Override to a specific plan_id"),
    user_id: str = Depends(get_current_user),
):
    """Return the authenticated user's meals for the given date from their latest plan."""
    target_date = plan_date or str(date_type.today())
    active_plan_id = plan_id or _latest_plan_id(user_id)

    if not active_plan_id:
        return DailyPlanResponse(date=target_date, meals=[])

    sb = get_supabase()
    result = (
        sb.table("Recommendation")
        .select("*")
        .eq("user_id", user_id)
        .eq("plan_id", active_plan_id)
        .eq("Date", target_date)
        .execute()
    )
    return DailyPlanResponse(date=target_date, meals=result.data)


@router.get("/replacements", response_model=ReplacementsResponse)
def get_replacements(
    date: str = Query(..., description="YYYY-MM-DD"),
    day: int = Query(..., description="Day number 1–7"),
    meal_slot: MealSlot = Query(...),
    recipe_codes: List[str] = Query(..., description="Current combination recipe codes"),
    recipe_quantities: List[float] = Query(default=[], description="Serving quantities for each recipe code (same order); defaults to 1.0"),
    user_id: str = Depends(get_current_user),
):
    """Return 3 pre-approved alternate combinations for the given slot and combination, ranked by GL proximity."""
    if not recipe_codes:
        raise HTTPException(status_code=400, detail="recipe_codes must not be empty")

    return get_preapproved_replacements(
        date=date,
        day=day,
        meal_slot=meal_slot,
        recipe_codes=recipe_codes,
        recipe_quantities=recipe_quantities or None,
    )


@router.post("/replacements/request", response_model=OnDemandReplacementResponse)
def request_replacement(
    body: OnDemandReplacementRequest,
    user_id: str = Depends(get_current_user),
):
    """
    On-demand replacement: user proposes recipe codes (no quantities).
    Returns possible=False if codes are unknown or wrong meal slot.
    Returns possible=True with computed quantities and updates Recommendation.
    """
    if not body.recipe_codes:
        raise HTTPException(status_code=400, detail="recipe_codes must not be empty")

    return request_on_demand_replacement(
        user_id=user_id,
        date=body.date,
        meal_slot=body.meal_slot,
        recipe_codes=body.recipe_codes,
        original_recipe_codes=body.original_recipe_codes,
    )
