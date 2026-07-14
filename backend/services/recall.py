import json
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


def _base_gl_map(sb, recipe_codes: List[str]) -> dict:
    """Base Glycemic Load (per one full portion) for each recipe code.

    GL = GI_Avg * (Carbohydrate_g - Fibre_g) / 100 — same net-of-fibre formula
    Functions_Base.build_recipe_master() uses to seed the LP optimizer's GL
    column (see services/lp_optimizer.py), so recall GL stays comparable to
    the planned GL. GI_Avg is looked up by Recipe_Category against
    SubCategory_foods_GI_GL, same join build_recipe_master() does.
    """
    if not recipe_codes:
        return {}
    recipes = (
        sb.table("Recipe")
        .select("Recipe_Code, Carbohydrate_g, TotalDietaryFibre_FIBTG_g, Recipe_Category")
        .in_("Recipe_Code", recipe_codes)
        .execute()
        .data
    ) or []

    categories = list({r["Recipe_Category"] for r in recipes if r.get("Recipe_Category")})
    gi_map: dict = {}
    if categories:
        gi_rows = (
            sb.table("SubCategory_foods_GI_GL").select("Code, GI_Avg").in_("Code", categories).execute().data
        ) or []
        for g in gi_rows:
            try:
                gi_map[g["Code"]] = float(g["GI_Avg"])
            except (TypeError, ValueError):
                continue

    base_gl: dict = {}
    for r in recipes:
        gi = gi_map.get(r.get("Recipe_Category"))
        if gi is None:
            continue
        try:
            carbs = float(r.get("Carbohydrate_g") or 0)
            fiber = float(r.get("TotalDietaryFibre_FIBTG_g") or 0)
        except (TypeError, ValueError):
            continue
        base_gl[r["Recipe_Code"]] = gi * max(carbs - fiber, 0.0) / 100.0
    return base_gl


def _portion_map(sb, recipe_codes: List[str]) -> dict:
    if not recipe_codes:
        return {}
    tag_rows = (
        sb.table("RecipeTagging").select("Recipe_Code, Portion").in_("Recipe_Code", recipe_codes).execute().data
    ) or []
    return {t["Recipe_Code"]: t.get("Portion") for t in tag_rows if t.get("Recipe_Code")}


def _gl_for_quantity(base_gl: Optional[float], portion, food_qty) -> Optional[float]:
    if base_gl is None or food_qty is None:
        return None
    try:
        entered_qty = float(food_qty)
        base_portion = float(portion)
        prop = (entered_qty / base_portion) if base_portion > 0 else 1.0
    except (TypeError, ValueError):
        prop = 1.0
    return round(base_gl * prop, 2)


def compute_gl_for_quantity(recipe_code: Optional[str], food_qty) -> Optional[float]:
    """Recompute GL for a recipe code + entered quantity — same pattern as
    compute_energy_for_quantity, used when Food_Qty is edited after the fact."""
    if not recipe_code or food_qty is None:
        return None
    sb = get_supabase()
    base_gl = _base_gl_map(sb, [recipe_code]).get(recipe_code)
    portion = _portion_map(sb, [recipe_code]).get(recipe_code)
    return _gl_for_quantity(base_gl, portion, food_qty)


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

        planned_codes = [item.get("Food_Name_desc") for item in planned if item.get("Food_Name_desc")]
        base_gl_map = _base_gl_map(sb, planned_codes)
        portion_map = _portion_map(sb, planned_codes)

        for item in planned:
            recall_id = str(uuid.uuid4())
            code = item.get("Food_Name_desc")
            food_qty = item.get("Food_Qty")
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
                "Food_Name_desc": code,
                "Food_Qty": food_qty,
                "R_desc": item.get("R_desc"),
                "Energy_Kcal": int(round(float(item["Energy_kcal"]))) if item.get("Energy_kcal") is not None else None,
                "GL": _gl_for_quantity(base_gl_map.get(code), portion_map.get(code), food_qty),
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
            base_gl_map = _base_gl_map(sb, codes_to_log)

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
                    row["GL"] = _gl_for_quantity(base_gl_map.get(code), tag_info.get("Portion"), qty)
                sb.table("DietRecall").insert(row).execute()
                recall_ids.append(recall_id)

    return recall_ids


