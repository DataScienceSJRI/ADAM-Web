import logging
from datetime import date

from core.supabase import get_supabase
from models.schemas import MealSlot, OutsideFoodDish, OutsideFoodSwapResponse, SLOT_TO_TIMINGS
from services.profile_builder import build_profile
from services.recommendation_writer import get_plan_status
from services.replacement import (
    _compute_gl_map,
    _fetch_diet_allowed_codes,
    _fetch_portion_map,
    _fetch_slot_gl,
)

logger = logging.getLogger("backend.services.outside_food")

WEEKLY_LIMIT = 5


def _current_plan_week(user_id: str) -> dict | None:
    status = get_plan_status(user_id)
    plans = status.get("plans") or []
    today_iso = date.today().isoformat()
    for plan in plans:
        if plan["start_date"] and plan["end_date"] and plan["start_date"] <= today_iso <= plan["end_date"]:
            return plan
    return plans[0] if plans else None


def _week_outside_count(sb, user_id: str, week_start_date: str) -> int:
    resp = (
        sb.table("OutsideFoodLog")
        .select("id", count="exact")
        .eq("user_id", user_id)
        .eq("week_start_date", week_start_date)
        .execute()
    )
    return resp.count or 0


def list_cuisine_types() -> list[str]:
    sb = get_supabase()
    rows = sb.table("cuisine_dishes").select("cuisine_type").execute().data or []
    return sorted({str(r["cuisine_type"]).strip() for r in rows if r.get("cuisine_type")})


def list_eligible_dishes(user_id: str, cuisine_type: str | None = None) -> list[OutsideFoodDish]:
    sb = get_supabase()

    query = sb.table("cuisine_dishes").select("recipe_code, recipe_name, cuisine_type")
    if cuisine_type:
        query = query.ilike("cuisine_type", cuisine_type.strip())
    dishes = query.execute().data or []
    if not dishes:
        return []

    codes = [str(d["recipe_code"]).strip().upper() for d in dishes]
    profile = build_profile(user_id)
    diet_type = (profile.get("diet_type") if profile else None) or ""
    diet_allowed = _fetch_diet_allowed_codes(sb, diet_type)

    tag_rows = (
        sb.table("RecipeTagging")
        .select("Recipe_Code, Description")
        .in_("Recipe_Code", codes)
        .execute()
        .data or []
    )
    unit_map = {
        row["Recipe_Code"]: str(row["Description"]).strip()
        for row in tag_rows
        if row.get("Description") and str(row["Description"]).strip().lower() not in ("nan", "none", "")
    }

    result = []
    for d in dishes:
        code = str(d["recipe_code"]).strip().upper()
        if diet_allowed is not None and code not in diet_allowed:
            continue
        result.append(OutsideFoodDish(
            recipe_code=d["recipe_code"],
            recipe_name=d["recipe_name"],
            cuisine_type=d.get("cuisine_type"),
            unit=unit_map.get(d["recipe_code"], "serving"),
        ))
    return result


