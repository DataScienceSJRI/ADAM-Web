"""Builds the profile dict that Functions_Base expects from BE_Basic_Details and BE_Preference_onboarding_details."""

from typing import Optional
from core.supabase import get_supabase


# Maps (gender_prefix, activity_level) → BaseEar/BaseTul column name
_ACTIVITY_MAP = {
    "sedentary": "sedentary",
    "lightly active": "moderate",
    "moderately active": "moderate",
    "very active": "heavy",
    "extra active": "heavy",
}


def _get_age_group_col(gender: str, activity: str) -> str:
    gender_prefix = "Women" if gender.strip().lower().startswith("f") else "Men"
    activity_key = activity.strip().lower()
    level = _ACTIVITY_MAP.get(activity_key, "sedentary")
    return f"{gender_prefix}_{level}"


def build_profile(user_id: str, onboarding_id: str | None = None) -> Optional[dict]:
    """
    Fetch user details from Supabase and return a profile dict
    compatible with Functions_Base.run() and optimize_weekly_menu_with_constraints().
    Returns None if no basic details found for the user.
    """
    supabase = get_supabase()

    bd_query = supabase.table("BE_Basic_Details").select("*").eq("user_id", user_id)
    if onboarding_id:
        bd_query = bd_query.eq("onboarding_id", onboarding_id)
    bd_resp = bd_query.order("created_at", desc=True).limit(1).execute()
    if not bd_resp.data:
        return None

    bd = bd_resp.data[0]

    age = bd.get("Age") or 0
    gender = bd.get("Gender") or "Male"
    weight = bd.get("Weight") or 0
    height = bd.get("Height") or 0
    hba1c = bd.get("Hba1c")
    activity = bd.get("Activity_levels") or "Sedentary"

    pref_query = (
        supabase.table("BE_Preference_onboarding_details")
        .select("diet_restrictions, breakfast_time, lunch_time, dinner_time")
        .eq("user_id", user_id)
    )
    if onboarding_id:
        pref_query = pref_query.eq("onboarding_id", onboarding_id)
    pref_details_resp = pref_query.order("created_at", desc=True).limit(1).execute()
    pref_row = pref_details_resp.data[0] if pref_details_resp.data else {}

    _restriction_map = {
        "veg":         "veg",
        "non veg":     "non-veg",
        "vegan":       "veg", 
        "gluten free": "gluten-free",
    }
    raw_diet = (pref_row.get("diet_restrictions") or "veg").strip().lower()
    diet_type = _restriction_map.get(raw_diet, "veg")

    breakfast_time = pref_row.get("breakfast_time")
    lunch_time     = pref_row.get("lunch_time")
    dinner_time    = pref_row.get("dinner_time")

    bmi = None
    if height and height > 0 and weight and weight > 0:
        height_m = height / 100.0
        bmi = round(weight / (height_m ** 2), 1)

    age_group_col = _get_age_group_col(gender, activity)

    return {
        "age": age,
        "gender": gender,
        "weight": weight,
        "height": height,
        "bmi": bmi,
        "hba1c": hba1c,
        "activity_levels": activity,
        "diet_type": diet_type,
        "age_group_col": age_group_col,
        "breakfast_time": breakfast_time,
        "lunch_time": lunch_time,
        "dinner_time": dinner_time,
    }
