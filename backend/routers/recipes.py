import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from core.auth import get_current_user
from core.supabase import get_supabase

logger = logging.getLogger("backend.routers.recipes")

router = APIRouter(prefix="/recipes", tags=["recipes"])


def _clean(row: dict) -> dict:
    """Replace NaN floats with None so the row is JSON-serializable."""
    return {k: (None if (isinstance(v, float) and v != v) else v) for k, v in row.items()}


_SLOT_COL_MAP = {"breakfast": "Breakfast", "lunch": "Lunch", "dinner": "Dinner", "snack": "Snack"}


@router.get("")
def get_recipes(
    page: int = Query(1, ge=1, description="Page number (1-based)"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
    search: Optional[str] = Query(None, description="Plain-text search on recipe name"),
    meal_slot: Optional[str] = Query(None, description="Filter by slot: breakfast, lunch, dinner, snack"),
    user_id: str = Depends(get_current_user),
):
    """Return paginated recipes. Use ?search= for plain-text name search, ?meal_slot= to filter by slot."""
    sb = get_supabase()
    offset = (page - 1) * page_size

    # Resolve meal_slot → list of allowed Recipe_Codes
    allowed_codes: Optional[list] = None
    if meal_slot:
        slot_col = _SLOT_COL_MAP.get(meal_slot.lower())
        if slot_col:
            tag_resp = sb.table("RecipeTagging").select("Recipe_Code").eq(slot_col, "1").execute()
            allowed_codes = [r["Recipe_Code"] for r in (tag_resp.data or [])]

    def _build_query(with_count: bool):
        fields = "Recipe_Code, Recipe_Name, Recipe_Category"
        q = sb.table("Recipe").select(fields, count="exact" if with_count else None, head=with_count)
        if search:
            q = q.ilike("Recipe_Name", f"%{search}%")
        if allowed_codes is not None:
            q = q.in_("Recipe_Code", allowed_codes) if allowed_codes else q.eq("Recipe_Code", "__no_match__")
        return q

    total = (_build_query(with_count=True).execute().count) or 0
    total_pages = max(1, -(-total // page_size))
    data = _build_query(with_count=False).range(offset, offset + page_size - 1).execute()

    return {
        "page": page,
        "page_size": page_size,
        "total": total,
        "total_pages": total_pages,
        "has_prev": page > 1,
        "has_next": page < total_pages,
        "recipes": [_clean(r) for r in (data.data or [])],
    }


@router.get("/search")
def search_recipes(
    q: str = Query(..., min_length=1, description="Plain-text recipe name to search"),
    meal_slot: Optional[str] = Query(None, description="Filter by slot: breakfast, lunch, dinner, snack"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user_id: str = Depends(get_current_user),
):
    """Search recipes by name. Optionally filter by meal slot."""
    sb = get_supabase()
    offset = (page - 1) * page_size

    allowed_codes: Optional[list] = None
    if meal_slot:
        slot_col = _SLOT_COL_MAP.get(meal_slot.lower())
        if slot_col:
            tag_resp = sb.table("RecipeTagging").select("Recipe_Code").eq(slot_col, "1").execute()
            allowed_codes = [r["Recipe_Code"] for r in (tag_resp.data or [])]

    def _build_query(with_count: bool):
        fields = "Recipe_Code, Recipe_Name, Recipe_Category"
        query = sb.table("Recipe").select(fields, count="exact" if with_count else None, head=with_count)
        query = query.ilike("Recipe_Name", f"%{q}%")
        if allowed_codes is not None:
            query = query.in_("Recipe_Code", allowed_codes) if allowed_codes else query.eq("Recipe_Code", "__no_match__")
        return query

    total = (_build_query(with_count=True).execute().count) or 0
    total_pages = max(1, -(-total // page_size))
    data = _build_query(with_count=False).range(offset, offset + page_size - 1).execute()

    return {
        "page": page,
        "page_size": page_size,
        "total": total,
        "total_pages": total_pages,
        "has_prev": page > 1,
        "has_next": page < total_pages,
        "recipes": [_clean(r) for r in (data.data or [])],
    }


@router.get("/{recipe_code}")
def get_recipe(recipe_code: str, user_id: str = Depends(get_current_user)):
    """Return full detail for a single recipe including RecipeTagging metadata."""
    sb = get_supabase()

    recipe_resp = sb.table("Recipe").select("*").eq("Recipe_Code", recipe_code).execute()
    if not recipe_resp.data:
        raise HTTPException(status_code=404, detail=f"Recipe '{recipe_code}' not found")

    data = _clean(recipe_resp.data[0])

    tag_resp = (
        sb.table("RecipeTagging").select("*").eq("Recipe_Code", recipe_code).execute()
    )
    if tag_resp.data:
        data["tagging"] = _clean(tag_resp.data[0])

    return data