def swap_to_outside_food(
    user_id: str,
    meal_date: str,
    meal_slot: MealSlot,
    recipe_code: str,
    quantity: float,
    original_recipe_codes: list[str] | None = None,
) -> OutsideFoodSwapResponse:
    sb = get_supabase()

    allowed = sb.table("cuisine_dishes").select("recipe_code, recipe_name").eq("recipe_code", recipe_code).execute().data
    if not allowed:
        return OutsideFoodSwapResponse(possible=False, reason="not_an_outside_food", week_count=0)

    profile = build_profile(user_id)
    diet_type = (profile.get("diet_type") if profile else None) or ""
    diet_allowed = _fetch_diet_allowed_codes(sb, diet_type)
    if diet_allowed is not None and recipe_code.strip().upper() not in diet_allowed:
        return OutsideFoodSwapResponse(possible=False, reason="not_diet_compatible", week_count=0)

    plan_week = _current_plan_week(user_id)
    if not plan_week:
        return OutsideFoodSwapResponse(possible=False, reason="no_active_plan", week_count=0)

    # meal_date is client-supplied -- without this check a request could
    # target a Recommendation row from a past/future week while still being
    # counted against the CURRENT week's cap below, which would be wrong on
    # both sides (swapping a date nobody asked about, miscounting the cap).
    week_start_date = plan_week["start_date"]
    week_end_date = plan_week["end_date"]
    if not week_start_date or not (week_start_date <= meal_date <= week_end_date):
        return OutsideFoodSwapResponse(possible=False, reason="not_current_week", week_count=0)

    week_count_so_far = _week_outside_count(sb, user_id, week_start_date)
    if week_count_so_far >= WEEKLY_LIMIT:
        logger.info("Outside-food swap blocked for user_id=%s: already at %d/%d this week", user_id, week_count_so_far, WEEKLY_LIMIT)
        try:
            from services.notify import notify
            notify(
                user_id=user_id,
                title="Outside-food limit reached",
                body=f"You've used all {WEEKLY_LIMIT} outside-food swaps for this week. Your plan continues as usual for the rest of the week.",
                data={"type": "outside_food_limit_reached", "week_count": week_count_so_far, "week_limit": WEEKLY_LIMIT},
            )
        except Exception:
            logger.exception("Could not notify user_id=%s of outside-food weekly limit", user_id)
        return OutsideFoodSwapResponse(possible=False, reason="weekly_limit_reached", week_count=week_count_so_far, week_limit=WEEKLY_LIMIT)

    recipe_resp = (
        sb.table("Recipe")
        .select("Recipe_Code, Recipe_Name, Recipe_Category, Carbohydrate_g, TotalDietaryFibre_FIBTG_g, Energy_ENERC_KJ")
        .eq("Recipe_Code", recipe_code)
        .execute()
    )
    recipe_rows = recipe_resp.data or []
    if not recipe_rows:
        return OutsideFoodSwapResponse(possible=False, reason="recipe_not_found", week_count=week_count_so_far)
    recipe_row = recipe_rows[0]

    tag_resp = (
        sb.table("RecipeTagging")
        .select("Recipe_Code, Description, \"Portion weight (g)\"")
        .eq("Recipe_Code", recipe_code)
        .execute()
    )
    tag_row = (tag_resp.data or [{}])[0]
    unit = str(tag_row.get("Description") or "serving").strip() or "serving"
    portion_weight = tag_row.get("Portion weight (g)")

    portion_map = _fetch_portion_map(sb, [recipe_code])
    portion = portion_map.get(recipe_code)
    proportion = (quantity / portion) if portion and portion > 0 else quantity

    gl_map = _compute_gl_map(sb, [recipe_row])
    gl = round(gl_map.get(recipe_code, 0.0) * proportion, 2)

    base_kj = float(recipe_row.get("Energy_ENERC_KJ") or 0)
    base_kcal = (base_kj / 4.184) if base_kj > 0 else 0.0
    energy_kcal = round(base_kcal * proportion, 1)

    grams = round(float(portion_weight) * proportion, 2) if portion_weight is not None else None

    # Update Recommendation the same way a normal on-demand swap does.
    timings = SLOT_TO_TIMINGS[meal_slot]
    original_slot_total_gl, all_slot_rows = _fetch_slot_gl(sb, user_id, meal_date, meal_slot)
    existing_plan_id = all_slot_rows[0].get("plan_id") if all_slot_rows else plan_week.get("plan_id")
    existing_week_no = all_slot_rows[0].get("WeekNo") if all_slot_rows else plan_week.get("week_no")
    existing_onboarding_id = all_slot_rows[0].get("onboarding_id") if all_slot_rows else plan_week.get("onboarding_id")

    existing_codes_in_slot = {str(r.get("Food_Name_desc") or "") for r in all_slot_rows if r.get("Food_Name_desc")}
    outside_codes_in_slot: set[str] = set()
    if existing_codes_in_slot:
        outside_rows = (
            sb.table("cuisine_dishes")
            .select("recipe_code")
            .in_("recipe_code", list(existing_codes_in_slot))
            .execute()
            .data or []
        )
        outside_codes_in_slot = {str(r["recipe_code"]) for r in outside_rows if r.get("recipe_code")}

    replaced_set = set(original_recipe_codes) if original_recipe_codes else (
        existing_codes_in_slot - outside_codes_in_slot
    )

    try:
        pkeys_to_delete = [
            r["Pkey"] for r in all_slot_rows
            if str(r.get("Food_Name_desc") or "") in replaced_set
        ]
        if pkeys_to_delete:
            sb.table("Recommendation").delete().in_("Pkey", pkeys_to_delete).execute()

        sb.table("Recommendation").insert({
            "user_id": user_id,
            "plan_id": existing_plan_id,
            "onboarding_id": existing_onboarding_id,
            "WeekNo": existing_week_no,
            "Date": meal_date,
            "Timings": timings,
            "Food_Name": recipe_row.get("Recipe_Name"),
            "Food_Name_desc": recipe_code,
            "Food_Qty": quantity,
            "R_desc": unit,
            "Energy_kcal": energy_kcal,
        }).execute()
    except Exception:
        logger.exception("Could not update Recommendation for outside-food swap, user_id=%s", user_id)

    try:
        if existing_plan_id:
            if replaced_set:
                sb.table("FinalSummary").delete().eq("user_id", user_id).eq(
                    "plan_id", existing_plan_id
                ).eq("Date", meal_date).eq("Meal_Time", timings).in_(
                    "Recipe_Code", list(replaced_set)
                ).execute()

            sb.table("FinalSummary").insert({
                "plan_id": existing_plan_id,
                "user_id": user_id,
                "Date": meal_date,
                "Meal_Time": timings,
                "Recipe_Code": recipe_code,
                "Recipe_Name": recipe_row.get("Recipe_Name"),
                "Optimal_proportion": proportion,
                "Recipe_weight_optimal_g": grams,
                "Energy_ENERC_Kcal": energy_kcal,
                "GL": gl,
            }).execute()

            # GL of just the recipes actually being replaced (not necessarily
            # the whole slot -- original_recipe_codes may be a partial swap
            # within a multi-dish slot), same convention
            # request_on_demand_replacement's target_gl uses.
            replaced_rows = [r for r in all_slot_rows if str(r.get("Food_Name_desc") or "") in replaced_set]
            replaced_codes = [str(r["Food_Name_desc"]) for r in replaced_rows]
            replaced_gl = 0.0
            if replaced_codes:
                replaced_recipe_rows = (
                    sb.table("Recipe")
                    .select("Recipe_Code, Recipe_Category, Carbohydrate_g, TotalDietaryFibre_FIBTG_g")
                    .in_("Recipe_Code", replaced_codes)
                    .execute()
                ).data or []
                replaced_gl_map = _compute_gl_map(sb, replaced_recipe_rows)
                replaced_portion_map = _fetch_portion_map(sb, replaced_codes)
                for r in replaced_rows:
                    rc = str(r["Food_Name_desc"])
                    qty = float(r.get("Food_Qty") or 1.0)
                    portion = replaced_portion_map.get(rc)
                    prop = (qty / portion) if portion and portion > 0 else qty
                    replaced_gl += replaced_gl_map.get(rc, 0.0) * prop

            new_meal_gl = round((original_slot_total_gl - replaced_gl) + gl, 2)
            sb.table("FinalSummary").update({"Meal_GL": new_meal_gl}).eq(
                "user_id", user_id
            ).eq("plan_id", existing_plan_id).eq("Date", meal_date).eq("Meal_Time", timings).execute()
    except Exception:
        logger.exception("Could not update FinalSummary for outside-food swap, user_id=%s", user_id)

    new_week_count = week_count_so_far + 1
    try:
        sb.table("OutsideFoodLog").insert({
            "user_id": user_id,
            "recipe_code": recipe_code,
            "recipe_name": recipe_row.get("Recipe_Name"),
            "meal_date": meal_date,
            "meal_slot": meal_slot.value,
            "plan_id": existing_plan_id,
            "week_no": existing_week_no,
            "week_start_date": week_start_date,
            "quantity": quantity,
            "unit": unit,
            "grams": grams,
            "gl": gl,
            "energy_kcal": energy_kcal,
            "week_count": new_week_count,
        }).execute()
    except Exception:
        logger.exception("Could not write OutsideFoodLog audit row for user_id=%s", user_id)

    try:
        from services.recall import log_recall
        log_recall(
            user_id=user_id,
            plan_id=existing_plan_id,
            meal_slot=meal_slot,
            date=meal_date,
            recipe_codes=[recipe_code],
            actual_quantities=[str(quantity)],
        )
    except Exception:
        logger.exception("Could not write DietRecall entry for outside-food swap, user_id=%s", user_id)

    try:
        from services.notify import notify
        notify(
            user_id=user_id,
            title="Outside food logged",
            body=f"{recipe_row.get('Recipe_Name') or recipe_code} logged for {meal_slot.value}. "
                 f"{new_week_count}/{WEEKLY_LIMIT} outside-food swaps used this week.",
            data={"type": "outside_food_logged", "week_count": new_week_count, "week_limit": WEEKLY_LIMIT},
        )
    except Exception:
        logger.exception("Could not notify user_id=%s of outside-food log", user_id)

    return OutsideFoodSwapResponse(possible=True, week_count=new_week_count, week_limit=WEEKLY_LIMIT, gl=gl, energy_kcal=energy_kcal)


def list_flagged_participants(coordinator_id: str, role: str) -> list[dict]:
    from core.supabase import fetch_all_rows

    sb = get_supabase()

    def _build_query():
        q = (
            sb.table("UserRoles").select("user_id, participant_id, display_name, coordinator_id")
            .eq("role", "participant").eq("is_active", True).ilike("participant_id", "A%")
        )
        if role == "coordinator":
            q = q.eq("coordinator_id", coordinator_id)
        return q

    active_real_participants = fetch_all_rows(_build_query)

    flagged = []
    for p in active_real_participants:
        user_id = p["user_id"]
        plan_week = _current_plan_week(user_id)
        if not plan_week:
            continue
        count = _week_outside_count(sb, user_id, plan_week["start_date"])
        if count >= WEEKLY_LIMIT:
            flagged.append({
                "user_id": user_id,
                "participant_id": p.get("participant_id"),
                "display_name": p.get("display_name"),
                "week_start_date": plan_week["start_date"],
                "week_count": count,
                "week_limit": WEEKLY_LIMIT,
            })
    return flagged
