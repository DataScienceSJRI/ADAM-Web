import logging
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from core.auth import get_current_user
from core.supabase import get_supabase
from models.schemas import PreferenceCreateRequest, PreferenceItem, PreferenceUpdateRequest
from services.profile_builder import build_profile

logger = logging.getLogger("backend.routers.preferences")

router = APIRouter(prefix="/preferences", tags=["preferences"])

_CATEGORY_COLUMNS = {
    "breakfast": "Breakfast",
    "lunch": "Lunch",
    "dinner": "Dinner",
    "snacks": "Snacks",
    "beverage": "Beverage",
    "side_dish_breakfast": "Side_dish_breakfast",
    "side_dish_lunch": "Side_dish_lunch",
    "side_dish_dinner": "Side_dish_dinner",
}


def _is_truthy(v) -> bool:
    """SubCategory_Onboarding's flag columns are a mix of bigint (0/1) and
    text ("0"/"1") across columns -- compare as string to handle both."""
    return v is not None and str(v).strip() not in ("", "0")


def _latest_onboarding_id(sb, user_id: str) -> Optional[str]:
    """Most recent onboarding_id for this user, from BE_Onboarding_Sessions --
    so a preference added from mobile is scoped to a real session rather
    than left onboarding_id=NULL and invisible to the next plan generation
    (same lookup services/reaction.py's preference sync uses)."""
    resp = (
        sb.table("BE_Onboarding_Sessions")
        .select("onboarding_id")
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .limit(1)
        .maybe_single()
        .execute()
    )
    return (resp.data or {}).get("onboarding_id") if resp else None


def _row_to_item(r: dict) -> PreferenceItem:
    return PreferenceItem(
        id=str(r.get("id", "")),
        meal_time=r.get("meal_time"),
        dish_type=r.get("dish_type"),
        sub_category=r.get("sub_category"),
        reaction=r.get("Reaction"),
        onboarding_id=r.get("onboarding_id"),
    )


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


@router.get("/options")
def get_preference_options(
    category: str = Query(..., description=f"One of: {', '.join(_CATEGORY_COLUMNS)}"),
    user_id: str = Depends(get_current_user),
):
    """Sub-category options to pick from when adding a preference (POST
    /preferences) -- the same catalog web onboarding's meal-preferences-form
    reads from SubCategory_Onboarding, filtered to one category/tab.
    Auto-filtered to Veg == 1 if the user's own dietary_type is veg/vegan,
    same rule the web form applies."""
    col = _CATEGORY_COLUMNS.get(category.strip().lower())
    if not col:
        raise HTTPException(status_code=400, detail=f"category must be one of: {', '.join(_CATEGORY_COLUMNS)}")

    sb = get_supabase()
    resp = sb.table("SubCategory_Onboarding").select(f"Code, SubCategory, Veg, {col}").execute()
    rows = [r for r in (resp.data or []) if _is_truthy(r.get(col))]

    profile = build_profile(user_id)
    dietary_type = ((profile.get("diet_type") if profile else None) or "").strip().lower()
    if dietary_type in ("veg", "vegan"):
        rows = [r for r in rows if r.get("Veg") == 1]

    return [{"code": r.get("Code"), "sub_category": r.get("SubCategory")} for r in rows]


@router.post("", response_model=PreferenceItem, status_code=201)
def create_preference(body: PreferenceCreateRequest, user_id: str = Depends(get_current_user)):
    """Add a new food preference selection -- the mobile 'edit preferences'
    tab adding to whatever was picked on web during onboarding. Idempotent:
    if this exact (meal_time, sub_category, dish_type) is already selected
    for the user's current onboarding session, updates its reaction in place
    instead of inserting a duplicate row."""
    sb = get_supabase()
    onboarding_id = _latest_onboarding_id(sb, user_id)

    existing_q = (
        sb.table("BE_Preference_onboarding")
        .select("id")
        .eq("user_id", user_id)
        .eq("meal_time", body.meal_time)
        .eq("sub_category", body.sub_category)
    )
    existing_q = (
        existing_q.eq("dish_type", body.dish_type) if body.dish_type is not None
        else existing_q.is_("dish_type", "null")
    )
    existing_q = (
        existing_q.eq("onboarding_id", onboarding_id) if onboarding_id
        else existing_q.is_("onboarding_id", "null")
    )
    existing = existing_q.limit(1).execute()

    if existing.data:
        resp = (
            sb.table("BE_Preference_onboarding")
            .update({"Reaction": body.reaction})
            .eq("id", existing.data[0]["id"])
            .execute()
        )
    else:
        resp = (
            sb.table("BE_Preference_onboarding")
            .insert({
                "user_id": user_id,
                "meal_time": body.meal_time,
                "sub_category": body.sub_category,
                "dish_type": body.dish_type,
                "Reaction": body.reaction,
                "onboarding_id": onboarding_id,
            })
            .execute()
        )

    return _row_to_item(resp.data[0])


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


@router.delete("/{preference_id}", status_code=204, include_in_schema=False)
def delete_preference(
    preference_id: str,
    user_id: str = Depends(get_current_user),
):
    """Delete a food preference row belonging to the authenticated user.
    Hidden from Swagger -- the mobile 'remove a preference' flow should use
    PUT .../{id} with reaction="disliked" instead (same effect on plan
    generation per data_loader.py's Reaction != "disliked" filter, but keeps
    a record instead of silently vanishing the row). Kept around, unlisted,
    for general data cleanup."""
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
