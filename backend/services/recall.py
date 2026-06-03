import logging
import uuid
from datetime import datetime, timezone, date as date_type
from typing import Optional, List

from core.supabase import get_supabase
from models.schemas import MealSlot, SLOT_TO_TIMINGS

logger = logging.getLogger("backend.services.recall")


def _fetch_planned_meals(user_id: str, plan_id: str, meal_slot: MealSlot, date: str) -> list:
    resp = (
        get_supabase()
        .table("Recommendation")
        .select("*")
        .eq("user_id", user_id)
        .eq("plan_id", plan_id)
        .eq("Timings", SLOT_TO_TIMINGS[meal_slot])
        .eq("Date", date)
        .execute()
    )
    return resp.data or []


def log_recall(
    user_id: str,
    plan_id: str,
    meal_slot: MealSlot,
    did_eat_as_planned: bool,
    date: Optional[str] = None,
    recipe_codes: Optional[List[str]] = None,
    actual_quantities: Optional[List[str]] = None,
) -> List[str]:
    sb = get_supabase()
    target_date = date or str(date_type.today())
    now = datetime.now(timezone.utc)
    recall_ids: List[str] = []

    if did_eat_as_planned:
        planned = _fetch_planned_meals(user_id, plan_id, meal_slot, target_date)

        if not planned:
            logger.warning(
                "No planned meals found for user=%s plan=%s slot=%s date=%s",
                user_id, plan_id, meal_slot.value, target_date,
            )

        for item in planned:
            recall_id = str(uuid.uuid4())
            row = {
                "ID": recall_id,
                "user_id": user_id,
                "Date": target_date,
                "Time": now.strftime("%H:%M:%S"),
                "created_at": now.isoformat(),
                "plan_id": plan_id,
                "meal_slot": meal_slot.value,
                "did_eat_as_planned": True,
                "Food_Name": item.get("Food_Name"),
                "Food_Name_desc": item.get("Food_Name_desc"),
                "Food_Qty": item.get("Food_Qty"),
                "R_desc": item.get("R_desc"),
                "Energy_Kcal": int(round(float(item["Energy_kcal"]))) if item.get("Energy_kcal") is not None else None,
            }
            sb.table("DietRecall").insert(row).execute()
            recall_ids.append(recall_id)

    else:
        codes_to_log = recipe_codes or []

        if not codes_to_log:
            # Skipped entirely — single row with no food info
            recall_id = str(uuid.uuid4())
            sb.table("DietRecall").insert({
                "ID": recall_id,
                "user_id": user_id,
                "Date": target_date,
                "Time": now.strftime("%H:%M:%S"),
                "created_at": now.isoformat(),
                "plan_id": plan_id,
                "meal_slot": meal_slot.value,
                "did_eat_as_planned": False,
                "notes": "skipped",
            }).execute()
            recall_ids.append(recall_id)
        else:
            # Fetch all provided recipe codes in one query
            recipe_resp = sb.table("Recipe").select("Recipe_Code, Recipe_Name, Energy_ENERC_KJ").in_("Recipe_Code", codes_to_log).execute()
            recipe_map = {r["Recipe_Code"]: r for r in (recipe_resp.data or [])}

            for i, code in enumerate(codes_to_log):
                recall_id = str(uuid.uuid4())
                row: dict = {
                    "ID": recall_id,
                    "user_id": user_id,
                    "Date": target_date,
                    "Time": now.strftime("%H:%M:%S"),
                    "created_at": now.isoformat(),
                    "plan_id": plan_id,
                    "meal_slot": meal_slot.value,
                    "did_eat_as_planned": False,
                    "notes": "changed",
                }
                recipe = recipe_map.get(code)
                if recipe:
                    row["Food_Name"] = recipe.get("Recipe_Name") or code
                    row["Food_Name_desc"] = code
                    kj = recipe.get("Energy_ENERC_KJ")
                    if kj:
                        row["Energy_Kcal"] = int(round(float(kj) / 4.184))
                else:
                    row["Food_Name"] = code
                    row["Food_Name_desc"] = code
                # Pick the matching quantity by index, fall back to None
                qty = actual_quantities[i] if actual_quantities and i < len(actual_quantities) else None
                if qty:
                    row["Food_Qty"] = qty
                sb.table("DietRecall").insert(row).execute()
                recall_ids.append(recall_id)

    return recall_ids


def log_recall_image(
    user_id: str,
    plan_id: str,
    meal_slot: MealSlot,
    image_url_pre: Optional[str],
    image_url_post: Optional[str],
) -> tuple[str, str]:
    sb = get_supabase()
    recall_id = str(uuid.uuid4())
    review_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)

    recall_row: dict = {
        "ID": recall_id,
        "user_id": user_id,
        "Date": str(date_type.today()),
        "Time": now.strftime("%H:%M:%S"),
        "created_at": now.isoformat(),
        "plan_id": plan_id,
        "meal_slot": meal_slot.value,
        "image_url_pre": image_url_pre,
        "image_url_post": image_url_post,
    }

    sb.table("DietRecall").insert(recall_row).execute()

    sb.table("MealImageReview").insert(
        {
            "id": review_id,
            "user_id": user_id,
            "diet_recall_id": recall_id,
            "pre_image_id": image_url_pre,
            "post_image_id": image_url_post,
            "review_status": "pending",
            "created_at": now.isoformat(),
        }
    ).execute()

    return recall_id, review_id
