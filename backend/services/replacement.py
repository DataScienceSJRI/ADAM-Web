import itertools
import logging
from typing import List

from core.supabase import get_supabase
from models.schemas import MealSlot, OnDemandReplacementResponse, RecipeWithQty, ReplacementsResponse, SLOT_TO_TIMINGS

_VALID_QUANTITIES: list[float] = [0.5, 1.0, 1.5, 2.0]
_GL_TOLERANCE = 0.20   # ±20% band around original meal GL
_GL_FLOOR = 1.0        # minimum absolute tolerance when original GL is near zero

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


def _compute_gl_map(sb, recipe_rows: list[dict]) -> dict[str, float]:
    """
    Compute GL for a list of recipe rows.
    GL = GI * max(0, Carbohydrate_g - TotalDietaryFibre_FIBTG_g) / 100
    GI is fetched from SubCategory_foods_GI_GL keyed by Recipe_Category (stored as Code).
    Returns {Recipe_Code: GL}.
    """
    if not recipe_rows:
        return {}

    categories = list({str(row.get("Recipe_Category") or "").strip() for row in recipe_rows if row.get("Recipe_Category")})
    gi_map: dict[str, float] = {}
    if categories:
        gi_resp = (
            sb.table("SubCategory_foods_GI_GL")
            .select("Code, GI_Avg")
            .in_("Code", categories)
            .execute()
        )
        gi_map = {
            str(r["Code"]).strip(): float(r.get("GI_Avg") or 0)
            for r in (gi_resp.data or [])
        }

    result: dict[str, float] = {}
    for row in recipe_rows:
        gi = gi_map.get(str(row.get("Recipe_Category") or "").strip(), 0.0)
        carb = float(row.get("Carbohydrate_g") or 0)
        fiber = float(row.get("TotalDietaryFibre_FIBTG_g") or 0)
        result[str(row["Recipe_Code"])] = gi * max(0.0, carb - fiber) / 100.0

    return result


