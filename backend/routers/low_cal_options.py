import logging
from fastapi import APIRouter, Depends, HTTPException

from core.auth import get_current_user
from core.supabase import get_supabase
from services.profile_builder import build_profile
from services.replacement import _fetch_diet_allowed_codes

logger = logging.getLogger("backend.routers.low_cal_options")

router = APIRouter(prefix="/low-cal-options", tags=["low-cal-options"])

_LIST_FIELDS = 'Recipe_Code, Recipe_Name, Recipe_Category, Servings, Ctime, "Energy Kcals"'


def _clean(row: dict) -> dict:
    """Replace NaN floats with None so the row is JSON-serializable."""
    return {k: (None if (isinstance(v, float) and v != v) else v) for k, v in row.items()}


@router.get("")
def list_low_cal_options(user_id: str = Depends(get_current_user)):
    """Summary list for the low-cal-options section: name, category, servings,
    cook time, energy. Call GET /low-cal-options/{recipe_code} for every other
    column (full nutrient detail) on a selected recipe."""
    sb = get_supabase()
    resp = sb.table("low_cal_options").select(_LIST_FIELDS).order("Recipe_Name").execute()
    return [_clean(r) for r in (resp.data or [])]


@router.get("/user")
def list_low_cal_options_for_user(user_id: str = Depends(get_current_user)):
    """Same summary list as GET /low-cal-options, filtered to recipes
    compatible with the authenticated user's own dietary_type -- reads
    RecipeTagging's Vegetarian/Ovo-vegetarian columns via the same
    _fetch_diet_allowed_codes helper services/replacement.py's swap
    suggestions use. "non-veg" or an unknown/missing diet_type means no
    filtering (matches the main plan-generation pipeline's own behavior)."""
    sb = get_supabase()
    profile = build_profile(user_id)
    diet_type = (profile.get("diet_type") if profile else None) or ""
    allowed = _fetch_diet_allowed_codes(sb, diet_type)

    resp = sb.table("low_cal_options").select(_LIST_FIELDS).order("Recipe_Name").execute()
    rows = resp.data or []
    if allowed is not None:
        rows = [r for r in rows if str(r.get("Recipe_Code") or "").strip().upper() in allowed]
    return [_clean(r) for r in rows]


@router.get("/{recipe_code}")
def get_low_cal_option(recipe_code: str, user_id: str = Depends(get_current_user)):
    """Full detail (every column) for a single low-cal option recipe."""
    sb = get_supabase()
    resp = sb.table("low_cal_options").select("*").eq("Recipe_Code", recipe_code).execute()
    if not resp.data:
        raise HTTPException(status_code=404, detail=f"'{recipe_code}' not found in low_cal_options")
    return _clean(resp.data[0])
