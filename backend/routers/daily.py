import logging
import math
from datetime import date as date_type
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from core.auth import get_current_user
from core.supabase import get_supabase
from models.schemas import (
    DailyMealItem,
    DailyPlanResponse,
    MealSlot,
    OnDemandReplacementRequest,
    OnDemandReplacementResponse,
    ReplacementsResponse,
    TimingSummary,
)
from services.replacement import get_preapproved_replacements, request_on_demand_replacement

logger = logging.getLogger("backend.routers.daily")

router = APIRouter(prefix="/plan", tags=["plan"])


def _round_food_qty(qty: Optional[float]) -> Optional[float]:
    """Round a portion quantity to the nearest 0.5 (0.1->0.5, 0.4->0.5, 0.74->0.5,
    0.76->1.0, 1.74->1.5, 1.76->2.0). Rounds .25/.75 boundaries up rather than
    Python's round() banker's-rounding (which would send 0.25 down to 0.0), and
    never rounds a positive quantity down to 0 — the smallest displayed portion
    is always 0.5."""
    if qty is None:
        return None
    try:
        qty = float(qty)
    except (TypeError, ValueError):
        return qty
    rounded = math.floor(qty * 2 + 0.5) / 2
    if qty > 0 and rounded <= 0:
        rounded = 0.5
    return rounded


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

    # Fetch GL data: GL per recipe, Meal_GL per timing
    gl_result = (
        sb.table("FinalSummary")
        .select("Meal_Time, Recipe_Code, GL, Meal_GL")
        .eq("user_id", user_id)
        .eq("plan_id", active_plan_id)
        .eq("Date", target_date)
        .execute()
    )

    # Build lookup maps from FinalSummary
    gl_by_item: dict = {}       # (Meal_Time, Recipe_Code) → GL
    meal_gl_by_timing: dict = {}  # Meal_Time → Meal_GL (first non-null wins)
    for row in (gl_result.data or []):
        timing = (row.get("Meal_Time") or "").strip()
        code = (row.get("Recipe_Code") or "").strip()
        gl = row.get("GL")
        meal_gl = row.get("Meal_GL")
        if timing and code:
            gl_by_item[(timing, code)] = gl
        if timing and meal_gl is not None and timing not in meal_gl_by_timing:
            meal_gl_by_timing[timing] = meal_gl

    # Attach per-item GL and accumulate per-timing kcal
    meals: List[DailyMealItem] = []
    kcal_by_timing: dict = {}
    seen_timings: list = []
    for row in (result.data or []):
        timing = (row.get("Timings") or "").strip()
        code = (row.get("Food_Name_desc") or "").strip()
        row["GL"] = gl_by_item.get((timing, code))
        row["Food_Qty"] = _round_food_qty(row.get("Food_Qty"))

        kcal = row.get("Energy_kcal")
        if timing:
            if kcal is not None:
                kcal_by_timing[timing] = kcal_by_timing.get(timing, 0.0) + kcal
            if timing not in seen_timings:
                seen_timings.append(timing)

        meals.append(DailyMealItem(**row))

    # Build per-timing summaries preserving meal order
    by_timing = [
        TimingSummary(
            timing=t,
            total_kcal=round(kcal_by_timing[t], 1) if t in kcal_by_timing else None,
            total_gl=round(meal_gl_by_timing[t], 2) if t in meal_gl_by_timing else None,
        )
        for t in seen_timings
    ]

    total_kcal_val = sum(kcal_by_timing.values()) if kcal_by_timing else None
    total_gl_val = sum(meal_gl_by_timing.values()) if meal_gl_by_timing else None

    return DailyPlanResponse(
        date=target_date,
        meals=meals,
        total_kcal=round(total_kcal_val, 1) if total_kcal_val is not None else None,
        total_gl=round(total_gl_val, 2) if total_gl_val is not None else None,
        by_timing=by_timing,
    )


@router.get("/replacements", response_model=ReplacementsResponse)
def get_replacements(
    date: str = Query(..., description="YYYY-MM-DD"),
    day: int = Query(..., description="Day number 1–7"),
    meal_slot: MealSlot = Query(...),
    recipe_codes: List[str] = Query(..., description="Current combination recipe codes"),
    user_id: str = Depends(get_current_user),
):
    """Return 3 pre-approved alternate combinations for the given slot and combination."""
    if not recipe_codes:
        raise HTTPException(status_code=400, detail="recipe_codes must not be empty")

    combos = get_preapproved_replacements(
        date=date,
        day=day,
        meal_slot=meal_slot,
        recipe_codes=recipe_codes,
    )
    return ReplacementsResponse(date=date, day=day, meal_slot=meal_slot, alternatives=combos)


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
