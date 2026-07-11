import logging
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from core.auth import get_current_user
from core.supabase import get_supabase
from models.schemas import (
    MealReactionRequest, MealSlot, ReactionResponse, ReactionItem, ReactionsListResponse, SLOT_TO_TIMINGS,
    WebMealReactionRequest, WebReactionItem, WebReactionsListResponse,
    RecipeReactionRequest,
)
from services.reaction import save_reaction, upsert_recipes_lu

logger = logging.getLogger("backend.routers.reaction")

router = APIRouter(prefix="/plan")


# ── Mobile endpoints (Recommendation table) ──────────────────────────────────

@router.post("/reaction", response_model=ReactionResponse, tags=["Reactions - Mobile"])
def log_reaction(body: MealReactionRequest, user_id: str = Depends(get_current_user)):
    """Log a like/dislike for a meal combination. Writes to Recommendation.Reaction / Combo_Reaction."""
    save_reaction(
        user_id=user_id,
        plan_id=body.plan_id,
        date=body.date,
        meal_slot=body.meal_slot,
        recipe_codes=body.recipe_codes,
        reaction=body.reaction,
    )
    return ReactionResponse(status="ok")


@router.get("/reaction", response_model=ReactionsListResponse, tags=["Reactions - Mobile"])
def get_reactions(
    plan_id: str = Query(...),
    date: Optional[str] = Query(None, description="Filter by date YYYY-MM-DD"),
    meal_slot: Optional[MealSlot] = Query(None),
    user_id: str = Depends(get_current_user),
):
    """Return meal reactions for a plan, grouped by date and meal slot. Reads from Recommendation table."""
    sb = get_supabase()
    query = (
        sb.table("Recommendation")
        .select("Date, Timings, Food_Name_desc, Reaction, Combo_Reaction")
        .eq("user_id", user_id)
        .eq("plan_id", plan_id)
        .not_.is_("Combo_Reaction", "null")
    )
    if date:
        query = query.eq("Date", date)
    if meal_slot:
        query = query.eq("Timings", SLOT_TO_TIMINGS[meal_slot])

    resp = query.execute()
    rows = resp.data or []

    grouped: dict = {}
    for r in rows:
        key = (r.get("Date"), r.get("Timings"))
        if key not in grouped:
            grouped[key] = {
                "date": r.get("Date"),
                "meal_slot": r.get("Timings"),
                "reaction": r.get("Combo_Reaction"),
                "recipe_codes": [],
            }
        if r.get("Food_Name_desc"):
            grouped[key]["recipe_codes"].append(r["Food_Name_desc"])

    items = [
        ReactionItem(
            date=g["date"],
            meal_slot=g["meal_slot"],
            recipe_codes=g["recipe_codes"],
            reaction=g["reaction"],
        )
        for g in grouped.values()
    ]
    return ReactionsListResponse(items=items, total=len(items))


@router.delete("/reaction", tags=["Reactions - Mobile"])
def delete_reaction(
    plan_id: str = Query(...),
    date: str = Query(..., description="YYYY-MM-DD"),
    meal_slot: MealSlot = Query(...),
    user_id: str = Depends(get_current_user),
):
    """Clear the reaction for a specific plan, date and meal slot. Clears Recommendation.Reaction / Combo_Reaction."""
    sb = get_supabase()
    timings = SLOT_TO_TIMINGS[meal_slot]
    resp = (
        sb.table("Recommendation")
        .update({"Reaction": None, "Combo_Reaction": None})
        .eq("user_id", user_id)
        .eq("plan_id", plan_id)
        .eq("Date", date)
        .eq("Timings", timings)
        .execute()
    )
    if not resp.data:
        raise HTTPException(status_code=404, detail="No reactions found for that slot")
    return {"status": "deleted"}