def build_diet_recall_food_rows(confirmed_foods: List[dict]) -> List[dict]:
    """Compute DietRecall field values (Food_Name, Food_Name_desc, R_desc, Food_Qty,
    Energy_Kcal, GL) for a list of {"recipe_code", "quantity", "unit"} entries —
    same Recipe/RecipeTagging/GL lookups log_recall()'s "changed" path uses.

    unit == "srv" means quantity is already the eaten fraction (servings); any
    other unit is treated as a raw amount in the recipe's own portion unit (the
    log_recall() convention), converted to a fraction via RecipeTagging.Portion.
    Entries missing a recipe_code are skipped.
    """
    sb = get_supabase()
    codes = [f["recipe_code"] for f in confirmed_foods if f.get("recipe_code")]
    if not codes:
        return []

    recipe_resp = sb.table("Recipe").select("Recipe_Code, Recipe_Name, Energy_ENERC_KJ").in_("Recipe_Code", codes).execute()
    recipe_map = {r["Recipe_Code"]: r for r in (recipe_resp.data or [])}

    tag_resp = sb.table("RecipeTagging").select("Recipe_Code, Description, Portion").in_("Recipe_Code", codes).execute()
    tag_map = {t["Recipe_Code"]: t for t in (tag_resp.data or []) if t.get("Recipe_Code")}

    base_gl_map = _base_gl_map(sb, codes)

    rows = []
    for f in confirmed_foods:
        code = f.get("recipe_code")
        if not code:
            continue
        qty = f.get("quantity")
        unit = str(f.get("unit") or "").strip().lower()
        tag_info = tag_map.get(code, {})
        recipe = recipe_map.get(code)
        portion = tag_info.get("Portion")

        try:
            if unit == "srv" and qty is not None:
                prop = float(qty)
                food_qty = round(prop * float(portion), 1) if portion else None
            elif qty is not None:
                food_qty = float(qty)
                base_portion = float(portion) if portion else None
                prop = (food_qty / base_portion) if base_portion else 1.0
            else:
                food_qty, prop = None, 1.0
        except (TypeError, ValueError):
            food_qty, prop = None, 1.0

        row: dict = {
            "Food_Name": (recipe.get("Recipe_Name") if recipe else None) or code,
            "Food_Name_desc": code,
        }
        desc = tag_info.get("Description")
        if desc and str(desc).strip().lower() not in ("nan", "none", ""):
            row["R_desc"] = str(desc).strip()
        if recipe and recipe.get("Energy_ENERC_KJ"):
            row["Energy_Kcal"] = int(round(float(recipe["Energy_ENERC_KJ"]) / 4.184 * prop))
        if food_qty is not None:
            row["Food_Qty"] = food_qty
        base_gl = base_gl_map.get(code)
        if base_gl is not None:
            row["GL"] = round(base_gl * prop, 2)
        rows.append(row)
    return rows


def _parse_structured_ai(raw: Optional[str]) -> Optional[dict]:
    """Parse a MealImageReview AI-result column into its structured {"foods": [...]}
    dict, or None if it's a sentinel, unparseable, or the "analyse" action's
    free-form text (no "foods" list)."""
    if not raw or raw in ("__processing__", "__failed__"):
        return None
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(parsed, dict) or not isinstance(parsed.get("foods"), list):
        return None
    return parsed


