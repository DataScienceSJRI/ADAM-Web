import logging
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from core.auth import get_current_user
from core.supabase import get_supabase
from models.schemas import MealReactionRequest, MealSlot, ReactionResponse, ReactionItem, ReactionsListResponse
from services.reaction import save_reaction

logger = logging.getLogger("backend.routers.reaction")

router = APIRouter(prefix="/plan", tags=["reaction"])


@router.post("/reaction", response_model=ReactionResponse)
def log_reaction(body: MealReactionRequest, user_id: str = Depends(get_current_user)):
    """Log a like/dislike for a meal combination (list of recipe codes)."""
    save_reaction(
        user_id=user_id,
        plan_id=body.plan_id,
        date=body.date,
        meal_slot=body.meal_slot,
        recipe_codes=body.recipe_codes,
        reaction=body.reaction,
    )
    return ReactionResponse(status="ok")


@router.get("/reaction", response_model=ReactionsListResponse)
def get_reactions(
    plan_id: str = Query(...),
    date: Optional[str] = Query(None, description="Filter by date YYYY-MM-DD"),
    meal_slot: Optional[MealSlot] = Query(None),
    user_id: str = Depends(get_current_user),
):
    """Return the user's meal reactions for a plan, optionally filtered by date and slot."""
    sb = get_supabase()
    query = sb.table("MealReactions").select("*", count="exact").eq("user_id", user_id).eq("plan_id", plan_id)
    if date:
        query = query.eq("date", date)
    if meal_slot:
        query = query.eq("timings", meal_slot.value)
    resp = query.order("date", desc=True).execute()
    items = [
        ReactionItem(
            id=r.get("id"),
            date=r.get("date"),
            meal_slot=r.get("timings"),
            recipe_codes=r.get("recipe_codes"),
            reaction=r.get("reaction"),
        )
        for r in (resp.data or [])
    ]
    return ReactionsListResponse(items=items, total=resp.count or len(items))


@router.delete("/reaction")
def delete_reaction(
    plan_id: str = Query(...),
    date: str = Query(..., description="YYYY-MM-DD"),
    meal_slot: MealSlot = Query(...),
    user_id: str = Depends(get_current_user),
):
    """Remove a reaction for a specific plan, date and meal slot."""
    sb = get_supabase()
    resp = (
        sb.table("MealReactions")
        .delete()
        .eq("user_id", user_id)
        .eq("plan_id", plan_id)
        .eq("date", date)
        .eq("timings", meal_slot.value)
        .execute()
    )
    if not resp.data:
        raise HTTPException(status_code=404, detail="Reaction not found")
    return {"status": "deleted"}
