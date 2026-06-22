import logging
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from core.auth import get_current_user
from core.supabase import get_supabase
from models.schemas import PreferenceItem, PreferenceUpdateRequest

logger = logging.getLogger("backend.routers.preferences")

router = APIRouter(prefix="/preferences", tags=["preferences"])


@router.get("", response_model=list[PreferenceItem])
def get_preferences(
    onboarding_id: Optional[str] = Query(None, description="Filter by onboarding session ID"),
    user_id: str = Depends(get_current_user),
):
    """Return the authenticated user's food preferences."""
    sb = get_supabase()
    query = (
        sb.table("BE_Preference_onboarding")
        .select("id, meal_time, dish_type, sub_category, Reaction, onboarding_id")
        .eq("user_id", user_id)
    )
    if onboarding_id:
        query = query.eq("onboarding_id", onboarding_id)
    resp = query.order("id", desc=False).execute()
    return [
        PreferenceItem(
            id=str(r.get("id", "")),
            meal_time=r.get("meal_time"),
            dish_type=r.get("dish_type"),
            sub_category=r.get("sub_category"),
            reaction=r.get("Reaction"),
            onboarding_id=r.get("onboarding_id"),
        )
        for r in (resp.data or [])
    ]


@router.put("/{preference_id}", response_model=PreferenceItem)
def update_preference(
    preference_id: str,
    body: PreferenceUpdateRequest,
    user_id: str = Depends(get_current_user),
):
    """Update a food preference row belonging to the authenticated user."""
    updates = {k: v for k, v in {
        "meal_time": body.meal_time,
        "dish_type": body.dish_type,
        "sub_category": body.sub_category,
        "Reaction": body.reaction,
    }.items() if v is not None}

    if not updates:
        raise HTTPException(status_code=400, detail="No fields provided to update.")

    sb = get_supabase()
    resp = (
        sb.table("BE_Preference_onboarding")
        .update(updates)
        .eq("id", preference_id)
        .eq("user_id", user_id)
        .execute()
    )
    if not resp.data:
        raise HTTPException(status_code=404, detail="Preference not found.")
    r = resp.data[0]
    return PreferenceItem(
        id=str(r.get("id", "")),
        meal_time=r.get("meal_time"),
        dish_type=r.get("dish_type"),
        sub_category=r.get("sub_category"),
        reaction=r.get("Reaction"),
        onboarding_id=r.get("onboarding_id"),
    )


@router.delete("/{preference_id}", status_code=204)
def delete_preference(
    preference_id: str,
    user_id: str = Depends(get_current_user),
):
    """Delete a food preference row belonging to the authenticated user."""
    sb = get_supabase()
    resp = (
        sb.table("BE_Preference_onboarding")
        .delete()
        .eq("id", preference_id)
        .eq("user_id", user_id)
        .execute()
    )
    if not resp.data:
        raise HTTPException(status_code=404, detail="Preference not found.")
