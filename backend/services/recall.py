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


def compute_energy_for_quantity(recipe_code: Optional[str], food_qty) -> Optional[int]:
    """Recompute Energy_Kcal for a recipe code + entered quantity, in the same way
    log_recall's "changed" path does: entered quantity / RecipeTagging.Portion gives
    the eaten fraction, which scales the recipe's per-portion energy (Energy_ENERC_KJ).

    Used whenever Food_Qty is edited after the fact (routers/recall.py update
    endpoints) so Energy_Kcal doesn't go stale relative to the new quantity.
    """
    if not recipe_code or food_qty is None:
        return None
    sb = get_supabase()
    recipe = (
        sb.table("Recipe").select("Energy_ENERC_KJ").eq("Recipe_Code", recipe_code).maybe_single().execute()
    ).data
    if not recipe or recipe.get("Energy_ENERC_KJ") is None:
        return None
    tag = (
        sb.table("RecipeTagging").select("Portion").eq("Recipe_Code", recipe_code).maybe_single().execute()
    ).data

    try:
        entered_qty = float(food_qty)
        base_portion = float((tag or {}).get("Portion"))
        prop = (entered_qty / base_portion) if base_portion > 0 else 1.0
    except (TypeError, ValueError):
        prop = 1.0

    return int(round(float(recipe["Energy_ENERC_KJ"]) / 4.184 * prop))


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
            # Fetch recipe info and default unit (Description) from RecipeTagging
            recipe_resp = sb.table("Recipe").select("Recipe_Code, Recipe_Name, Energy_ENERC_KJ").in_("Recipe_Code", codes_to_log).execute()
            recipe_map = {r["Recipe_Code"]: r for r in (recipe_resp.data or [])}

            tag_resp = sb.table("RecipeTagging").select("Recipe_Code, Description, Portion").in_("Recipe_Code", codes_to_log).execute()
            tag_map = {t["Recipe_Code"]: t for t in (tag_resp.data or []) if t.get("Recipe_Code")}

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
                # actual_quantities is the absolute quantity the user entered, in the
                # recipe's own portion unit (e.g. Cups) — same as Food_Qty elsewhere.
                # Divide by RecipeTagging.Portion (the recipe's full-portion size) to
                # get the eaten fraction, exactly like build_daily_nutrient_summary
                # (routers/kpi.py) does when it reads Food_Qty back later.
                qty = actual_quantities[i] if actual_quantities and i < len(actual_quantities) else None
                tag_info = tag_map.get(code, {})
                try:
                    entered_qty = float(qty)
                    base_portion = float(tag_info.get("Portion"))
                    prop = (entered_qty / base_portion) if base_portion > 0 else 1.0
                except (TypeError, ValueError):
                    prop = 1.0

                recipe = recipe_map.get(code)
                if recipe:
                    row["Food_Name"] = recipe.get("Recipe_Name") or code
                    row["Food_Name_desc"] = code
                    kj = recipe.get("Energy_ENERC_KJ")
                    if kj:
                        row["Energy_Kcal"] = int(round(float(kj) / 4.184 * prop))
                else:
                    row["Food_Name"] = code
                    row["Food_Name_desc"] = code
                desc = tag_info.get("Description")
                if desc and str(desc).strip().lower() not in ("nan", "none", ""):
                    row["R_desc"] = str(desc).strip()
                if qty:
                    # Store the entered quantity as-is (absolute, same unit as the
                    # "ate as planned" path's Food_Qty) so both paths mean the same thing.
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
    now = datetime.now(timezone.utc)
    today = str(date_type.today())

    # If this is a post-only upload, find today's pre-only row for the same
    # user + meal slot and patch it rather than creating a second row.
    if image_url_post and not image_url_pre:
        existing_recalls = (
            sb.table("DietRecall")
            .select("ID")
            .eq("user_id", user_id)
            .eq("meal_slot", meal_slot.value)
            .eq("Date", today)
            .is_("image_url_post", "null")
            .order("created_at", desc=True)
            .limit(1)
            .execute()
            .data
        )
        if existing_recalls:
            recall_id = existing_recalls[0]["ID"]
            sb.table("DietRecall").update({"image_url_post": image_url_post}).eq("ID", recall_id).execute()
            existing_review = (
                sb.table("MealImageReview")
                .select("id")
                .eq("diet_recall_id", recall_id)
                .limit(1)
                .execute()
                .data
            )
            if existing_review:
                review_id = existing_review[0]["id"]
                sb.table("MealImageReview").update({"post_image_id": image_url_post}).eq("id", review_id).execute()
                return recall_id, review_id

    # Default: insert a new DietRecall + MealImageReview row (pre-only or both together).
    recall_id = str(uuid.uuid4())
    review_id = str(uuid.uuid4())

    sb.table("DietRecall").insert({
        "ID": recall_id,
        "user_id": user_id,
        "Date": today,
        "Time": now.strftime("%H:%M:%S"),
        "created_at": now.isoformat(),
        "plan_id": plan_id,
        "meal_slot": meal_slot.value,
        "image_url_pre": image_url_pre,
        "image_url_post": image_url_post,
    }).execute()

    sb.table("MealImageReview").insert({
        "id": review_id,
        "user_id": user_id,
        "diet_recall_id": recall_id,
        "pre_image_id": image_url_pre,
        "post_image_id": image_url_post,
        "review_status": "pending",
        "created_at": now.isoformat(),
    }).execute()

    # Auto-enqueue food identification when a pre-meal image is present.
    if image_url_pre:
        try:
            from services.food_id_worker import PROCESSING_SENTINEL, enqueue_food_id_job
            sb.table("MealImageReview").update(
                {"tracked_foods_by_ai": PROCESSING_SENTINEL}
            ).eq("id", review_id).execute()
            enqueue_food_id_job(review_id, image_url_pre)
        except Exception:
            logger.warning("Could not enqueue food ID job for review %s", review_id)

    return recall_id, review_id
