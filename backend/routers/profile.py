import logging
from fastapi import APIRouter, Depends, HTTPException
from core.auth import get_current_user
from core.supabase import get_supabase
from models.schemas import UserProfileResponse, UserProfileUpdateRequest

logger = logging.getLogger("backend.routers.profile")

router = APIRouter(prefix="/user", tags=["user"])


@router.get("/profile", response_model=UserProfileResponse)
def get_profile(user_id: str = Depends(get_current_user)):
    """Return the authenticated user's profile."""
    sb = get_supabase()

    basic = sb.table("BE_Basic_Details").select("*").eq("user_id", user_id).limit(1).execute()
    details = sb.table("BE_Preference_onboarding_details").select("*").eq("user_id", user_id).limit(1).execute()

    b = basic.data[0] if basic.data else {}
    d = details.data[0] if details.data else {}

    return UserProfileResponse(
        user_id=user_id,
        age=b.get("Age"),
        gender=b.get("Gender"),
        weight=b.get("Weight"),
        height=b.get("Height"),
        hba1c=b.get("Hba1c"),
        activity_level=b.get("Activity_levels"),
        diet_restrictions=d.get("diet_restrictions"),
        breakfast_time=d.get("breakfast_time"),
        lunch_time=d.get("lunch_time"),
        dinner_time=d.get("dinner_time"),
    )


@router.put("/profile", response_model=UserProfileResponse)
def update_profile(body: UserProfileUpdateRequest, user_id: str = Depends(get_current_user)):
    """Update the authenticated user's profile."""
    sb = get_supabase()

    basic_fields = {
        "Age": int(body.age) if body.age is not None else None,
        "Gender": body.gender,
        "Weight": body.weight,
        "Height": int(body.height) if body.height is not None else None,
        "Hba1c": body.hba1c,
        "Activity_levels": body.activity_level,
    }
    basic_update = {k: v for k, v in basic_fields.items() if v is not None}

    detail_fields = {
        "diet_restrictions": body.diet_restrictions,
        "breakfast_time": body.breakfast_time,
        "lunch_time": body.lunch_time,
        "dinner_time": body.dinner_time,
    }
    detail_update = {k: v for k, v in detail_fields.items() if v is not None}

    if basic_update:
        sb.table("BE_Basic_Details").update(basic_update).eq("user_id", user_id).execute()

    if detail_update:
        sb.table("BE_Preference_onboarding_details").update(detail_update).eq("user_id", user_id).execute()

    return get_profile(user_id=user_id)
