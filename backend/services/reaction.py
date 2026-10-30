import logging
from typing import List, Optional

from core.supabase import get_supabase
from models.schemas import MealSlot, ReactionType, SLOT_TO_TIMINGS

logger = logging.getLogger("backend.services.reaction")


def upsert_recipes_lu(user_id: str, recipe_codes: List[str], reaction: ReactionType) -> None:
    """Mirror a meal-plan like/dislike into Recipes_LU (L/U) so the standalone
    recipes page reflects mobile-app reactions, not just its own."""
    if not recipe_codes:
        return
    sb = get_supabase()
    lu_code = "L" if reaction == ReactionType.LIKE else "U"
    rows = [{"UID": user_id, "Recipe_Code": code, "Interaction": lu_code} for code in dict.fromkeys(recipe_codes)]
    sb.table("Recipes_LU").upsert(rows, on_conflict="UID,Recipe_Code").execute()


def save_reaction(
    user_id: str,
    plan_id: str,
    date: str,
    meal_slot: MealSlot,
    recipe_codes: List[str],
    reaction: ReactionType,
) -> None:
    sb = get_supabase()
    timings = SLOT_TO_TIMINGS[meal_slot]
    val = reaction.value

    # Every recipe in this slot gets the combo reaction, so mirror all of them into Recipes_LU
    slot_resp = sb.table("Recommendation").select("Food_Name_desc") \
        .eq("user_id", user_id).eq("plan_id", plan_id) \
        .eq("Date", date).eq("Timings", timings).execute()
    slot_codes = [r["Food_Name_desc"] for r in (slot_resp.data or []) if r.get("Food_Name_desc")]

    # Mark the whole combo reaction on every row in this meal slot
    sb.table("Recommendation").update({"Combo_Reaction": val}) \
        .eq("user_id", user_id).eq("plan_id", plan_id) \
        .eq("Date", date).eq("Timings", timings).execute()

    # Also mark per-recipe Reaction on the specific codes
    if recipe_codes:
        sb.table("Recommendation").update({"Reaction": val}) \
            .eq("user_id", user_id).eq("plan_id", plan_id) \
            .eq("Date", date).eq("Timings", timings) \
            .in_("Food_Name_desc", recipe_codes).execute()

    upsert_recipes_lu(user_id, slot_codes, reaction)


def _sync_subcategory_preference(user_id: str, recipe_code: str, meal_time: str, reaction: Optional[str]) -> None:
    """Keep the subcategory-level dislike signal in BE_Preference_onboarding
    (read by the next plan generation) in sync with a single recipe's
    like/dislike from the web dashboard.

    Scopes every delete/insert to this exact (user_id, onboarding_id,
    meal_time, sub_category) combination -- the client-side version of this
    (meal-card.tsx / meal-plan-table.tsx, now removed) deleted by just
    (user_id, sub_category, Reaction="disliked"), which also erased any
    onboarding-time preference for the same subcategory recorded under a
    different onboarding session or a different meal_time. No-ops if the
    recipe has no RecipeTagging.Subcategories."""
    sb = get_supabase()
    tag_resp = sb.table("RecipeTagging").select("Subcategories").eq("Recipe_Code", recipe_code).maybe_single().execute()
    sub_category = (tag_resp.data or {}).get("Subcategories") if tag_resp else None
    if not sub_category:
        return

    session_resp = (
        sb.table("BE_Onboarding_Sessions")
        .select("onboarding_id")
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .limit(1)
        .maybe_single()
        .execute()
    )
    onboarding_id = (session_resp.data or {}).get("onboarding_id") if session_resp else None

    scoped_delete = (
        sb.table("BE_Preference_onboarding")
        .delete()
        .eq("user_id", user_id)
        .eq("sub_category", sub_category)
        .eq("meal_time", meal_time)
        .eq("Reaction", "disliked")
    )
    scoped_delete = (
        scoped_delete.eq("onboarding_id", onboarding_id) if onboarding_id
        else scoped_delete.is_("onboarding_id", "null")
    )
    scoped_delete.execute()

    if reaction == "disliked":
        sb.table("BE_Preference_onboarding").insert({
            "user_id": user_id,
            "meal_time": meal_time,
            "sub_category": sub_category,
            "dish_type": None,
            "Reaction": "disliked",
            "onboarding_id": onboarding_id,
        }).execute()


def set_meal_card_reaction(user_id: str, pkey: int, recipe_code: str, meal_time: str, reaction: Optional[str]) -> None:
    """Like/dislike a single recipe from the web dashboard's meal card / plan
    table: updates Recommendation.Reaction for display (scoped to this user's
    own row) and syncs the BE_Preference_onboarding signal via
    _sync_subcategory_preference. reaction=None clears both."""
    sb = get_supabase()
    sb.table("Recommendation").update({"Reaction": reaction}).eq("Pkey", pkey).eq("user_id", user_id).execute()
    _sync_subcategory_preference(user_id, recipe_code, meal_time, reaction)

