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


def get_preapproved_replacements(
    date: str,
    day: int,
    meal_slot: MealSlot,
    recipe_codes: List[str],
) -> List[List[dict]]:
    """
    For each recipe in the combination, find up to 3 same-subcategory alternatives.
    Transpose into 3 alternate combinations (one pick per position).
    """
    sb = get_supabase()

    per_recipe_alts: list[list[dict]] = []

    for rc in recipe_codes:
        rc = str(rc).strip()

        # Fetch just this recipe to get its subcategory
        target_resp = sb.table("Recipe").select("Recipe_Code, Recipe_Category").eq("Recipe_Code", rc).execute()
        if not target_resp.data:
            continue

        subcat = target_resp.data[0].get("Recipe_Category", "")
        if not subcat:
            continue

        # Fetch alternatives in the same subcategory (exclude the current recipe)
        alts_resp = (
            sb.table("Recipe")
            .select("Recipe_Code, Recipe_Name")
            .eq("Recipe_Category", subcat)
            .neq("Recipe_Code", rc)
            .limit(3)
            .execute()
        )

        alts = [
            {
                "recipe_code": row["Recipe_Code"],
                "recipe_name": row.get("Recipe_Name") or "",
                "quantity": 1.0,
                "unit": "serving",
            }
            for row in (alts_resp.data or [])
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

    # Check meal-slot tag in RecipeTagging
    slot_col = _SLOT_TAG_COL.get(meal_slot)
    if slot_col:
        tag_resp = (
            sb.table("RecipeTagging")
            .select(f"Recipe_Code, {slot_col}")
            .in_("Recipe_Code", recipe_codes)
            .execute()
        )
        logger.info("on_demand: tagging rows=%s", tag_resp.data)
        for row in (tag_resp.data or []):
            try:
                tagged = int(float(row.get(slot_col) or 0)) == 1
            except (TypeError, ValueError):
                tagged = False
            if not tagged:
                logger.info("on_demand: possible=False — %s not tagged for %s (value=%s)", row["Recipe_Code"], slot_col, row.get(slot_col))
                return OnDemandReplacementResponse(possible=False)

    # Compute servings based on energy target
    target_energy = _ENERGY_TARGET_KCAL.get(meal_slot, 500.0)
    energy_per_recipe = target_energy / len(found)

    combination: list[RecipeWithQty] = []
    for row in found:
        base_kj = float(row.get("Energy_ENERC_KJ") or 0)
        base_kcal = (base_kj / 4.184) if base_kj > 0 else 100.0
        serving = round(energy_per_recipe / base_kcal, 2)
        serving = max(0.25, min(serving, 3.0))
        combination.append(
            RecipeWithQty(
                recipe_code=str(row["Recipe_Code"]),
                recipe_name=str(row.get("Recipe_Name") or ""),
                quantity=serving,
                unit="serving",
            )
        )

    # Update Recommendation table
    try:
        timings = SLOT_TO_TIMINGS[meal_slot]
        existing = (
            sb.table("Recommendation")
            .select("Pkey")
            .eq("user_id", user_id)
            .eq("Date", date)
            .eq("Timings", timings)
            .execute()
        )
        if existing.data:
            pkeys = [r["Pkey"] for r in existing.data]
            sb.table("Recommendation").delete().in_("Pkey", pkeys).execute()

        sb.table("Recommendation").insert(
            [
                {
                    "user_id": user_id,
                    "Date": date,
                    "Timings": timings,
                    "Food_Name": item.recipe_name,
                    "Food_Name_desc": item.recipe_code,
                    "Food_Qty": item.quantity,
                }
                for item in combination
            ]
        ).execute()
    except Exception as exc:
        logger.warning("Could not update Recommendation for on-demand replacement: %s", exc)

    return OnDemandReplacementResponse(possible=True, combination=combination)
