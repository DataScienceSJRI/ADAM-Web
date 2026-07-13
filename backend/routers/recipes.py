import logging
import re
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from core.auth import get_current_user
from core.supabase import get_supabase
from models.schemas import LikedRecipesResponse, ReactionResponse, ReactionType

logger = logging.getLogger("backend.routers.recipes")

router = APIRouter(prefix="/recipes", tags=["recipes"])


def _clean(row: dict) -> dict:
    """Replace NaN floats with None so the row is JSON-serializable."""
    return {k: (None if (isinstance(v, float) and v != v) else v) for k, v in row.items()}


_SLOT_COL_MAP = {"breakfast": "Breakfast", "lunch": "Lunch", "dinner": "Dinner", "snacks": "Snack"}

# Safety cap on how many ILIKE matches get pulled back for ranking. PostgREST's
# .order() can't express "starts with X" > "whole word X" > "substring X"
# relevance, so a search fetches matches (bounded by this) and ranks them in
# Python instead of paginating server-side. Comfortably above what any real
# search term should match in the Recipe table.
_SEARCH_RANK_FETCH_CAP = 1000


def _search_rank_key(name: str, term: str, similarity: float = 0.0, relevance: Optional[float] = None) -> tuple:
    """Rank a recipe name against a search term: whole-word match (prefix or
    not) first, then any other substring match, then fuzzy-only matches
    (ranked by similarity score descending) last.

    Within a tier, recipes with a curated Recipe_order."Relevance order" value
    sort first, min to max; recipes without one fall after. Within that,
    shorter names (fewer modifiers -> the "plainer" variant, e.g. "Plain Rice"
    over "Rice Manu") rank first, so a bare-word match doesn't get pushed
    behind every name that merely happens to start with the term — alphabetical
    is the final tiebreak."""
    name_lower = (name or "").strip().lower()
    term_lower = term.strip().lower()
    escaped = re.escape(term_lower)
    if re.search(rf"\b{escaped}\b", name_lower):
        # whole-word match, whether or not it's the first word (a plain
        # .startswith() would also match "Dosakaya" for term "dosa", since
        # it's a literal string prefix even though "dosa" isn't a standalone
        # word there — \b rules that out).
        tier = 0
    elif term_lower in name_lower:
        tier = 1
    else:
        tier = 2  # fuzzy-only match (no substring at all), rank by similarity desc
    has_relevance = relevance is not None
    return (
        tier,
        -similarity if tier == 2 else 0.0,
        0 if has_relevance else 1,
        relevance if has_relevance else 0.0,
        len(name_lower),
        name_lower,
    )


def _resolve_allowed_codes(sb, meal_slot: Optional[str]) -> Optional[list]:
    """meal_slot -> list of Recipe_Codes tagged for that slot in RecipeTagging, or None if no filter."""
    if not meal_slot:
        return None
    slot_col = _SLOT_COL_MAP.get(meal_slot.lower())
    if not slot_col:
        return None
    tag_resp = sb.table("RecipeTagging").select("Recipe_Code").eq(slot_col, "1").execute()
    return [r["Recipe_Code"] for r in (tag_resp.data or [])]


def _fuzzy_search_rows(sb, search_term: str) -> Optional[list]:
    """Call the search_recipes_fuzzy Postgres function (substring match OR
    pg_trgm similarity — see migration in routers/recipes.py's search docs)
    so typos/alt-spellings like "idly" still find "Idli". Returns None if the
    function isn't installed yet, so the caller can fall back to plain ilike.

    Deliberately doesn't cache "unavailable" across requests: the DB migration
    can be applied while this process is still running (no code change, so
    --reload won't restart it), and a failed RPC call is cheap (a fast 404),
    so there's no good reason to risk fuzzy search staying stuck off."""
    try:
        resp = (
            sb.rpc("search_recipes_fuzzy", {"search_term": search_term})
            .limit(_SEARCH_RANK_FETCH_CAP)
            .execute()
        )
        return resp.data or []
    except Exception as exc:
        logger.warning("search_recipes_fuzzy RPC unavailable, falling back to ilike search: %s", exc)
        return None