def compute_consumption(tracked_foods_by_ai: Optional[str], tracked_foods_by_ai_post: Optional[str]) -> Optional[dict]:
    """Match dishes between the pre-meal and post-meal structured AI results by
    recipe_code and compute how much of each was actually eaten.

    Returns None if either side isn't a ready, structured result (still
    processing, failed, missing, or unparseable) — callers treat that as "not
    ready to check consumption yet".

    Otherwise returns {"foods": [...], "flags": [...]} — pre's food list, each
    entry carrying its original match/quantity plus a "consumption" block
    ({"pre_quantity_g", "post_quantity_g", "consumed_g"}) wherever a recipe_code
    + quantity was available. A dish present in pre but absent from post is
    treated as fully eaten. Dishes seen only in post are noted in "flags", not
    merged in as foods (there's nothing to subtract from).
    """
    pre = _parse_structured_ai(tracked_foods_by_ai)
    post = _parse_structured_ai(tracked_foods_by_ai_post)
    if pre is None or post is None:
        return None

    post_by_code: dict[str, list[float]] = {}
    for fr in post.get("foods", []):
        matched = (fr.get("match") or {}).get("matched") or {}
        code = matched.get("recipe_code")
        quantity = fr.get("quantity") or {}
        qty_g = quantity.get("quantity_g")
        if code and qty_g is not None:
            post_by_code.setdefault(code, []).append(float(qty_g))

    merged_foods = []
    for fr in pre.get("foods", []):
        entry = dict(fr)
        matched = (fr.get("match") or {}).get("matched") or {}
        code = matched.get("recipe_code")
        quantity = fr.get("quantity") or {}
        pre_qty_g = quantity.get("quantity_g")

        if code and pre_qty_g is not None:
            pre_qty_g = float(pre_qty_g)
            bucket = post_by_code.get(code)
            if bucket:
                post_qty_g = bucket.pop(0)
            else:
                post_qty_g = 0.0
            consumed_g = max(pre_qty_g - post_qty_g, 0.0)
            entry["consumption"] = {
                "pre_quantity_g": pre_qty_g,
                "post_quantity_g": post_qty_g,
                "consumed_g": consumed_g,
            }
        merged_foods.append(entry)

    flags = list(pre.get("flags", []))
    leftover_codes = [code for code, bucket in post_by_code.items() if bucket]
    if leftover_codes:
        flags.append(f"{len(leftover_codes)} food(s) found in post-meal image with no matching pre-meal dish")

    return {"foods": merged_foods, "flags": flags}


def resolve_confirmed_foods(
    reviewed_foods_by_human: Optional[str],
    tracked_foods_by_ai: Optional[str],
    tracked_foods_by_ai_post: Optional[str] = None,
    consumption_result: Optional[str] = None,
) -> List[dict]:
    """Resolve the coordinator-confirmed food list for a review, in priority order:

    1. reviewed_foods_by_human — structured JSON written by the coordinator's recipe
       pickers, e.g. [{"recipe_code": "A001745", "recipe_name": "Idli", "quantity": 2, "unit": "srv"}].
       Rows from before this JSON format existed are a plain display string and
       parse-fail here, so they fall through to (2).
    2. consumption_result — the stored output of the coordinator's explicit "Check
       Consumption" step (compute_consumption, run via action="check_consumption").
       Uses each food's consumption.consumed_g.
    3. Safety net: if consumption_result wasn't computed but both tracked_foods_by_ai
       and tracked_foods_by_ai_post are ready structured results, compute it on the
       fly (covers approving without clicking "Check Consumption" first).
    4. tracked_foods_by_ai alone, quantity.quantity_g — today's original fallback,
       used when there's no usable post-meal result at all.

    Returns [] if nothing structured is available.
    """
    if reviewed_foods_by_human:
        try:
            parsed = json.loads(reviewed_foods_by_human)
            if isinstance(parsed, list):
                foods = [
                    {"recipe_code": f.get("recipe_code"), "quantity": f.get("quantity"), "unit": f.get("unit")}
                    for f in parsed if isinstance(f, dict) and f.get("recipe_code")
                ]
                if foods:
                    return foods
        except (json.JSONDecodeError, TypeError):
            pass

    merged = _parse_structured_ai(consumption_result) or compute_consumption(
        tracked_foods_by_ai, tracked_foods_by_ai_post
    )
    if merged:
        foods = []
        for fr in merged.get("foods", []):
            matched = (fr.get("match") or {}).get("matched") or {}
            code = matched.get("recipe_code")
            if not code:
                continue
            consumption = fr.get("consumption")
            qty_g = consumption["consumed_g"] if consumption else (fr.get("quantity") or {}).get("quantity_g")
            foods.append({"recipe_code": code, "quantity": qty_g, "unit": "g"})
        if foods:
            return foods

    ai = _parse_structured_ai(tracked_foods_by_ai)
    if ai:
        foods = []
        for fr in ai.get("foods", []):
            matched = (fr.get("match") or {}).get("matched") or {}
            code = matched.get("recipe_code")
            if not code:
                continue
            quantity = fr.get("quantity") or {}
            foods.append({"recipe_code": code, "quantity": quantity.get("quantity_g"), "unit": "g"})
        if foods:
            return foods

    return []


