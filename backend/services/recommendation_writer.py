import uuid
import logging
import pandas as pd
from datetime import date, timedelta
from typing import Optional
from core.supabase import get_supabase

logger = logging.getLogger("backend.recommendation_writer")


def write_recommendations(
    user_id: str,
    weekly_menu: pd.DataFrame,
    week_no: int = 1,
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

        rows.append({
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
        })

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
        .select("plan_id, WeekNo, Date")
        .eq("user_id", user_id)
        .execute()
    )
    data = resp.data or []

    plans: dict[str, dict] = {}
    for r in data:
        pid = r.get("plan_id") or "unknown"
        if pid not in plans:
            plans[pid] = {"plan_id": pid, "week_no": r.get("WeekNo"), "dates": [], "row_count": 0}
        plans[pid]["row_count"] += 1
        if r.get("Date"):
            plans[pid]["dates"].append(r["Date"])

    plan_list = []
    for p in plans.values():
        dates = sorted(p["dates"])
        plan_list.append({
            "plan_id": p["plan_id"],
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
