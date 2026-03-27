import uuid
import logging
import math
import pandas as pd
from datetime import date, timedelta
from typing import Optional
from core.supabase import get_supabase

logger = logging.getLogger("backend.recommendation_writer")


def _to_float(val) -> float | None:
    """Convert value to float, returning None for NaN/None/invalid."""
    try:
        v = float(val)
        return None if math.isnan(v) or math.isinf(v) else v
    except (TypeError, ValueError):
        return None


def _to_str(val) -> str | None:
    """Convert value to stripped string, returning None for empty/nan."""
    if val is None:
        return None
    s = str(val).strip()
    return None if s.lower() in ("nan", "none", "") else s


def write_recommendations(
    user_id: str,
    weekly_menu: pd.DataFrame,
    week_no: int = 1,
    onboarding_id: str | None = None,
) -> tuple[int, str]:
    """
    Writes the new weekly menu as a new plan.
    Returns (rows_written, plan_id).
    """
    if weekly_menu.empty:
        return 0, ""

    supabase = get_supabase()
    plan_id = str(uuid.uuid4())

    recipe_codes = weekly_menu["Recipe_Code"].dropna().unique().tolist() if "Recipe_Code" in weekly_menu.columns else []
    portion_map: dict = {}
    if recipe_codes:
        try:
            tag_resp = (
                supabase.table("RecipeTagging")
                .select("Recipe_Code, Portion, Description")
                .in_("Recipe_Code", recipe_codes)
                .execute()
            )
            for t in (tag_resp.data or []):
                code = str(t.get("Recipe_Code", "")).strip()
                portion_map[code] = {
                    "portion": t.get("Portion"),
                    "desc": t.get("Description"),
                }
        except Exception:
            pass

    today = date.today()
    rows = []
    for _, row in weekly_menu.iterrows():
        day_num = int(row.get("Day", 1))
        meal_date = (today + timedelta(days=day_num - 1)).isoformat()

        energy = row.get("Energy_ENERC_Kcal")
        try:
            energy = float(energy) if energy is not None else None
        except (TypeError, ValueError):
            energy = None

        recipe_code = str(row.get("Recipe_Code", "")).strip()
        tag_info = portion_map.get(recipe_code, {})
        serving_mult = row.get("Serving")
        food_qty: float | None = None
        try:
            mult = float(serving_mult) if serving_mult is not None else None
            por_raw = tag_info.get("portion")
            por = float(por_raw) if por_raw is not None else None
            if mult is not None and por is not None and por > 0:
                food_qty = round(mult * por, 1)
            elif mult is not None:
                food_qty = round(mult, 1)
        except (TypeError, ValueError):
            food_qty = None

        desc_raw = tag_info.get("desc")
        portion_desc = str(desc_raw).strip() if desc_raw and str(desc_raw).strip().lower() not in ("nan", "none", "") else "serving"

        row_dict = {
            "user_id": user_id,
            "plan_id": plan_id,
            "WeekNo": week_no,
            "Date": meal_date,
            "Timings": str(row.get("Meal_Time", "")).strip(),
            "Food_Name": str(row.get("Recipe_Name", "")).strip() or None,
            "Food_Name_desc": str(row.get("Recipe_Code", "")).strip() or None,
            "Food_Qty": food_qty,
            "R_desc": str(portion_desc).strip() if portion_desc else None,
            "Energy_kcal": energy,
        }
        if onboarding_id:
            row_dict["onboarding_id"] = onboarding_id
        rows.append(row_dict)

    if not rows:
        return 0, ""

    batch_size = 100
    for i in range(0, len(rows), batch_size):
        resp = supabase.table("Recommendation").insert(rows[i : i + batch_size]).execute()
        try:
            # log Supabase response for debugging (non-fatal)
            logger.info(
                "Inserted %d rows to Recommendation (batch %d-%d). supabase_status=%s",
                len(rows[i : i + batch_size]),
                i,
                i + batch_size - 1,
                getattr(resp, "status_code", "unknown"),
            )
        except Exception:
            logger.exception("Failed to log supabase insert response")

    return len(rows), plan_id