def _fetch_slot_gl(sb, user_id: str, date: str, meal_slot: MealSlot) -> tuple[float, list[dict]]:
    """
    Return (total_gl, slot_rows) for the user's current plan for the given slot.
    Filters to the most recent plan_id to avoid stale rows from old plan versions.
    slot_rows includes Food_Name_desc (recipe code), Food_Qty, Pkey and plan metadata.
    """
    timings = SLOT_TO_TIMINGS[meal_slot]

    # Resolve the active plan_id by taking the most recently created plan for this user
    plan_resp = (
        sb.table("BE_Onboarding_Sessions")
        .select("plan_id")
        .eq("user_id", user_id)
        .not_.is_("plan_id", "null")
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    active_plan_id = (plan_resp.data[0].get("plan_id") if plan_resp.data else None)

    query = (
        sb.table("Recommendation")
        .select("Pkey, Food_Name_desc, Food_Qty, plan_id, WeekNo, onboarding_id")
        .eq("user_id", user_id)
        .eq("Date", date)
        .eq("Timings", timings)
    )
    if active_plan_id:
        query = query.eq("plan_id", active_plan_id)

    slot_rows = query.execute().data or []

    if not slot_rows:
        return 0.0, slot_rows

    codes = [str(r["Food_Name_desc"]) for r in slot_rows if r.get("Food_Name_desc")]
    recipe_rows = (
        sb.table("Recipe")
        .select("Recipe_Code, Recipe_Category, Carbohydrate_g, TotalDietaryFibre_FIBTG_g")
        .in_("Recipe_Code", codes)
        .execute()
    ).data or []

    gl_map = _compute_gl_map(sb, recipe_rows)
    qty_map = {str(r["Food_Name_desc"]): float(r.get("Food_Qty") or 1.0) for r in slot_rows}
    total_gl = sum(gl_map.get(rc, 0.0) * qty_map.get(rc, 1.0) for rc in codes)
    return total_gl, slot_rows


def _best_qty_combo(
    gl_per_recipe: list[float],
    target_gl: float,
    fixed_gl: float,
) -> list[float] | None:
    """
    Enumerate all combinations of _VALID_QUANTITIES for each recipe.
    Return the quantity list whose (fixed_gl + combo_gl) is closest to target_gl
    and falls within the ±_GL_TOLERANCE band, or None if no valid combo exists.
    """
    tolerance = max(_GL_FLOOR, target_gl * _GL_TOLERANCE)
    lo = target_gl - tolerance
    hi = target_gl + tolerance

    best_combo: list[float] | None = None
    best_delta = float("inf")

    for qtys in itertools.product(_VALID_QUANTITIES, repeat=len(gl_per_recipe)):
        combo_gl = sum(g * q for g, q in zip(gl_per_recipe, qtys))
        total_gl = fixed_gl + combo_gl
        if lo <= total_gl <= hi:
            delta = abs(total_gl - target_gl)
            if delta < best_delta:
                best_delta = delta
                best_combo = list(qtys)

    return best_combo


def get_preapproved_replacements(
    date: str,
    day: int,
    meal_slot: MealSlot,
    recipe_codes: List[str],
    recipe_quantities: List[float] | None = None,
) -> ReplacementsResponse:
    """
    For each recipe in the combination, find up to 3 same-subcategory alternatives
    that are tagged for the given meal slot, ranked by GL proximity to the original.
    Transpose into up to 3 alternate combinations (one pick per position).
    Returns original_gl (total meal GL at given quantities) alongside alternatives.
    """
    sb = get_supabase()
    slot_col = _SLOT_TAG_COL.get(meal_slot)

    # Pad/default quantities to 1.0 per recipe
    quantities: list[float] = list(recipe_quantities or [])
    while len(quantities) < len(recipe_codes):
        quantities.append(1.0)

    per_recipe_alts: list[list[dict]] = []
    total_original_gl: float = 0.0

    for rc, qty in zip(recipe_codes, quantities):
        rc = str(rc).strip()

        # Fetch this recipe's subcategory and nutrients needed for GL
        target_resp = (
            sb.table("Recipe")
            .select("Recipe_Code, Recipe_Category, Carbohydrate_g, TotalDietaryFibre_FIBTG_g")
            .eq("Recipe_Code", rc)
            .execute()
        )
        if not target_resp.data:
            continue

        row0 = target_resp.data[0]
        subcat = row0.get("Recipe_Category", "")
        if not subcat:
            continue

        original_gl = _compute_gl_map(sb, [row0]).get(rc, 0.0)
        total_original_gl += original_gl * qty

        # Fetch a larger pool of same-subcategory candidates for slot filtering + GL ranking
        candidate_resp = (
            sb.table("Recipe")
            .select("Recipe_Code, Recipe_Name, Recipe_Category, Carbohydrate_g, TotalDietaryFibre_FIBTG_g")
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

        # Compute GL for all candidates in one batch GI lookup, then rank by proximity to original
        gl_map = _compute_gl_map(sb, candidates)
        candidates.sort(key=lambda row: abs(gl_map.get(str(row["Recipe_Code"]), 0.0) - original_gl))

        alts = [
            {
                "recipe_code": row["Recipe_Code"],
                "recipe_name": row.get("Recipe_Name") or "",
                "quantity": qty,
                "unit": "serving",
                "gl": round(gl_map.get(str(row["Recipe_Code"]), 0.0) * qty, 2),
            }
            for row in candidates[:3]
        ]
        per_recipe_alts.append(alts)

    result_combos: list[list[dict]] = []
    for i in range(3):
        combo = [alts[i] for alts in per_recipe_alts if i < len(alts)]
        if combo:
            result_combos.append(combo)

    return ReplacementsResponse(
        date=date,
        day=day,
        meal_slot=meal_slot,
        original_gl=round(total_original_gl, 2),
        alternatives=result_combos,
    )


def request_on_demand_replacement(
    user_id: str,
    date: str,
    meal_slot: MealSlot,
    recipe_codes: List[str],
    original_recipe_codes: List[str] | None = None,
) -> OnDemandReplacementResponse:
    """
    Validate proposed recipe codes, find the quantity combination closest to the
    current slot's GL within ±20%, and write it to the Recommendation table.
    Rejects if no valid quantity combination exists.
    """
    sb = get_supabase()

    # Fetch nutritional data for proposed recipes (need GL + energy)
    recipe_resp = (
        sb.table("Recipe")
        .select("Recipe_Code, Recipe_Name, Recipe_Category, Carbohydrate_g, TotalDietaryFibre_FIBTG_g, Energy_ENERC_KJ")
        .in_("Recipe_Code", recipe_codes)
        .execute()
    )
    found = recipe_resp.data or []
    found_map = {str(r["Recipe_Code"]): r for r in found}

    logger.info("on_demand: requested=%s found=%s", recipe_codes, list(found_map.keys()))

    if len(found) < len(recipe_codes):
        missing = [rc for rc in recipe_codes if rc not in found_map]
        logger.info("on_demand: possible=False — recipes not found: %s", missing)
        return OnDemandReplacementResponse(possible=False)

    # Check meal-slot tag — every proposed recipe must be tagged for this slot
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
                logger.info("on_demand: possible=False — %s not tagged for %s", rc, slot_col)
                return OnDemandReplacementResponse(possible=False)

    # Fetch current slot rows for plan metadata (plan_id, WeekNo etc.) and original recipes' GL
    _, all_slot_rows = _fetch_slot_gl(sb, user_id, date, meal_slot)

    # Determine which recipes are being replaced and compute their current GL as the target
    replaced_set = set(original_recipe_codes) if original_recipe_codes else {
        str(r.get("Food_Name_desc") or "") for r in all_slot_rows if r.get("Food_Name_desc")
    }

    # Compute target GL from the original recipes being replaced (at their current plan quantities)
    original_codes_in_plan = [
        str(r.get("Food_Name_desc") or "") for r in all_slot_rows
        if r.get("Food_Name_desc") and str(r["Food_Name_desc"]) in replaced_set
    ]
    target_gl = 0.0
    if original_codes_in_plan:
        orig_recipe_rows = (
            sb.table("Recipe")
            .select("Recipe_Code, Recipe_Category, Carbohydrate_g, TotalDietaryFibre_FIBTG_g")
            .in_("Recipe_Code", original_codes_in_plan)
            .execute()
        ).data or []
        orig_gl_map = _compute_gl_map(sb, orig_recipe_rows)
        orig_qty_map = {
            str(r["Food_Name_desc"]): float(r.get("Food_Qty") or 1.0)
            for r in all_slot_rows if str(r.get("Food_Name_desc") or "") in replaced_set
        }
        target_gl = sum(orig_gl_map.get(rc, 0.0) * orig_qty_map.get(rc, 1.0) for rc in original_codes_in_plan)

    logger.info("on_demand: target_gl=%.2f (GL of recipes being replaced)", target_gl)

    # Compute per-unit GL for each proposed recipe
    gl_map = _compute_gl_map(sb, found)
    gl_per_recipe = [gl_map.get(str(rc), 0.0) for rc in recipe_codes]

    # Find the quantity combo whose GL is closest to target_gl and within ±20% band
    # fixed_gl=0: we compare proposed GL directly against the replaced recipes' GL
    best_qtys = _best_qty_combo(gl_per_recipe, target_gl, fixed_gl=0.0)
    if best_qtys is None:
        logger.info("on_demand: possible=False — no quantity combo within ±20%% GL band (target=%.2f)", target_gl)
        return OnDemandReplacementResponse(possible=False)

    logger.info("on_demand: accepted qtys=%s", best_qtys)

    combination: list[RecipeWithQty] = []
    energy_by_code: dict[str, float] = {}
    for rc, qty in zip(recipe_codes, best_qtys):
        row = found_map[rc]
        base_kj = float(row.get("Energy_ENERC_KJ") or 0)
        base_kcal = (base_kj / 4.184) if base_kj > 0 else 100.0
        energy_by_code[rc] = round(qty * base_kcal, 1)
        combination.append(
            RecipeWithQty(
                recipe_code=rc,
                recipe_name=str(row.get("Recipe_Name") or ""),
                quantity=qty,
                unit="serving",
                gl=round(gl_map.get(rc, 0.0) * qty, 2),
            )
        )

    # Update Recommendation table — reuse slot rows already fetched above
    try:
        timings = SLOT_TO_TIMINGS[meal_slot]

        existing_plan_id: str | None = all_slot_rows[0].get("plan_id") if all_slot_rows else None
        existing_week_no: int | None = all_slot_rows[0].get("WeekNo") if all_slot_rows else None
        existing_onboarding_id: str | None = all_slot_rows[0].get("onboarding_id") if all_slot_rows else None

        if original_recipe_codes:
            # Only delete the specific recipes being replaced, leave the rest of the combo intact
            pkeys_to_delete = [
                r["Pkey"] for r in all_slot_rows
                if r.get("Food_Name_desc") in original_recipe_codes
            ]
        else:
            # No original specified — replace the entire slot (legacy behaviour)
            pkeys_to_delete = [r["Pkey"] for r in all_slot_rows]

        if pkeys_to_delete:
            sb.table("Recommendation").delete().in_("Pkey", pkeys_to_delete).execute()

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