def _fetch_relevance_order(sb, codes: list) -> dict:
    """Recipe_Code -> "Relevance order" (as float) for the given codes, from the
    curated Recipe_order table. Recipes missing a row there, or with a null
    order, are simply absent from the returned map — callers treat that as
    "no override", falling back to substring-match ranking."""
    if not codes:
        return {}
    resp = (
        sb.table("Recipe_order")
        .select('Recipe_Code, "Relevance order"')
        .in_("Recipe_Code", codes)
        .execute()
    )
    result = {}
    for r in resp.data or []:
        raw = r.get("Relevance order")
        if raw is None:
            continue
        try:
            result[r["Recipe_Code"]] = float(raw)
        except (TypeError, ValueError):
            continue
    return result


def _search_and_paginate(sb, search_term: Optional[str], meal_slot: Optional[str], page: int, page_size: int) -> dict:
    offset = (page - 1) * page_size
    allowed_codes = _resolve_allowed_codes(sb, meal_slot)
    fields = "Recipe_Code, Recipe_Name, Recipe_Category"

    def _base_query(with_count: bool):
        q = sb.table("Recipe").select(fields, count="exact" if with_count else None, head=with_count)
        if search_term:
            q = q.ilike("Recipe_Name", f"%{search_term}%")
        if allowed_codes is not None:
            q = q.in_("Recipe_Code", allowed_codes) if allowed_codes else q.eq("Recipe_Code", "__no_match__")
        return q

    if search_term:
        rows = _fuzzy_search_rows(sb, search_term)
        if rows is None:
            # search_recipes_fuzzy RPC not present yet (migration not run) —
            # fall back to plain substring search.
            rows = _base_query(with_count=False).limit(_SEARCH_RANK_FETCH_CAP).execute().data or []
        if allowed_codes is not None:
            allowed_set = set(allowed_codes)
            rows = [r for r in rows if r.get("Recipe_Code") in allowed_set]
        relevance_map = _fetch_relevance_order(sb, [r.get("Recipe_Code") for r in rows if r.get("Recipe_Code")])
        rows.sort(
            key=lambda r: _search_rank_key(
                r.get("Recipe_Name") or "",
                search_term,
                r.get("match_similarity") or 0.0,
                relevance_map.get(r.get("Recipe_Code")),
            )
        )
        total = len(rows)
        page_rows = rows[offset: offset + page_size]
    else:
        total = (_base_query(with_count=True).execute().count) or 0
        page_rows = _base_query(with_count=False).range(offset, offset + page_size - 1).execute().data or []

    total_pages = max(1, -(-total // page_size))
    return {
        "page": page,
        "page_size": page_size,
        "total": total,
        "total_pages": total_pages,
        "has_prev": page > 1,
        "has_next": page < total_pages,
        "recipes": [_clean(r) for r in page_rows],
    }


@router.get("")
def get_recipes(
    page: int = Query(1, ge=1, description="Page number (1-based)"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
    search: Optional[str] = Query(None, description="Plain-text search on recipe name"),
    meal_slot: Optional[str] = Query(None, description="Filter by slot: breakfast, lunch, dinner, snacks"),
    user_id: str = Depends(get_current_user),
):
    """Return paginated recipes. Use ?search= for plain-text name search, ?meal_slot= to filter by slot.
    When searching, results are ranked: prefix match first, then whole-word match,
    then any substring match; shorter names rank first within each tier."""
    sb = get_supabase()
    return _search_and_paginate(sb, search, meal_slot, page, page_size)


@router.get("/search")
def search_recipes(
    q: str = Query(..., min_length=1, description="Plain-text recipe name to search"),
    meal_slot: Optional[str] = Query(None, description="Filter by slot: breakfast, lunch, dinner, snacks"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user_id: str = Depends(get_current_user),
):
    """Search recipes by name, ranked: prefix match first, then whole-word match,
    then any other substring match; shorter names rank first within each tier.
    Optionally filter by meal slot."""
    sb = get_supabase()
    return _search_and_paginate(sb, q, meal_slot, page, page_size)


def _lu_recipe_codes(sb, user_id: str, lu_code: str) -> set:
    """Recipe codes the user liked/disliked via the standalone recipes page (Recipes_LU)."""
    resp = sb.table("Recipes_LU").select("Recipe_Code").eq("UID", user_id).eq("Interaction", lu_code).execute()
    return {r["Recipe_Code"] for r in (resp.data or []) if r.get("Recipe_Code")}


def _mobile_reaction_recipe_codes(sb, user_id: str, reaction_value: str) -> set:
    """Recipe codes the user liked/disliked from the mobile app's meal-plan reactions,
    which write directly to Recommendation.Reaction (per-recipe) / Combo_Reaction (whole slot)."""
    codes: set = set()
    per_recipe_resp = (
        sb.table("Recommendation").select("Food_Name_desc")
        .eq("user_id", user_id).eq("Reaction", reaction_value).execute()
    )
    codes.update(r["Food_Name_desc"] for r in (per_recipe_resp.data or []) if r.get("Food_Name_desc"))

    combo_resp = (
        sb.table("Recommendation").select("Food_Name_desc")
        .eq("user_id", user_id).eq("Combo_Reaction", reaction_value).execute()
    )
    codes.update(r["Food_Name_desc"] for r in (combo_resp.data or []) if r.get("Food_Name_desc"))

    return codes


def _list_reaction_recipes(sb, user_id: str, lu_code: str, mobile_reaction_value: str) -> dict:
    """Recipes the user has liked/disliked, merging the standalone recipes page (Recipes_LU)
    with the mobile app's meal-plan reactions (Recommendation.Reaction / Combo_Reaction),
    joined against Recipe for name/category."""
    codes = (
        _lu_recipe_codes(sb, user_id, lu_code)
        | _mobile_reaction_recipe_codes(sb, user_id, mobile_reaction_value)
    )
    if not codes:
        return {"items": [], "total": 0}
    recipe_resp = (
        sb.table("Recipe")
        .select("Recipe_Code, Recipe_Name, Recipe_Category")
        .in_("Recipe_Code", list(codes))
        .execute()
    )
    items = [
        {
            "Recipe_Code": r["Recipe_Code"],
            "Recipe_Name": r.get("Recipe_Name"),
            "Recipe_Category": r.get("Recipe_Category"),
        }
        for r in (recipe_resp.data or [])
    ]
    return {"items": items, "total": len(items)}


@router.get("/like", response_model=LikedRecipesResponse)
def get_liked_recipes(user_id: str = Depends(get_current_user)):
    """List recipes the current user has liked, from the recipes page or the mobile app's meal-plan reactions."""
    sb = get_supabase()
    return _list_reaction_recipes(sb, user_id, "L", ReactionType.LIKE.value)


@router.get("/dislike", response_model=LikedRecipesResponse)
def get_disliked_recipes(user_id: str = Depends(get_current_user)):
    """List recipes the current user has disliked, from the recipes page or the mobile app's meal-plan reactions."""
    sb = get_supabase()
    return _list_reaction_recipes(sb, user_id, "U", ReactionType.DISLIKE.value)


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


def _set_recipe_reaction(sb, recipe_code: str, user_id: str, interaction: str) -> dict:
    """Upsert into Recipes_LU keyed on (UID, Recipe_Code), so re-reacting overwrites the prior value."""
    sb.table("Recipes_LU").upsert(
        {"UID": user_id, "Recipe_Code": recipe_code, "Interaction": interaction},
        on_conflict="UID,Recipe_Code",
    ).execute()
    return {"status": "ok"}


@router.post("/{recipe_code}/like", response_model=ReactionResponse)
def like_recipe(recipe_code: str, user_id: str = Depends(get_current_user)):
    """Like a recipe"""
    sb = get_supabase()
    return _set_recipe_reaction(sb, recipe_code, user_id, "L")


@router.post("/{recipe_code}/dislike", response_model=ReactionResponse)
def dislike_recipe(recipe_code: str, user_id: str = Depends(get_current_user)):
    """Dislike a recipe"""
    sb = get_supabase()
    return _set_recipe_reaction(sb, recipe_code, user_id, "U")
