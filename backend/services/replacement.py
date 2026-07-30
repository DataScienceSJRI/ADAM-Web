import itertools
import logging
from typing import List, Optional

from core.supabase import get_supabase
from models.schemas import MealSlot, OnDemandReplacementResponse, RecipeWithQty, ReplacementsResponse, SLOT_TO_TIMINGS
from services.profile_builder import build_profile

VALID_QUANTITIES: list[float] = [0.5, 1.0, 1.5, 2.0]
_GL_TOLERANCE = 0.20   # ±20% band around original meal GL
_GL_FLOOR = 1.0        # minimum absolute tolerance when original GL is near zero

logger = logging.getLogger("backend.services.replacement")

_ENERGY_TARGET_KCAL: dict = {
    MealSlot.BREAKFAST: 400.0,
    MealSlot.LUNCH: 600.0,
    MealSlot.DINNER: 600.0,
    MealSlot.SNACK: 200.0,
}


def _fetch_adam_approved_codes(sb) -> set[str]:
    """Recipe codes flagged ADAM_Recipes == 1 in Rec_ADAM_yes_no — the same
    eligibility gate calculate_recipe_gl.py and the main plan-generation
    pipeline use. Candidates outside this set shouldn't surface as swap
    suggestions even if they're otherwise a good GL match."""
    rows = sb.table("Rec_ADAM_yes_no").select("Recipe_Code, ADAM_Recipes").execute().data or []
    return {
        str(r["Recipe_Code"]).strip().upper()
        for r in rows
        if r.get("Recipe_Code") and str(r.get("ADAM_Recipes")) == "1"
    }


_DIET_COLUMN_MAP = {
    "veg": "Vegetarian",
    "vegan": "Vegetarian",
    "non-veg": "Non vegetarian",
    "egg": "Ovo-vegetarian",
    "ovo-veg": "Ovo-vegetarian",
}


def _fetch_diet_allowed_codes(sb, diet_type: Optional[str]) -> Optional[set[str]]:
    """
    Recipe codes allowed under the user's dietary_type preference — same
    columns/logic as services/data_loader.py's live filter (what the main
    plan-generation pipeline uses), reading RecipeTagging's 1/0
    "Vegetarian"/"Ovo-vegetarian" columns. "non-veg" and unknown/missing
    diet_type both mean no filtering (matches the main pipeline exactly),
    signalled by returning None rather than an empty/permissive set.
    """
    col = _DIET_COLUMN_MAP.get((diet_type or "").strip().lower())
    if col is None or col == "Non vegetarian":
        return None

    rows = (
        sb.table("RecipeTagging")
        .select("Recipe_Code, Vegetarian, \"Ovo-vegetarian\"")
        .execute()
        .data
    ) or []

    def _as_float(v):
        try:
            return float(v) if v is not None else None
        except (TypeError, ValueError):
            return None

    allowed: set[str] = set()
    for r in rows:
        code = r.get("Recipe_Code")
        if not code:
            continue
        veg = _as_float(r.get("Vegetarian"))
        if col == "Ovo-vegetarian":
            ovo = _as_float(r.get("Ovo-vegetarian"))
            ok = (veg == 1) or (veg == 0 and ovo == 1)
        else:
            ok = veg == 1
        if ok:
            allowed.add(str(code).strip().upper())
    return allowed