def get_plan_status(user_id: str) -> dict:
    """Returns whether a plan exists and a list of all plans with their metadata."""
    supabase = get_supabase()
    resp = (
        supabase.table("Recommendation")
        .select("plan_id, onboarding_id, WeekNo, Date")
        .eq("user_id", user_id)
        .execute()
    )
    data = resp.data or []

    plans: dict[str, dict] = {}
    for r in data:
        pid = r.get("plan_id") or "unknown"
        if pid not in plans:
            plans[pid] = {"plan_id": pid, "onboarding_id": r.get("onboarding_id"), "week_no": r.get("WeekNo"), "dates": [], "row_count": 0}
        plans[pid]["row_count"] += 1
        if r.get("Date"):
            plans[pid]["dates"].append(r["Date"])

    plan_list = []
    for p in plans.values():
        dates = sorted(p["dates"])
        plan_list.append({
            "plan_id": p["plan_id"],
            "onboarding_id": p["onboarding_id"],
            "week_no": p["week_no"],
            "start_date": dates[0] if dates else None,
            "end_date": dates[-1] if dates else None,
            "row_count": p["row_count"],
        })
    plan_list.sort(key=lambda x: x["start_date"] or "", reverse=True)

    return {
        "has_plan": len(plan_list) > 0,
        "row_count": sum(p["row_count"] for p in plan_list),
        "plans": plan_list,
    }


def write_final_summary(
    user_id: str,
    plan_id: str,
    final_summary_df: pd.DataFrame,
) -> int:
    """
    Writes the formatted weekly menu summary to FinalSummary table.
    Day numbers are converted to actual dates. Internal computation
    columns (_opt_prop, _carb_g, etc.) are excluded.
    Returns rows written.
    """
    if final_summary_df is None or final_summary_df.empty:
        return 0

    supabase = get_supabase()
    today = date.today()
    rows = []

    for _, row in final_summary_df.iterrows():
        try:
            meal_date = (today + timedelta(days=int(row.get("Day", 1)) - 1)).isoformat()
        except (TypeError, ValueError):
            meal_date = None

        rows.append({
            "plan_id": plan_id,
            "user_id": user_id,
            "Date": meal_date,
            "Meal_Time": _to_str(row.get("Meal_Time")),
            "Recipe_Code": _to_str(row.get("Recipe_Code")),
            "Code_cooccurence": _to_str(row.get("Code_cooccurence")),
            "Subcategories": _to_str(row.get("Subcategories")),
            "Dish_Type": _to_str(row.get("Dish_Type")),
            "Recipe_Name": _to_str(row.get("Recipe_Name")),
            "Optimal_proportion": _to_float(row.get("Optimal proportion")),
            "Recipe_weight_original_g": _to_float(row.get("Recipe weight Original (g)")),
            "Portion_original": _to_str(row.get("Portion original")),
            "Recipe_weight_optimal_g": _to_float(row.get("Recipe weight Optimal (g)")),
            "Portion_optimal": _to_float(row.get("Portion optimal")),
            "Description_tagging": _to_str(row.get("Description_tagging")),
            "OPTIMAL_STATUS": _to_str(row.get("OPTIMAL_STATUS")),
            "Subcategory_Code": _to_str(row.get("Subcategory_Code")),
            "GI_Avg": _to_float(row.get("GI_Avg")),
            "Subcategory_Name": _to_str(row.get("Subcategory_Name")),
            "Energy_ENERC_KJ": _to_float(row.get("Energy_ENERC_KJ")),
            "Carbohydrate_g": _to_float(row.get("Carbohydrate_g")),
            "TotalDietaryFibre_FIBTG_g": _to_float(row.get("TotalDietaryFibre_FIBTG_g")),
            "Energy_ENERC_Kcal": _to_float(row.get("Energy_ENERC_Kcal")),
            "GL": _to_float(row.get("GL")),
            "Meal_GL": _to_float(row.get("Meal_GL")),
        })

    if not rows:
        return 0

    batch_size = 100
    for i in range(0, len(rows), batch_size):
        supabase.table("FinalSummary").insert(rows[i : i + batch_size]).execute()

    logger.info("Inserted %d rows to FinalSummary for plan_id=%s", len(rows), plan_id)
    return len(rows)


def write_final_nutrient_summary(
    user_id: str,
    plan_id: str,
    nutrient_summary_df: pd.DataFrame,
) -> int:
    """
    Writes the weekly nutrient achievement summary to FinalNutrientSummary table.
    Returns rows written.
    """
    if nutrient_summary_df is None or nutrient_summary_df.empty:
        return 0

    supabase = get_supabase()
    rows = [
        {
            "plan_id": plan_id,
            "user_id": user_id,
            "Nutrient": _to_str(row.get("Nutrient")),
            "Weekly_Requirement": _to_float(row.get("Weekly_Requirement")),
            "Achieved_From_Menu": _to_float(row.get("Achieved_From_Menu")),
            "Percent_Requirement_Met": _to_float(row.get("Percent_Requirement_Met")),
        }
        for _, row in nutrient_summary_df.iterrows()
    ]

    if not rows:
        return 0

    supabase.table("FinalNutrientSummary").insert(rows).execute()
    logger.info("Inserted %d rows to FinalNutrientSummary for plan_id=%s", len(rows), plan_id)
    return len(rows)