def approve_review_diet_recall(diet_recall_id: str, confirmed_foods: List[dict]) -> bool:
    """Write the coordinator-confirmed foods into DietRecall. A placeholder row
    (no food data) already exists for this review from photo-upload time
    (log_recall_image) — update it with the first confirmed food, then insert
    one additional row per remaining food (a meal can be more than one dish),
    mirroring how log_recall()'s text-only path creates one row per recipe_code.
    Every written row is marked verified_by_coordinator=True.
    Returns False (no-op) if confirmed_foods resolves to nothing usable.
    """
    field_rows = build_diet_recall_food_rows(confirmed_foods)
    if not field_rows:
        return False

    sb = get_supabase()
    first, *rest = field_rows
    sb.table("DietRecall").update({
        **first,
        "did_eat_as_planned": False,
        "notes": "verified",
        "verified_by_coordinator": True,
    }).eq("ID", diet_recall_id).execute()

    if rest:
        base_resp = sb.table("DietRecall").select("user_id, Date, Time, plan_id, meal_slot, image_url_pre, image_url_post").eq("ID", diet_recall_id).limit(1).execute()
        base_row = base_resp.data[0] if base_resp.data else {}
        for fields in rest:
            sb.table("DietRecall").insert({
                "ID": str(uuid.uuid4()),
                "created_at": datetime.now(timezone.utc).isoformat(),
                "did_eat_as_planned": False,
                "notes": "verified",
                "verified_by_coordinator": True,
                **base_row,
                **fields,
            }).execute()

    return True


def reject_review_diet_recall(diet_recall_id: str) -> None:
    """Leave DietRecall's food fields empty on reject, but note it so the
    user/coordinator can see it needs resubmitting."""
    get_supabase().table("DietRecall").update({
        "notes": "Image review rejected — please resubmit",
    }).eq("ID", diet_recall_id).execute()


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
                .select("id, review_status")
                .eq("diet_recall_id", recall_id)
                .limit(1)
                .execute()
                .data
            )
            if existing_review:
                review_id = existing_review[0]["id"]
                sb.table("MealImageReview").update({"post_image_id": image_url_post}).eq("id", review_id).execute()
                if existing_review[0].get("review_status") == "pending":
                    _enqueue_post_identification(sb, review_id, image_url_post)
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

    # Auto-enqueue food identification when a post-meal image is present. Fully
    # independent of the pre-image job above — used later by the coordinator's
    # explicit "Check Consumption" step, never auto-merged into tracked_foods_by_ai.
    if image_url_post:
        _enqueue_post_identification(sb, review_id, image_url_post)

    return recall_id, review_id


def _enqueue_post_identification(sb, review_id: str, image_url_post: str) -> None:
    try:
        from services.food_id_worker import PROCESSING_SENTINEL, enqueue_food_id_job_post
        sb.table("MealImageReview").update(
            {"tracked_foods_by_ai_post": PROCESSING_SENTINEL}
        ).eq("id", review_id).execute()
        enqueue_food_id_job_post(review_id, image_url_post)
    except Exception:
        logger.warning("Could not enqueue post-meal food ID job for review %s", review_id)