def _fetch_excluded_recipe_codes(sb, user_id: str) -> set[str]:
    """
    Union of recipes that should never be shown to this user — same
    sources/logic as services/data_loader.py's live filters:

    - Explicitly disliked: Recipes_LU (UID + Interaction=="U") and
      Recommendation rows where Reaction or Combo_Reaction == "dislike"
      (Food_Name_desc is the recipe code column there).
    - Allergens: BE_Preference_onboarding_details.health_details
      .allergy_food_codes (ingredient codes), mapped to recipes via
      Recipes_ingredient.Ing_Id -> Recipe_Code.
    """
    excluded: set[str] = set()

    lu_rows = (
        sb.table("Recipes_LU").select("Recipe_Code").eq("UID", user_id).eq("Interaction", "U").execute().data
    ) or []
    excluded.update(str(r["Recipe_Code"]).strip().upper() for r in lu_rows if r.get("Recipe_Code"))

    reaction_rows = (
        sb.table("Recommendation")
        .select("Food_Name_desc")
        .eq("user_id", user_id)
        .eq("Reaction", "dislike")
        .execute()
        .data
    ) or []
    excluded.update(str(r["Food_Name_desc"]).strip().upper() for r in reaction_rows if r.get("Food_Name_desc"))

    combo_rows = (
        sb.table("Recommendation")
        .select("Food_Name_desc")
        .eq("user_id", user_id)
        .eq("Combo_Reaction", "dislike")
        .execute()
        .data
    ) or []
    excluded.update(str(r["Food_Name_desc"]).strip().upper() for r in combo_rows if r.get("Food_Name_desc"))

    health_rows = (
        sb.table("BE_Preference_onboarding_details").select("health_details").eq("user_id", user_id).execute().data
    ) or []
    allergy_codes: set[str] = set()
    for row in health_rows:
        details = row.get("health_details")
        if isinstance(details, dict):
            allergy_codes.update(str(c).strip() for c in (details.get("allergy_food_codes") or []) if c is not None)

    if allergy_codes:
        ing_rows = (
            sb.table("Recipes_ingredient")
            .select("Recipe_Code, Ing_Id")
            .in_("Ing_Id", list(allergy_codes))
            .execute()
            .data
        ) or []
        excluded.update(str(r["Recipe_Code"]).strip().upper() for r in ing_rows if r.get("Recipe_Code"))

    return excluded


def _fetch_eligible_codes(sb, user_id: str) -> set[str]:
    """
    Combines all eligibility gates candidates must pass to surface as a swap
    suggestion: ADAM-approved, matches the user's dietary preference, and
    isn't disliked or an allergen — the same pool the main plan-generation
    pipeline draws from (services/data_loader.py), minus the meal-slot tag
    filter (deliberately not applied here — see _rank_alternatives_for_recipe).
    """
    eligible = _fetch_adam_approved_codes(sb)

    profile = build_profile(user_id)
    diet_allowed = _fetch_diet_allowed_codes(sb, profile.get("diet_type") if profile else None)
    if diet_allowed is not None:
        eligible &= diet_allowed

    eligible -= _fetch_excluded_recipe_codes(sb, user_id)
    return eligible


def _compute_gl_map(sb, recipe_rows: list[dict]) -> dict[str, float]:
    """
    Compute GL for a list of recipe rows.
    GL = GI * Carbohydrate_g / 100
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
        # result[str(row["Recipe_Code"])] = gi * max(0.0, carb - fiber) / 100.0
        result[str(row["Recipe_Code"])] = gi * carb / 100.0

    return result


def _fetch_portion_map(sb, recipe_codes: list[str]) -> dict[str, float]:
    """RecipeTagging.Portion per recipe code — the reference amount Recipe's
    nutrient columns (Carbohydrate_g etc.) were computed for. Needed to turn an
    absolute Food_Qty (e.g. "4.2 cups") into a proportion (Food_Qty / Portion)
    before scaling a full-portion GL/energy value, same convention
    services/recall.py's gl_for_quantity uses."""
    if not recipe_codes:
        return {}
    rows = (
        sb.table("RecipeTagging")
        .select("Recipe_Code, Portion")
        .in_("Recipe_Code", recipe_codes)
        .execute()
        .data
    ) or []
    result = {}
    for r in rows:
        try:
            result[str(r["Recipe_Code"])] = float(r["Portion"])
        except (TypeError, ValueError, KeyError):
            continue
    return result


