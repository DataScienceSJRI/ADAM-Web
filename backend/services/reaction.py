import logging
from typing import List

from core.supabase import get_supabase
from models.schemas import MealSlot, ReactionType, SLOT_TO_TIMINGS

logger = logging.getLogger("backend.services.reaction")


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
        
