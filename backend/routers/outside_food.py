import logging
from fastapi import APIRouter, Depends

from core.auth import get_current_user
from core.roles import require_coordinator
from models.schemas import OutsideFoodDish, OutsideFoodSwapRequest, OutsideFoodSwapResponse
from services.outside_food import list_eligible_dishes, list_flagged_participants, swap_to_outside_food

logger = logging.getLogger("backend.routers.outside_food")
router = APIRouter(prefix="/outside-foods", tags=["outside-foods"])


@router.get("", response_model=list[OutsideFoodDish])
def get_eligible_dishes(user_id: str = Depends(get_current_user)):
    """Dishes a participant can pick when swapping a plan slot for an outside
    meal -- cuisine_dishes filtered to their own diet type."""
    return list_eligible_dishes(user_id)


@router.post("/swap", response_model=OutsideFoodSwapResponse)
def swap(body: OutsideFoodSwapRequest, user_id: str = Depends(get_current_user)):
    """Swap a plan slot to an outside-food dish. Hard-capped at 5 per the
    participant's own current plan week -- returns possible=False with
    reason="weekly_limit_reached" past that, without touching the plan."""
    return swap_to_outside_food(
        user_id=user_id,
        meal_date=body.date,
        meal_slot=body.meal_slot,
        recipe_code=body.recipe_code,
        quantity=body.quantity,
        original_recipe_codes=body.original_recipe_codes,
    )


@router.get("/flagged")
def get_flagged_participants(
    coordinator_id: str = Depends(get_current_user),
    role: str = Depends(require_coordinator),
):
    return list_flagged_participants(coordinator_id, role)
