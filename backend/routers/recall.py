import logging
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from core.auth import get_current_user
from core.supabase import get_supabase
from models.schemas import (
    DietRecallImageRequest,
    DietRecallLogRequest,
    DietRecallUpdateRequest,
    MealSlot,
    RecallHistoryItem,
    RecallHistoryResponse,
    RecallImageResponse,
    RecallLogResponse,
)
from services.recall import log_recall, log_recall_image

logger = logging.getLogger("backend.routers.recall")

router = APIRouter(prefix="/recall", tags=["recall"])


@router.post("/log", response_model=RecallLogResponse)
def recall_log(body: DietRecallLogRequest, user_id: str = Depends(get_current_user)):
    """Record whether the user ate as planned for a given meal slot."""
    # recipe_codes (plural) takes priority; fall back to legacy recipe_code
    codes = body.recipe_codes or ([body.recipe_code] if body.recipe_code else None)
    # actual_quantities (plural) takes priority; fall back to legacy actual_quantity
    quantities = body.actual_quantities or ([body.actual_quantity] if body.actual_quantity else None)
    recall_ids = log_recall(
        user_id=user_id,
        plan_id=body.plan_id,
        meal_slot=body.meal_slot,
        did_eat_as_planned=body.did_eat_as_planned,
        date=body.date,
        recipe_codes=codes,
        actual_quantities=quantities,
    )
    return RecallLogResponse(status="ok", recall_ids=recall_ids)


@router.get("", response_model=RecallHistoryResponse)
def get_recall_history(
    date: Optional[str] = Query(None, description="Filter by date YYYY-MM-DD"),
    meal_slot: Optional[MealSlot] = Query(None),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user_id: str = Depends(get_current_user),
):
    """Return the authenticated user's diet recall history."""
    sb = get_supabase()
    query = sb.table("DietRecall").select("*", count="exact").eq("user_id", user_id)
    if date:
        query = query.eq("Date", date)
    if meal_slot:
        query = query.eq("meal_slot", meal_slot.value)
    query = query.order("Date", desc=True).order("Time", desc=True).range(offset, offset + limit - 1)
    resp = query.execute()
    items = [
        RecallHistoryItem(
            id=r.get("ID"),
            date=r.get("Date"),
            meal_slot=r.get("meal_slot"),
            did_eat_as_planned=r.get("did_eat_as_planned"),
            food_name=r.get("Food_Name"),
            food_qty=r.get("Food_Qty"),
            energy_kcal=r.get("Energy_Kcal"),
            notes=r.get("notes"),
        )
        for r in (resp.data or [])
    ]
    return RecallHistoryResponse(items=items, total=resp.count or len(items))

@router.put("/{recall_id}")
def update_recall(recall_id: str, body: DietRecallUpdateRequest, user_id: str = Depends(get_current_user)):
    """Update a diet recall entry belonging to the authenticated user."""
    updates = {k: v for k, v in {
        "did_eat_as_planned": body.did_eat_as_planned,
        "Food_Qty": body.food_qty,
        "notes": body.notes,
    }.items() if v is not None}

    if not updates:
        raise HTTPException(status_code=400, detail="No fields provided to update.")

    sb = get_supabase()
    resp = sb.table("DietRecall").update(updates).eq("ID", recall_id).eq("user_id", user_id).execute()
    if not resp.data:
        raise HTTPException(status_code=404, detail="Recall entry not found")
    return {"status": "updated", "id": recall_id}


@router.delete("/{recall_id}")
def delete_recall(recall_id: str, user_id: str = Depends(get_current_user)):
    """Delete a diet recall entry belonging to the authenticated user."""
    sb = get_supabase()
    resp = sb.table("DietRecall").delete().eq("ID", recall_id).eq("user_id", user_id).execute()
    if not resp.data:
        raise HTTPException(status_code=404, detail="Recall entry not found")
    return {"status": "deleted", "id": recall_id}


@router.post("/image", response_model=RecallImageResponse)
def recall_image(body: DietRecallImageRequest, user_id: str = Depends(get_current_user)):
    """Upload pre/post meal photo URLs; creates a MealImageReview row (pending)."""
    recall_id, review_id = log_recall_image(
        user_id=user_id,
        plan_id=body.plan_id,
        meal_slot=body.meal_slot,
        image_url_pre=body.image_url_pre,
        image_url_post=body.image_url_post,
    )
    return RecallImageResponse(status="ok", recall_id=recall_id, review_id=review_id)
