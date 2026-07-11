import logging
from typing import List

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

