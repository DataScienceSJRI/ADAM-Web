import logging
from typing import List

from core.supabase import get_supabase
from models.schemas import MealSlot, OnDemandReplacementResponse, RecipeWithQty, SLOT_TO_TIMINGS

logger = logging.getLogger("backend.services.replacement")

_ENERGY_TARGET_KCAL: dict = {
    MealSlot.BREAKFAST: 400.0,
    MealSlot.LUNCH: 600.0,
    MealSlot.DINNER: 600.0,
    MealSlot.SNACK: 200.0,
}

_SLOT_TAG_COL: dict = {
    MealSlot.BREAKFAST: "Breakfast",
    MealSlot.LUNCH: "Lunch",
    MealSlot.DINNER: "Dinner",
    MealSlot.SNACK: "Snack",
}


def _is_tagged(row: dict, slot_col: str) -> bool:
    """Return True when a RecipeTagging row's slot column equals 1 (handles float strings like '1.0')."""
    try:
        return int(float(row.get(slot_col) or 0)) == 1
    except (TypeError, ValueError):
        return False


def get_preapproved_replacements(
    date: str,
    day: int,
    meal_slot: MealSlot,
    recipe_codes: List[str],
) -> List[List[dict]]:
    """
    For each recipe in the combination, find up to 3 same-subcategory alternatives
    that are tagged for the given meal slot.
    Transpose into up to 3 alternate combinations (one pick per position).
    """
    sb = get_supabase()
    slot_col = _SLOT_TAG_COL.get(meal_slot)

    per_recipe_alts: list[list[dict]] = []

    for rc in recipe_codes:
        rc = str(rc).strip()

        # Fetch this recipe's subcategory
        target_resp = sb.table("Recipe").select("Recipe_Code, Recipe_Category").eq("Recipe_Code", rc).execute()
        if not target_resp.data:
            continue

        subcat = target_resp.data[0].get("Recipe_Category", "")
        if not subcat:
            continue

        # Fetch a larger pool of same-subcategory candidates to allow for slot filtering
        candidate_resp = (
            sb.table("Recipe")
            .select("Recipe_Code, Recipe_Name")
            .eq("Recipe_Category", subcat)
            .neq("Recipe_Code", rc)
            .limit(20)
            .execute()
        )
        candidates = candidate_resp.data or []

        # Filter candidates by meal-slot tag using Python-side parsing (column stores "1.0"/"0.0" strings)
        if slot_col and candidates:
            cand_codes = [row["Recipe_Code"] for row in candidates]
            tag_resp = (
                sb.table("RecipeTagging")
                .select(f"Recipe_Code, {slot_col}")
                .in_("Recipe_Code", cand_codes)
                .execute()
            )
            tagged_codes = {row["Recipe_Code"] for row in (tag_resp.data or []) if _is_tagged(row, slot_col)}
            candidates = [row for row in candidates if row["Recipe_Code"] in tagged_codes]

        alts = [
            {
                "recipe_code": row["Recipe_Code"],
                "recipe_name": row.get("Recipe_Name") or "",
                "quantity": 1.0,
                "unit": "serving",
            }
            for row in candidates[:3]
        ]
        per_recipe_alts.append(alts)

    result_combos: list[list[dict]] = []
    for i in range(3):
        combo = [alts[i] for alts in per_recipe_alts if i < len(alts)]
        if combo:
            result_combos.append(combo)

    return result_combos


