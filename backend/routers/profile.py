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
        breakfast_time=_extract_time(d.get("breakfast_time")),
        lunch_time=_extract_time(d.get("lunch_time")),
        dinner_time=_extract_time(d.get("dinner_time")),
        profile_url=b.get("profile_url"),
    )


def _to_timestamptz(t: str | None) -> str | None:
    """Coerce a bare time string like '08:30:00' to a valid timestamptz for Postgres."""
    if not t:
        return t
    if "T" in t or " " in t or len(t) > 12:
        return t
    return f"1970-01-01T{t}+00:00"


def _extract_time(t: str | None) -> str | None:
    """Strip any date prefix from a timestamptz and return just HH:MM:SS."""
    if not t:
        return t
    # "1970-01-01T08:30:00+00:00" → "08:30:00"
    # "1970-01-01 08:30:00+00" → "08:30:00"
    for sep in ("T", " "):
        if sep in t:
            time_part = t.split(sep)[1]
            # drop timezone suffix (+00:00, +00, Z, etc.)
            for tz in ("+", "-", "Z"):
                if tz in time_part:
                    time_part = time_part.split(tz)[0]
                    break
            return time_part
    return t


@router.put("/profile", response_model=UserProfileResponse)
def update_profile(body: UserProfileUpdateRequest, user_id: str = Depends(get_current_user)):
    """Update the authenticated user's profile."""
    sb = get_supabase()

    basic_fields = {
        "Age": int(body.age) if body.age is not None else None,
        "Gender": body.gender,
        "Weight": int(body.weight) if body.weight is not None else None,
        "Height": int(body.height) if body.height is not None else None,
        "Hba1c": body.hba1c,
        "Activity_levels": body.activity_level,
        "profile_url": body.profile_url,
    }
    basic_update = {k: v for k, v in basic_fields.items() if v is not None}

    detail_fields = {
        "diet_restrictions": body.diet_restrictions,
        "breakfast_time": _to_timestamptz(body.breakfast_time),
        "lunch_time": _to_timestamptz(body.lunch_time),
        "dinner_time": _to_timestamptz(body.dinner_time),
    }
    detail_update = {k: v for k, v in detail_fields.items() if v is not None}

    if basic_update:
        sb.table("BE_Basic_Details").update(basic_update).eq("user_id", user_id).execute()

    if detail_update:
        sb.table("BE_Preference_onboarding_details").update(detail_update).eq("user_id", user_id).execute()

    return get_profile(user_id=user_id)