def _fetch_slot_gl(sb, user_id: str, date: str, meal_slot: MealSlot) -> tuple[float, list[dict]]:
    """
    Return (total_gl, slot_rows) for the user's current plan for the given slot.
    Filters to the most recent plan_id to avoid stale rows from old plan versions.
    slot_rows includes Food_Name_desc (recipe code), Food_Qty, Pkey and plan metadata.
    """
    timings = SLOT_TO_TIMINGS[meal_slot]

    # Resolve the active plan_id as the one that actually has rows for `date`.
    # BE_Onboarding_Sessions.plan_id is NOT a history: it's UPDATEd keyed on
    # onboarding_id, so each newly generated plan overwrites the previous
    # plan_id there. Once a next-week plan has been auto-generated (day 6,
    # 9pm IST), that column only points at the NEW plan even while `date`
    # still falls in the OLD (still-current) week, causing this to match
    # zero rows for a date that does have data. Recommendation itself is the
    # only place plan history survives, so resolve straight from it.
    date_resp = (
        sb.table("Recommendation")
        .select("plan_id, Pkey")
        .eq("user_id", user_id)
        .eq("Date", date)
        .execute()
    )
    date_rows = date_resp.data or []
    if date_rows:
        # Normally exactly one plan_id covers a given date. If more than one
        # does (e.g. a regenerated plan left stale rows behind), prefer the
        # one with the highest Pkey (most recently inserted).
        active_plan_id = max(date_rows, key=lambda r: r.get("Pkey") or 0)["plan_id"]
    else:
        plan_resp = (
            sb.table("BE_Onboarding_Sessions")
            .select("plan_id")
            .eq("user_id", user_id)
            .not_.is_("plan_id", "null")
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        active_plan_id = plan_resp.data[0]["plan_id"] if plan_resp.data else None

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
    portion_map = _fetch_portion_map(sb, codes)
    # Food_Qty is an absolute quantity in the recipe's own portion unit (e.g.
    # "4.2 cups") — divide by Portion to get the proportion of a full portion
    # gl_map's per-recipe value represents, matching services/recall.py's
    # gl_for_quantity. Falls back to treating Food_Qty as already-a-proportion
    # only when Portion is unknown (missing RecipeTagging row).
    def _proportion(rc: str) -> float:
        qty = qty_map.get(rc, 1.0)
        portion = portion_map.get(rc)
        return (qty / portion) if portion and portion > 0 else qty

    total_gl = sum(gl_map.get(rc, 0.0) * _proportion(rc) for rc in codes)
    return total_gl, slot_rows


def _best_qty_combo(
    gl_per_recipe: list[float],
    target_gl: float,
    fixed_gl: float,
) -> list[float] | None:
    """
    Enumerate all combinations of VALID_QUANTITIES for each recipe.
    Return the quantity list whose (fixed_gl + combo_gl) is closest to target_gl
    and falls within the ±_GL_TOLERANCE band, or None if no valid combo exists.
    """
    tolerance = max(_GL_FLOOR, target_gl * _GL_TOLERANCE)
    lo = target_gl - tolerance
    hi = target_gl + tolerance

    best_combo: list[float] | None = None
    best_delta = float("inf")

    for qtys in itertools.product(VALID_QUANTITIES, repeat=len(gl_per_recipe)):
        combo_gl = sum(g * q for g, q in zip(gl_per_recipe, qtys))
        total_gl = fixed_gl + combo_gl
        if lo <= total_gl <= hi:
            delta = abs(total_gl - target_gl)
            if delta < best_delta:
                best_delta = delta
                best_combo = list(qtys)

    return best_combo


_SUGGESTION_QUANTITIES: list[float] = [0.5, 1.0, 1.5, 2.0, 2.5]


def _resolve_original_gl(sb, recipe_code: str, quantity: float) -> tuple[Optional[float], Optional[str]]:
    """
    Fetch recipe_code's Recipe_Category and compute its GL at `quantity`.

    `quantity` is the recipe's CURRENT ABSOLUTE quantity (same convention as
    Food_Qty elsewhere, e.g. "10" for 10 almonds) — converted to a proportion
    via RecipeTagging.Portion before scaling the full-portion GL, same fix
    applied in request_on_demand_replacement / _fetch_slot_gl.

    Returns (original_gl, subcat) — both None if the recipe or its
    subcategory couldn't be resolved.
    """
    rc = str(recipe_code).strip()
    target_resp = (
        sb.table("Recipe")
        .select("Recipe_Code, Recipe_Category, Carbohydrate_g, TotalDietaryFibre_FIBTG_g")
        .eq("Recipe_Code", rc)
        .execute()
    )
    if not target_resp.data:
        return None, None

    row0 = target_resp.data[0]
    subcat = row0.get("Recipe_Category", "")
    if not subcat:
        return None, None

    base_gl_original = _compute_gl_map(sb, [row0]).get(rc, 0.0)
    original_portion = _fetch_portion_map(sb, [rc]).get(rc)
    original_proportion = (quantity / original_portion) if original_portion and original_portion > 0 else quantity
    return base_gl_original * original_proportion, subcat


def _rank_candidates(sb, candidates: list[dict], original_gl: float) -> list[RecipeWithQty]:
    """
    Given a pool of Recipe rows and a target original_gl, score each candidate
    at whichever of _SUGGESTION_QUANTITIES (as a proportion of its own full
    portion) lands its GL closest to original_gl — so a candidate isn't
    penalised just because 1 of its own servings has very different carbs
    than 1 of the original's. Ranks by that gap, returns the top 3 with
    quantity expressed as an absolute amount (via RecipeTagging.Portion).
    """
    if not candidates:
        return []

    cand_codes = [row["Recipe_Code"] for row in candidates]

    # Pick up Description (the recipe's real portion unit, e.g. "2 pieces", "1 cup"
    # — same column services/recall.py uses) and Portion (to convert the chosen
    # proportion back into an absolute quantity) in one batch.
    tag_resp = (
        sb.table("RecipeTagging")
        .select("Recipe_Code, Description, Portion")
        .in_("Recipe_Code", cand_codes)
        .execute()
    )
    desc_map = {
        row["Recipe_Code"]: str(row["Description"]).strip()
        for row in (tag_resp.data or [])
        if row.get("Description") and str(row["Description"]).strip().lower() not in ("nan", "none", "")
    }
    cand_portion_map = {
        row["Recipe_Code"]: float(row["Portion"])
        for row in (tag_resp.data or [])
        if row.get("Portion") is not None
    }

    gl_map = _compute_gl_map(sb, candidates)

    scored: list[dict] = []
    for row in candidates:
        code = str(row["Recipe_Code"])
        base_gl = gl_map.get(code, 0.0)

        best_q = _SUGGESTION_QUANTITIES[0]
        best_gap = float("inf")
        for q in _SUGGESTION_QUANTITIES:
            gap = abs(base_gl * q - original_gl)
            if gap < best_gap:
                best_gap = gap
                best_q = q

        portion = cand_portion_map.get(code)
        abs_quantity = round(best_q * portion, 1) if portion else best_q

        scored.append({
            "recipe_code": code,
            "recipe_name": row.get("Recipe_Name") or "",
            "quantity": abs_quantity,
            "unit": desc_map.get(code, "serving"),
            "gl": round(base_gl * best_q, 2),
            "_gap": best_gap,
        })

    scored.sort(key=lambda s: s["_gap"])

    return [
        RecipeWithQty(
            recipe_code=s["recipe_code"],
            recipe_name=s["recipe_name"],
            quantity=s["quantity"],
            unit=s["unit"],
            gl=s["gl"],
        )
        for s in scored[:3]
    ]


def _rank_alternatives_for_recipe(
    sb, recipe_code: str, quantity: float, eligible_codes: set[str]
) -> tuple[Optional[float], Optional[str], list[RecipeWithQty]]:
    """
    "Same_category" group: up to 3 alternatives sharing the same
    Recipe_Category as recipe_code, ranked via _rank_candidates.

    Matching is by Recipe_Category only — no meal-slot tag filter — since that
    tag is inconsistently populated in RecipeTagging (e.g. some egg dishes are
    tagged for no slot at all) and would otherwise hide valid same-subcategory
    swaps.

    Candidates are restricted to eligible_codes (ADAM-approved, matches the
    user's dietary preference, not disliked/allergenic — see
    _fetch_eligible_codes) so suggestions stay within the same pool the plan
    itself was built from.

    Returns (original_gl, subcat, alternatives) — original_gl/subcat are None
    if the recipe or its subcategory couldn't be resolved.
    """
    rc = str(recipe_code).strip()
    original_gl, subcat = _resolve_original_gl(sb, rc, quantity)
    if original_gl is None:
        return None, None, []

    candidate_resp = (
        sb.table("Recipe")
        .select("Recipe_Code, Recipe_Name, Recipe_Category, Carbohydrate_g, TotalDietaryFibre_FIBTG_g")
        .eq("Recipe_Category", subcat)
        .neq("Recipe_Code", rc)
        .in_("Recipe_Code", list(eligible_codes))
        .limit(20)
        .execute()
    )
    candidates = candidate_resp.data or []
    return original_gl, subcat, _rank_candidates(sb, candidates, original_gl)


def _split_codes(value) -> list[str]:
    return [c.strip() for c in str(value or "").split(",") if c.strip()]


def _find_column_role(mapping_rows: list[dict], subcat: str) -> Optional[str]:
    """Which column of Main1_Main2_Mapping Subcategory `subcat` naturally
    belongs to: an exact Main1_Code match takes priority (that's its own
    dedicated row), else whichever of Main2_Code/Main3_Code/Optional lists it
    under."""
    for row in mapping_rows:
        if str(row.get("Main1_Code") or "").strip() == subcat:
            return "Main1_Code"
    for col in ("Main2_Code", "Main3_Code", "Optional"):
        for row in mapping_rows:
            if subcat in _split_codes(row.get(col)):
                return col
    return None


def _fetch_companion_subcategories(
    sb, user_id: str, date: str, meal_slot: MealSlot, exclude_recipe_code: str
) -> set[str]:
    """Recipe_Category of every OTHER recipe already planned in this
    (user_id, date, meal_slot) — what's already on the plate alongside the
    recipe being replaced."""
    timings = SLOT_TO_TIMINGS[meal_slot]
    rows = (
        sb.table("Recommendation")
        .select("Food_Name_desc")
        .eq("user_id", user_id)
        .eq("Date", date)
        .eq("Timings", timings)
        .execute()
        .data
    ) or []
    codes = {
        str(r["Food_Name_desc"]) for r in rows
        if r.get("Food_Name_desc") and str(r["Food_Name_desc"]) != str(exclude_recipe_code)
    }
    if not codes:
        return set()
    recipe_rows = (
        sb.table("Recipe").select("Recipe_Code, Recipe_Category").in_("Recipe_Code", list(codes)).execute().data
    ) or []
    return {str(r["Recipe_Category"]).strip() for r in recipe_rows if r.get("Recipe_Category")}


def _optional_companions_for_target(sb, mapping_rows: list[dict], target_subcat: str) -> set[str]:
    """
    Subcategories that are merely OPTIONAL accompaniments to target_subcat
    itself, per every row target_subcat appears in (as Main1_Code, or inside
    Main2_Code/Main3_Code/Optional). E.g. Black Coffee is Optional for Dosa's
    own row — so even though Coffee is genuinely on the plate, it isn't a real
    signal of what this meal is themed around and shouldn't drive the search.
    """
    result: set[str] = set()
    for row in mapping_rows:
        m1 = str(row.get("Main1_Code") or "").strip()
        row_all = (
            {m1} | set(_split_codes(row.get("Main2_Code")))
            | set(_split_codes(row.get("Main3_Code"))) | set(_split_codes(row.get("Optional")))
        )
        if target_subcat in row_all:
            result.update(_split_codes(row.get("Optional")))
    result.discard(target_subcat)
    return result


def _new_mapping_subcategories(sb, target_subcat: str, companion_subcats: set[str]) -> set[str]:
    """
    Subcategories that pair with the SAME companions target_subcat's own meal
    already has, restricted to target_subcat's own column-role (e.g. Dosa is
    a Main1_Code-type dish, so only other Main1_Code values are suggested —
    not Main3/Optional accompaniment types like chutney or buttermilk).

    Companions that are merely OPTIONAL accompaniments to target_subcat itself
    (see _optional_companions_for_target) are dropped before matching — e.g.
    Black Coffee being on the plate alongside Dosa shouldn't pull in "pairs
    with coffee" categories like Sandwich, since Coffee isn't a real signal of
    what the Dosa meal is themed around.

    A row qualifies if ANY remaining companion subcategory appears in
    Main1_Code, Main2_Code, or Main3_Code (union across companions, not
    requiring all of them at once). Optional is excluded from row-matching —
    it's a loose "goes with almost anything" bucket, so a companion only found
    there isn't a real pairing signal either.
    """
    mapping_rows = sb.table("Main1_Main2_Mapping Subcategory").select("*").execute().data or []
    role = _find_column_role(mapping_rows, target_subcat)
    if role is None or not companion_subcats:
        return set()

    optional_for_target = _optional_companions_for_target(sb, mapping_rows, target_subcat)
    effective_companions = companion_subcats - optional_for_target
    if not effective_companions:
        return set()

    result: set[str] = set()
    for row in mapping_rows:
        m1 = str(row.get("Main1_Code") or "").strip()
        cols = {
            "Main1_Code": [m1] if m1 else [],
            "Main2_Code": _split_codes(row.get("Main2_Code")),
            "Main3_Code": _split_codes(row.get("Main3_Code")),
            "Optional": _split_codes(row.get("Optional")),
        }
        row_match_codes = set(cols["Main1_Code"]) | set(cols["Main2_Code"]) | set(cols["Main3_Code"])
        if row_match_codes & effective_companions:
            result.update(cols[role])

    result.discard(target_subcat)
    return result


def _rank_new_mapping_for_recipe(
    sb, recipe_code: str, original_gl: float, target_subcat: str, user_id: str, date: str, meal_slot: MealSlot,
    eligible_codes: set[str],
) -> list[RecipeWithQty]:
    """
    "New_mapping" group: up to 3 alternatives from subcategories that pair
    with whatever else is already planned in this meal (via
    Main1_Main2_Mapping Subcategory), ranked the same way as Same_category.

    Candidates are restricted to eligible_codes (ADAM-approved, matches the
    user's dietary preference, not disliked/allergenic — see
    _fetch_eligible_codes) so suggestions stay within the same pool the plan
    itself was built from.
    """
    rc = str(recipe_code).strip()
    companion_subcats = _fetch_companion_subcategories(sb, user_id, date, meal_slot, rc)
    if not companion_subcats:
        return []

    candidate_subcats = _new_mapping_subcategories(sb, target_subcat, companion_subcats)
    if not candidate_subcats:
        return []

    candidate_resp = (
        sb.table("Recipe")
        .select("Recipe_Code, Recipe_Name, Recipe_Category, Carbohydrate_g, TotalDietaryFibre_FIBTG_g")
        .in_("Recipe_Category", list(candidate_subcats))
        .neq("Recipe_Code", rc)
        .in_("Recipe_Code", list(eligible_codes))
        .limit(20)
        .execute()
    )
    candidates = candidate_resp.data or []
    return _rank_candidates(sb, candidates, original_gl)


def _fetch_current_quantities(
    sb, user_id: str, date: str, meal_slot: MealSlot, recipe_codes: list[str]
) -> dict[str, float]:
    """Look up each recipe's actual currently-planned Food_Qty from
    Recommendation for this user/date/slot — the real "original quantity" a
    replacement should be ranked against, rather than a guessed default."""
    if not recipe_codes:
        return {}
    timings = SLOT_TO_TIMINGS[meal_slot]
    rows = (
        sb.table("Recommendation")
        .select("Food_Name_desc, Food_Qty")
        .eq("user_id", user_id)
        .eq("Date", date)
        .eq("Timings", timings)
        .in_("Food_Name_desc", recipe_codes)
        .execute()
        .data
    ) or []
    result: dict[str, float] = {}
    for r in rows:
        code = r.get("Food_Name_desc")
        qty = r.get("Food_Qty")
        if not code or qty is None:
            continue
        try:
            result[str(code)] = float(qty)
        except (TypeError, ValueError):
            continue
    return result


def get_preapproved_replacements(
    date: str,
    day: int,
    meal_slot: MealSlot,
    recipe_codes: List[str],
    user_id: str,
    recipe_quantities: List[float] | None = None,
) -> ReplacementsResponse:
    """
    For each recipe in the combination, finds two groups of alternatives:

    - same_category: up to 3 alternatives sharing the recipe's own
      Recipe_Category (_rank_alternatives_for_recipe).
    - new_mapping: up to 3 alternatives from subcategories that pair with
      whatever else is already planned in this meal, via
      Main1_Main2_Mapping Subcategory (_rank_new_mapping_for_recipe) — e.g.
      replacing Dosa when Sambar is also planned surfaces Idli, since both
      pair with Sambar.

    Both groups are transposed into up to 3 alternate combinations each (one
    pick per position) — same shape/logic as before, just run twice against
    different candidate pools.

    recipe_codes may contain a single recipe (a single-dish swap) or several
    (a whole-slot combination) — the ranking and quantity logic is identical
    either way, applied independently per recipe.

    recipe_quantities are each recipe's current ABSOLUTE quantity (same
    convention as Food_Qty, e.g. "10" for 10 almonds). Any recipe missing an
    explicit value here (including when recipe_quantities is omitted
    entirely, e.g. the Flutter app currently never sends it) has its actual
    planned quantity looked up from Recommendation instead of guessing —
    only falls back to 1.0 if that lookup also finds nothing (e.g. the
    recipe isn't actually in the plan for this date/slot).
    """
    sb = get_supabase()

    quantities: list[Optional[float]] = list(recipe_quantities or [])
    while len(quantities) < len(recipe_codes):
        quantities.append(None)

    missing_codes = [rc for rc, q in zip(recipe_codes, quantities) if q is None]
    # Skip the Recommendation lookup entirely when every recipe already has an
    # explicit quantity — no need to touch the DB for something we already have.
    plan_qty_map = _fetch_current_quantities(sb, user_id, date, meal_slot, missing_codes) if missing_codes else {}

    resolved_quantities: list[float] = []
    for rc, q in zip(recipe_codes, quantities):
        if q is not None:
            resolved_quantities.append(q)
        elif rc in plan_qty_map:
            resolved_quantities.append(plan_qty_map[rc])
        else:
            logger.warning(
                "get_preapproved_replacements: no planned quantity found for %s on %s/%s — defaulting to 1.0",
                rc, date, meal_slot,
            )
            resolved_quantities.append(1.0)

    eligible_codes = _fetch_eligible_codes(sb, user_id)

    per_recipe_same_category: list[list[RecipeWithQty]] = []
    per_recipe_new_mapping: list[list[RecipeWithQty]] = []
    total_original_gl = 0.0
    any_valid = False

    for rc, qty in zip(recipe_codes, resolved_quantities):
        original_gl, subcat, same_cat_alts = _rank_alternatives_for_recipe(sb, rc, qty, eligible_codes)
        if original_gl is None:
            continue
        any_valid = True
        total_original_gl += original_gl
        per_recipe_same_category.append(same_cat_alts)

        new_mapping_alts = _rank_new_mapping_for_recipe(
            sb, rc, original_gl, subcat, user_id, date, meal_slot, eligible_codes
        )
        per_recipe_new_mapping.append(new_mapping_alts)

    def _transpose(per_recipe: list[list[RecipeWithQty]]) -> list[list[RecipeWithQty]]:
        result: list[list[RecipeWithQty]] = []
        for i in range(3):
            combo = [alts[i] for alts in per_recipe if i < len(alts)]
            if combo:
                result.append(combo)
        return result

    return ReplacementsResponse(
        date=date,
        day=day,
        meal_slot=meal_slot,
        original_gl=round(total_original_gl, 2) if any_valid else None,
        same_category=_transpose(per_recipe_same_category),
        new_mapping=_transpose(per_recipe_new_mapping),
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

    recipe_codes / original_recipe_codes may each be a single code (swapping one
    dish) or several (swapping a whole combination) — the GL target and quantity
    search are identical either way.
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

    # Pick up Description/Portion/"Portion weight (g)" here (the recipe's real portion
    # unit e.g. "2 pieces", plus what's needed to convert the chosen proportion into an
    # absolute Food_Qty and a Recipe_weight_optimal_g — same columns services/recall.py
    # and plan generation use).
    # No meal-slot tag check — that tag is inconsistently populated in RecipeTagging
    # (e.g. some egg dishes are tagged for no slot at all) and would otherwise reject
    # valid same-subcategory swaps.
    tag_resp = (
        sb.table("RecipeTagging")
        .select("Recipe_Code, Description, Portion, \"Portion weight (g)\"")
        .in_("Recipe_Code", recipe_codes)
        .execute()
    )
    desc_map = {
        row["Recipe_Code"]: str(row["Description"]).strip()
        for row in (tag_resp.data or [])
        if row.get("Description") and str(row["Description"]).strip().lower() not in ("nan", "none", "")
    }
    portion_map = {
        row["Recipe_Code"]: float(row["Portion"])
        for row in (tag_resp.data or [])
        if row.get("Portion") is not None
    }
    portion_weight_map = {
        row["Recipe_Code"]: row.get("Portion weight (g)")
        for row in (tag_resp.data or [])
    }

    # Fetch current slot rows for plan metadata (plan_id, WeekNo etc.) and original recipes' GL
    original_slot_total_gl, all_slot_rows = _fetch_slot_gl(sb, user_id, date, meal_slot)

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
        # Food_Qty is an absolute quantity (e.g. "4.2 cups") — divide by the
        # original recipe's Portion to recover the proportion orig_gl_map's
        # full-portion GL needs to be scaled by (same fix as _fetch_slot_gl).
        orig_portion_map = _fetch_portion_map(sb, original_codes_in_plan)

        def _orig_proportion(rc: str) -> float:
            qty = orig_qty_map.get(rc, 1.0)
            portion = orig_portion_map.get(rc)
            return (qty / portion) if portion and portion > 0 else qty

        target_gl = sum(orig_gl_map.get(rc, 0.0) * _orig_proportion(rc) for rc in original_codes_in_plan)

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
                unit=desc_map.get(rc, "serving"),
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
                    # item.quantity is a proportion (0.5/1/1.5/2 of a full portion);
                    # store the absolute quantity in the recipe's own portion unit
                    # (e.g. "4.2 cups"), same convention write_recommendations uses
                    # for plan-generated rows, so Food_Qty means the same thing
                    # everywhere it's read (_fetch_slot_gl, KPI planned-GL trend, etc.)
                    "Food_Qty": (
                        round(item.quantity * portion_map[item.recipe_code], 1)
                        if item.recipe_code in portion_map
                        else item.quantity
                    ),
                    "Energy_kcal": energy_by_code.get(item.recipe_code),
                }
                for item in combination
            ]
        ).execute()
    except Exception as exc:
        logger.warning("Could not update Recommendation for on-demand replacement: %s", exc)

    # Keep FinalSummary in sync (GET /plan/daily reads GL and Recipe_weight_optimal_g
    # from there) — RecommendationsBackup is intentionally left untouched, it's an
    # immutable snapshot of the original plan and stays that way.
    try:
        if existing_plan_id:
            # Drop stale rows for the recipes being replaced
            sb.table("FinalSummary").delete().eq("user_id", user_id).eq(
                "plan_id", existing_plan_id
            ).eq("Date", date).eq("Meal_Time", timings).in_(
                "Recipe_Code", list(replaced_set)
            ).execute()

            # item.quantity IS the proportion here (same convention _compute_gl_map
            # uses — GL = base_gl * qty, no separate division by Portion), so it
            # plays the same role as "Optimal proportion"/Serving in plan generation.
            # portion_weight_map was already fetched above (alongside desc_map/portion_map).
            sb.table("FinalSummary").insert(
                [
                    {
                        "plan_id": existing_plan_id,
                        "user_id": user_id,
                        "Date": date,
                        "Meal_Time": timings,
                        "Recipe_Code": item.recipe_code,
                        "Recipe_Name": item.recipe_name,
                        "Optimal_proportion": item.quantity,
                        "Recipe_weight_optimal_g": (
                            round(float(portion_weight_map[item.recipe_code]) * item.quantity, 2)
                            if portion_weight_map.get(item.recipe_code) is not None
                            else None
                        ),
                        "Energy_ENERC_Kcal": energy_by_code.get(item.recipe_code),
                        "GL": item.gl,
                    }
                    for item in combination
                ]
            ).execute()

            # Recompute this slot's total GL (untouched recipes' contribution +
            # the new combination's) and sync it onto every row in the slot, so
            # Meal_GL stays correct regardless of which row a reader picks first.
            new_meal_gl = round(
                (original_slot_total_gl - target_gl) + sum(item.gl or 0.0 for item in combination),
                2,
            )
            sb.table("FinalSummary").update({"Meal_GL": new_meal_gl}).eq(
                "user_id", user_id
            ).eq("plan_id", existing_plan_id).eq("Date", date).eq(
                "Meal_Time", timings
            ).execute()
    except Exception as exc:
        logger.warning("Could not update FinalSummary for on-demand replacement: %s", exc)

    return OnDemandReplacementResponse(possible=True, combination=combination)
