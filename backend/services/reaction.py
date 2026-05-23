import logging
from datetime import datetime, timezone
from typing import List

from core.supabase import get_supabase
from models.schemas import MealSlot, ReactionType

logger = logging.getLogger("backend.services.reaction")


def save_reaction(
    user_id: str,
    plan_id: str,
    date: str,
    meal_slot: MealSlot,
    recipe_codes: List[str],
    reaction: ReactionType,
) -> None:
    get_supabase().table("MealReactions").insert(
        {
            "user_id": user_id,
            "plan_id": plan_id,
            "date": date,
            "timings": meal_slot.value,     # existing column name in DB
            "recipe_codes": recipe_codes,   # new jsonb column — see migration
            "reaction": reaction.value,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
    ).execute()