@router.post("/reaction/recipe", response_model=ReactionResponse, tags=["Reactions - Mobile"])
def log_recipe_reaction(body: RecipeReactionRequest, user_id: str = Depends(get_current_user)):
    """Like/dislike an individual recipe. Updates Recommendation.Reaction only (not Combo_Reaction)."""
    sb = get_supabase()
    query = (
        sb.table("Recommendation")
        .update({"Reaction": body.reaction.value})
        .eq("user_id", user_id)
        .eq("plan_id", body.plan_id)
        .eq("Food_Name_desc", body.recipe_code)
    )
    if body.date:
        query = query.eq("Date", body.date)
    resp = query.execute()
    if not resp.data:
        raise HTTPException(status_code=404, detail="No matching recipe found in plan")
    upsert_recipes_lu(user_id, [body.recipe_code], body.reaction)
    logger.info("Recipe reaction saved: user=%s recipe=%s reaction=%s", user_id, body.recipe_code, body.reaction.value)
    return ReactionResponse(status="ok")


# ── Web endpoints (MealReactions table) ──────────────────────────────────────

@router.get("/reaction/web", response_model=WebReactionsListResponse, tags=["Reactions - Web"])
def get_reactions_web(
    plan_id: str = Query(...),
    date: Optional[str] = Query(None, description="Filter by date YYYY-MM-DD"),
    timings: Optional[str] = Query(None, description="Filter by timing e.g. Breakfast"),
    user_id: str = Depends(get_current_user),
):
    """Return reactions from MealReactions table (web dashboard)."""
    sb = get_supabase()
    query = (
        sb.table("MealReactions")
        .select("*")
        .eq("plan_id", plan_id)
        .eq("user_id", user_id)
    )
    if date:
        query = query.eq("date", date)
    if timings:
        query = query.eq("timings", timings)
    resp = query.execute()
    items = [WebReactionItem(**r) for r in (resp.data or [])]
    return WebReactionsListResponse(items=items, total=len(items))


@router.post("/reaction/web", response_model=ReactionResponse, tags=["Reactions - Web"])
def log_reaction_web(body: WebMealReactionRequest, user_id: str = Depends(get_current_user)):
    """Save a like/dislike to MealReactions (web dashboard). Upserts — existing reaction for the same slot is replaced.

    - Per-recipe reaction: set recommendation_pkey, leave date/timings null.
    - Combo reaction: set date + timings, leave recommendation_pkey null.
    """
    sb = get_supabase()

    del_q = sb.table("MealReactions").delete().eq("plan_id", body.plan_id).eq("user_id", user_id)
    if body.recommendation_pkey is not None:
        del_q = del_q.eq("recommendation_pkey", body.recommendation_pkey)
    else:
        del_q = del_q.is_("recommendation_pkey", "null")
        if body.date:
            del_q = del_q.eq("date", body.date)
        if body.timings:
            del_q = del_q.eq("timings", body.timings)
    del_q.execute()

    row: dict = {"plan_id": body.plan_id, "user_id": user_id, "reaction": body.reaction.value}
    if body.recommendation_pkey is not None:
        row["recommendation_pkey"] = body.recommendation_pkey
    if body.date:
        row["date"] = body.date
    if body.timings:
        row["timings"] = body.timings
    sb.table("MealReactions").insert(row).execute()
    return ReactionResponse(status="ok")


@router.delete("/reaction/web", tags=["Reactions - Web"])
def delete_reaction_web(
    plan_id: str = Query(...),
    recommendation_pkey: Optional[int] = Query(None, description="Per-recipe: the Recommendation.Pkey"),
    date: Optional[str] = Query(None, description="Combo reactions: YYYY-MM-DD"),
    timings: Optional[str] = Query(None, description="Combo reactions: e.g. Breakfast"),
    user_id: str = Depends(get_current_user),
):
    """Delete a reaction from MealReactions (web dashboard).
    Provide recommendation_pkey for per-recipe reactions, or date + timings for combo reactions.
    """
    if recommendation_pkey is None and not (date and timings):
        raise HTTPException(status_code=400, detail="Provide recommendation_pkey OR both date and timings")
    sb = get_supabase()
    del_q = sb.table("MealReactions").delete().eq("plan_id", plan_id).eq("user_id", user_id)
    if recommendation_pkey is not None:
        del_q = del_q.eq("recommendation_pkey", recommendation_pkey)
    else:
        del_q = del_q.is_("recommendation_pkey", "null").eq("date", date).eq("timings", timings)
    resp = del_q.execute()
    if not resp.data:
        raise HTTPException(status_code=404, detail="No reaction found")
    return {"status": "deleted"}