def request_on_demand_replacement(
    user_id: str,
    date: str,
    meal_slot: MealSlot,
    recipe_codes: List[str],
) -> OnDemandReplacementResponse:
    """
    Validate proposed recipe codes for the meal slot, compute serving quantities
    targeting the slot's energy budget, and update the Recommendation table.
    """
    sb = get_supabase()

    # Fetch only the proposed recipes
    recipe_resp = sb.table("Recipe").select("Recipe_Code, Recipe_Name, Energy_ENERC_KJ").in_("Recipe_Code", recipe_codes).execute()
    found = recipe_resp.data or []

    logger.info("on_demand: requested=%s found=%s", recipe_codes, [r["Recipe_Code"] for r in found])

    if len(found) < len(recipe_codes):
        logger.info("on_demand: possible=False — recipe not found in Recipe table")
        return OnDemandReplacementResponse(possible=False)

    # Check meal-slot tag in RecipeTagging — every requested code must have a row and be tagged
    slot_col = _SLOT_TAG_COL.get(meal_slot)
    if slot_col:
        tag_resp = (
            sb.table("RecipeTagging")
            .select(f"Recipe_Code, {slot_col}")
            .in_("Recipe_Code", recipe_codes)
            .execute()
        )
        logger.info("on_demand: tagging rows=%s", tag_resp.data)
        tag_map = {row["Recipe_Code"]: row for row in (tag_resp.data or [])}
        for rc in recipe_codes:
            if rc not in tag_map:
                logger.info("on_demand: possible=False — %s has no RecipeTagging row", rc)
                return OnDemandReplacementResponse(possible=False)
            if not _is_tagged(tag_map[rc], slot_col):
                logger.info("on_demand: possible=False — %s not tagged for %s (value=%s)", rc, slot_col, tag_map[rc].get(slot_col))
                return OnDemandReplacementResponse(possible=False)

    # Compute servings based on energy target
    target_energy = _ENERGY_TARGET_KCAL.get(meal_slot, 500.0)
    energy_per_recipe = target_energy / len(found)

    combination: list[RecipeWithQty] = []
    energy_by_code: dict[str, float] = {}
    for row in found:
        base_kj = float(row.get("Energy_ENERC_KJ") or 0)
        base_kcal = (base_kj / 4.184) if base_kj > 0 else 100.0
        serving = round(energy_per_recipe / base_kcal, 2)
        serving = max(0.25, min(serving, 3.0))
        energy_by_code[str(row["Recipe_Code"])] = round(serving * base_kcal, 1)
        combination.append(
            RecipeWithQty(
                recipe_code=str(row["Recipe_Code"]),
                recipe_name=str(row.get("Recipe_Name") or ""),
                quantity=serving,
                unit="serving",
            )
        )

    # Update Recommendation table — preserve plan_id, WeekNo, and onboarding_id from existing rows
    try:
        timings = SLOT_TO_TIMINGS[meal_slot]
        existing = (
            sb.table("Recommendation")
            .select("Pkey, plan_id, WeekNo, onboarding_id")
            .eq("user_id", user_id)
            .eq("Date", date)
            .eq("Timings", timings)
            .execute()
        )
        existing_plan_id: str | None = None
        existing_week_no: int | None = None
        existing_onboarding_id: str | None = None
        if existing.data:
            existing_plan_id = existing.data[0].get("plan_id")
            existing_week_no = existing.data[0].get("WeekNo")
            existing_onboarding_id = existing.data[0].get("onboarding_id")
            pkeys = [r["Pkey"] for r in existing.data]
            sb.table("Recommendation").delete().in_("Pkey", pkeys).execute()

        sb.table("Recommendation").insert(
            [
                {
                    "user_id": user_id,
                    "plan_id": existing_plan_id,
                    "onboarding_id": existing_onboarding_id,
                    "WeekNo": existing_week_no,
                    "Date": date,
                    "Timings": timings,
                    "Food_Name": item.recipe_name,
                    "Food_Name_desc": item.recipe_code,
                    "Food_Qty": item.quantity,
                    "Energy_kcal": energy_by_code.get(item.recipe_code),
                }
                for item in combination
            ]
        ).execute()
    except Exception as exc:
        logger.warning("Could not update Recommendation for on-demand replacement: %s", exc)

    return OnDemandReplacementResponse(possible=True, combination=combination)
