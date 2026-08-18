import os
from datetime import date as date_type, datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from core.supabase import get_supabase
from models.schemas import ContactParticipantRequest
from services.push import send_push
from services.recall import fetch_base_gl_map, fetch_portion_map, gl_for_quantity
from services.reminders import DEFAULT_MEAL_TIMES, IST, time_to_minutes

router = APIRouter(prefix="/status", tags=["status"])

_STATUS_TOKEN = os.getenv("DASHBOARD_SHARE_TOKEN", "")

MEAL_SLOTS = ["breakfast", "lunch", "dinner", "snacks"]
_MEAL_TIME_TO_SLOT = {"Breakfast": "breakfast", "Lunch": "lunch", "Dinner": "dinner", "Snacks": "snacks"}
_AT_RISK_DAYS = 3
_SNACK_DUE_AFTER_SLOT = "dinner"
_GL_COMPLIANCE_TOLERANCE = 0.20
_GL_COMPLIANCE_FLOOR = 1.0
_GL_COMPLIANCE_WINDOW_DAYS = 14


def _format_slot_list(slots: list[str]) -> str:
    if not slots:
        return ""
    if len(slots) == 1:
        return slots[0]
    return ", ".join(slots[:-1]) + " and " + slots[-1]


def _check_token(token: str) -> None:
    if not _STATUS_TOKEN or token != _STATUS_TOKEN:
        raise HTTPException(status_code=403, detail="Invalid or missing status dashboard token")


def _weighted_avg_gl(day_gl: dict[str, float], day_energy: dict[str, float]) -> Optional[float]:
    """Energy-weighted average of per-day GL totals: Σ(GL_day * Energy_day) /
    Σ(Energy_day) — a day the user ate more counts more toward "their typical
    GL" than a day they barely ate. Same formula as routers/kpi.py's
    _weighted_avg_gl_per_day. Falls back to a plain mean if no day has energy
    data at all."""
    if not day_gl:
        return None
    weighted_sum = sum(gl * day_energy.get(d, 0.0) for d, gl in day_gl.items())
    weight_total = sum(day_energy.values())
    if weight_total > 0:
        return round(weighted_sum / weight_total, 1)
    return round(sum(day_gl.values()) / len(day_gl), 1)


def _normalize_date(raw: str) -> Optional[str]:
    if not raw:
        return None
    parts = raw.strip().split("T")[0].split("-")
    if len(parts) != 3:
        return None
    try:
        y, m, d = int(parts[0]), int(parts[1]), int(parts[2])
        return f"{y:04d}-{m:02d}-{d:02d}"
    except ValueError:
        return None


def _lookup_ids(user_ids: list[str]) -> list[str]:
    ids: list[str] = []
    for uid in user_ids:
        ids.append(uid)
        ids.append(f"{uid}@adam.participant")
    return ids


def _earliest_dates(sb, table: str, lookup_ids: list[str]) -> dict[str, str]:
    rows = (
        sb.table(table)
        .select("user_id, Date")
        .in_("user_id", lookup_ids)
        .limit(20000)
        .execute()
        .data
    ) or []
    earliest: dict[str, str] = {}
    for r in rows:
        uid = str(r.get("user_id", "")).split("@")[0]
        d = _normalize_date(r.get("Date") or "")
        if not d:
            continue
        if uid not in earliest or d < earliest[uid]:
            earliest[uid] = d
    return earliest


def _bulk_gl_compliant_pct(sb, lookup_ids: list[str], today: date_type) -> dict[str, Optional[float]]:
    window_end = today - timedelta(days=1)
    window_start = str(window_end - timedelta(days=_GL_COMPLIANCE_WINDOW_DAYS - 1))
    window_end_str = str(window_end)

    planned_rows = (
        sb.table("RecommendationsBackup")
        .select("user_id, Date, Timings, Food_Name_desc, Food_Qty")
        .in_("user_id", lookup_ids)
        .gte("Date", window_start)
        .lte("Date", window_end_str)
        .limit(20000)
        .execute()
        .data
    ) or []
    if not planned_rows:
        return {}

    recall_rows = (
        sb.table("DietRecall")
        .select("user_id, Date, meal_slot, GL")
        .in_("user_id", lookup_ids)
        .gte("Date", window_start)
        .lte("Date", window_end_str)
        .limit(20000)
        .execute()
        .data
    ) or []

    actual_gl: dict[tuple[str, str, str], float] = {}
    for r in recall_rows:
        uid = str(r.get("user_id", "")).split("@")[0]
        d = _normalize_date(r.get("Date") or "")
        slot = str(r.get("meal_slot", "")).strip().lower()
        gl = r.get("GL")
        if not d or slot not in MEAL_SLOTS or gl is None:
            continue
        key = (uid, d, slot)
        actual_gl[key] = actual_gl.get(key, 0.0) + float(gl)

    codes = list({str(row["Food_Name_desc"]).strip() for row in planned_rows if row.get("Food_Name_desc")})
    base_gl_map = fetch_base_gl_map(sb, codes)
    portion_map = fetch_portion_map(sb, codes)

    planned_occasions: dict[str, set] = {}
    planned_gl: dict[tuple[str, str, str], float] = {}
    for row in planned_rows:
        uid = str(row.get("user_id", "")).split("@")[0]
        d = _normalize_date(row.get("Date") or "")
        code = row.get("Food_Name_desc")
        if not d or not code:
            continue
        slot = _MEAL_TIME_TO_SLOT.get(str(row.get("Timings") or "").strip())
        if slot is None:
            continue
        planned_occasions.setdefault(uid, set()).add((d, slot))
        code_norm = str(code).strip()
        gl = gl_for_quantity(base_gl_map.get(code_norm), portion_map.get(code_norm), row.get("Food_Qty"))
        if gl is not None:
            key = (uid, d, slot)
            planned_gl[key] = planned_gl.get(key, 0.0) + gl

    pct_by_uid: dict[str, Optional[float]] = {}
    for uid, occasions in planned_occasions.items():
        compliant = 0
        for d, slot in occasions:
            actual = actual_gl.get((uid, d, slot))
            if actual is None:
                continue
            planned = planned_gl.get((uid, d, slot), 0.0)
            if actual <= planned:
                compliant += 1
                continue
            tolerance = max(_GL_COMPLIANCE_FLOOR, planned * _GL_COMPLIANCE_TOLERANCE)
            if (actual - planned) <= tolerance:
                compliant += 1
        pct_by_uid[uid] = round(100 * compliant / len(occasions), 1) if occasions else None

    return pct_by_uid


def _empty_overview() -> dict:
    return {
        "today": str(date_type.today()),
        "meal_slots": MEAL_SLOTS,
        "summary": {
            "total_participants": 0,
            "active_today": 0,
            "avg_compliance_pct": None,
            "avg_gl_adherence_pct": None,
            "at_risk_count": 0,
            "not_started_count": 0,
        },
        "participants": [],
        "missed_logs_today": [],
        "pending_reviews_24h": [],
    }


@router.get("/overview/{token}")
def status_overview(token: str, days: int = Query(120, ge=7, le=371)):
    _check_token(token)
    sb = get_supabase()

    participants = (
        sb.table("UserRoles")
        .select("user_id, participant_id, display_name")
        .eq("role", "participant")
        .execute()
        .data
    ) or []
    participants = [p for p in participants if str(p.get("participant_id") or "").strip().upper().startswith("A")]
    if not participants:
        return _empty_overview()

    today = date_type.today()
    window_floor = today - timedelta(days=days - 1)
    all_uids = [p["user_id"] for p in participants]
    lookup_ids = _lookup_ids(all_uids)
    plan_start = _earliest_dates(sb, "Recommendation", lookup_ids)
    earliest_recall = _earliest_dates(sb, "DietRecall", lookup_ids)
    activity_start: dict[str, str] = {}
    for uid in all_uids:
        candidates = [d for d in (plan_start.get(uid), earliest_recall.get(uid)) if d]
        if candidates:
            activity_start[uid] = min(candidates)

    window: dict[str, tuple[str, str]] = {}
    for uid in all_uids:
        a_start = activity_start.get(uid)
        start = max(a_start, str(window_floor)) if a_start else str(today)
        end = max(str(today), a_start) if a_start else str(today)
        window[uid] = (start, end)

    global_start = min((w[0] for w in window.values()), default=str(window_floor))

    recalls = (
        sb.table("DietRecall")
        .select("user_id, Date, meal_slot, GL, Energy_Kcal")
        .in_("user_id", lookup_ids)
        .gte("Date", global_start)
        .limit(20000)
        .execute()
        .data
    ) or []

    counts: dict[str, dict[str, dict[str, int]]] = {}
    actual_gl: dict[str, dict[str, dict[str, float]]] = {}
    actual_energy: dict[str, dict[str, dict[str, float]]] = {}
    for r in recalls:
        uid = str(r.get("user_id", "")).split("@")[0]
        slot = str(r.get("meal_slot", "")).strip().lower()
        d = _normalize_date(r.get("Date") or "")
        if not d or slot not in MEAL_SLOTS:
            continue
        counts.setdefault(uid, {}).setdefault(slot, {})
        counts[uid][slot][d] = counts[uid][slot].get(d, 0) + 1
        if r.get("GL") is not None:
            actual_gl.setdefault(uid, {}).setdefault(slot, {})
            actual_gl[uid][slot][d] = actual_gl[uid][slot].get(d, 0.0) + float(r["GL"])
        if r.get("Energy_Kcal") is not None:
            actual_energy.setdefault(uid, {}).setdefault(slot, {})
            actual_energy[uid][slot][d] = actual_energy[uid][slot].get(d, 0.0) + float(r["Energy_Kcal"])

    # Sourced from RecommendationsBackup (the immutable original plan), same
    # table and same recomputation via gl_for_quantity as _bulk_gl_compliant_pct
    # / routers/kpi.py's build_recipe_compliance — so the displayed planned-GL
    # averages always agree with the compliance percentage shown alongside
    # them. FinalSummary reflects the *current* plan (post-swap), which can
    # legitimately diverge from RecommendationsBackup after a recipe swap.
    plan_rows = (
        sb.table("RecommendationsBackup")
        .select("user_id, Date, Timings, Food_Name_desc, Food_Qty, Energy_kcal")
        .in_("user_id", lookup_ids)
        .gte("Date", global_start)
        .limit(20000)
        .execute()
        .data
    ) or []

    plan_codes = list({str(r["Food_Name_desc"]).strip() for r in plan_rows if r.get("Food_Name_desc")})
    plan_base_gl_map = fetch_base_gl_map(sb, plan_codes)
    plan_portion_map = fetch_portion_map(sb, plan_codes)

    # planned_gl[uid][slot][date] = summed planned GL for that meal slot.
    # planned_energy alongside it (also from RecommendationsBackup, same rows)
    # so avg_gl_planned/avg_gl_actual below can use the same energy-weighted
    # average as routers/kpi.py's build_gl_by_meal, not a plain mean.
    planned_gl: dict[str, dict[str, dict[str, float]]] = {}
    planned_energy: dict[str, dict[str, dict[str, float]]] = {}
    for r in plan_rows:
        uid = str(r.get("user_id", "")).split("@")[0]
        d = _normalize_date(r.get("Date") or "")
        code = r.get("Food_Name_desc")
        slot = _MEAL_TIME_TO_SLOT.get(str(r.get("Timings") or "").strip())
        if not d or slot is None or not code:
            continue
        code_norm = str(code).strip()
        gl = gl_for_quantity(plan_base_gl_map.get(code_norm), plan_portion_map.get(code_norm), r.get("Food_Qty"))
        if gl is not None:
            planned_gl.setdefault(uid, {}).setdefault(slot, {})
            planned_gl[uid][slot][d] = planned_gl[uid][slot].get(d, 0.0) + gl
        if r.get("Energy_kcal") is not None:
            planned_energy.setdefault(uid, {}).setdefault(slot, {})
            planned_energy[uid][slot][d] = planned_energy[uid][slot].get(d, 0.0) + float(r["Energy_kcal"])

    gl_compliant_pct_by_uid = _bulk_gl_compliant_pct(sb, lookup_ids, today)

    all_review_rows = (
        sb.table("MealImageReview")
        .select("user_id, diet_recall_id, review_status, created_at")
        .in_("user_id", lookup_ids)
        .in_("review_status", ["pending", "approved"])
        .limit(2000)
        .execute()
        .data
    ) or []
    review_recall_ids = list({r["diet_recall_id"] for r in all_review_rows if r.get("diet_recall_id")})

    review_recall_map: dict[str, dict] = {}
    if review_recall_ids:
        dr_rows = (
            sb.table("DietRecall")
            .select("ID, Date, meal_slot")
            .in_("ID", review_recall_ids)
            .execute()
            .data
        ) or []
        review_recall_map = {r["ID"]: r for r in dr_rows}

    slot_review_statuses: dict[str, dict[str, dict[str, list[str]]]] = {}
    # created_at of each *pending* row within a (uid, slot, date) group — used
    # below to decide staleness for groups that turn out to be fully pending.
    # Rows in an already-partially-approved group are irrelevant to staleness
    # since that group no longer counts as pending at all.
    slot_review_pending_created_at: dict[str, dict[str, dict[str, list[str]]]] = {}
    for r in all_review_rows:
        uid = str(r.get("user_id", "")).split("@")[0]
        recall = review_recall_map.get(r.get("diet_recall_id"))
        if not recall:
            continue
        slot = str(recall.get("meal_slot", "")).strip().lower()
        d = _normalize_date(recall.get("Date") or "")
        if not d or slot not in MEAL_SLOTS:
            continue
        uid_window = window.get(uid)
        if uid_window and not (uid_window[0] <= d <= uid_window[1]):
            continue
        status = r.get("review_status")
        slot_review_statuses.setdefault(uid, {}).setdefault(slot, {}).setdefault(d, []).append(status)
        if status == "pending" and r.get("created_at"):
            slot_review_pending_created_at.setdefault(uid, {}).setdefault(slot, {}).setdefault(d, []).append(
                r["created_at"]
            )

    pending_slots: dict[str, dict[str, set]] = {}
    for uid, slots in slot_review_statuses.items():
        for slot, dates in slots.items():
            for d, statuses in dates.items():
                if statuses and all(s == "pending" for s in statuses):
                    pending_slots.setdefault(uid, {}).setdefault(slot, set()).add(d)

    result = []
    for p in participants:
        uid = p["user_id"]
        start, end = window[uid]
        participant_counts = counts.get(uid, {})
        participant_actual_gl = actual_gl.get(uid, {})
        participant_planned_gl = planned_gl.get(uid, {})
        participant_actual_energy = actual_energy.get(uid, {})
        participant_planned_energy = planned_energy.get(uid, {})
        participant_pending = pending_slots.get(uid, {})

        days_list = []
        d = date_type.fromisoformat(start)
        end_d = date_type.fromisoformat(end)
        logged_total = expected_total = 0
        gl_pairs: list[tuple[float, float]] = []
        # Per-day (GL, Energy) totals, planned and actual tracked separately —
        # feeds the energy-weighted average below (same formula as
        # routers/kpi.py's _weighted_avg_gl_per_day: a day you ate more counts
        # more toward "your typical GL" than a day you barely ate).
        planned_day_gl: dict[str, float] = {}
        planned_day_energy: dict[str, float] = {}
        actual_day_gl: dict[str, float] = {}
        actual_day_energy: dict[str, float] = {}
        while d <= end_d:
            key = str(d)
            meal_counts = {slot: participant_counts.get(slot, {}).get(key, 0) for slot in MEAL_SLOTS}
            logged_count = sum(1 for c in meal_counts.values() if c > 0)
            pending_review_by_meal = {
                slot: key in participant_pending.get(slot, ()) for slot in MEAL_SLOTS
            }

            gl_planned_by_meal = {
                slot: participant_planned_gl.get(slot, {}).get(key) for slot in MEAL_SLOTS
            }
            gl_actual_by_meal = {
                slot: participant_actual_gl.get(slot, {}).get(key) for slot in MEAL_SLOTS
            }
            planned_vals = [v for v in gl_planned_by_meal.values() if v is not None]
            actual_vals = [v for v in gl_actual_by_meal.values() if v is not None]
            gl_planned = sum(planned_vals) if planned_vals else None
            gl_actual = sum(actual_vals) if actual_vals else None

            days_list.append({
                "date": key,
                "meals": meal_counts,
                "logged_count": logged_count,
                "pending_review_by_meal": pending_review_by_meal,
                "gl_planned": round(gl_planned, 1) if gl_planned is not None else None,
                "gl_actual": round(gl_actual, 1) if gl_actual is not None else None,
                "gl_planned_by_meal": {
                    slot: (round(v, 1) if v is not None else None) for slot, v in gl_planned_by_meal.items()
                },
                "gl_actual_by_meal": {
                    slot: (round(v, 1) if v is not None else None) for slot, v in gl_actual_by_meal.items()
                },
            })
            if d <= today:
                expected_total += len(MEAL_SLOTS)
                logged_total += logged_count
            if gl_planned is not None and gl_actual is not None:
                gl_pairs.append((gl_planned, gl_actual))
            # avg_gl_planned/avg_gl_actual below must compare like with like —
            # only occasions (this exact day + meal slot) where BOTH a plan
            # and a log exist, not "every planned slot" vs "every logged
            # slot" independently (those can be different-sized, barely
            # overlapping sets when a lot goes unlogged, which would make the
            # two averages not actually comparable to each other).
            for slot in MEAL_SLOTS:
                slot_planned = gl_planned_by_meal[slot]
                slot_actual = gl_actual_by_meal[slot]
                if slot_planned is None or slot_actual is None:
                    continue
                planned_day_gl[key] = planned_day_gl.get(key, 0.0) + slot_planned
                actual_day_gl[key] = actual_day_gl.get(key, 0.0) + slot_actual
                slot_planned_energy = participant_planned_energy.get(slot, {}).get(key)
                if slot_planned_energy is not None:
                    planned_day_energy[key] = planned_day_energy.get(key, 0.0) + slot_planned_energy
                slot_actual_energy = participant_actual_energy.get(slot, {}).get(key)
                if slot_actual_energy is not None:
                    actual_day_energy[key] = actual_day_energy.get(key, 0.0) + slot_actual_energy
            d += timedelta(days=1)

        last_logged_overall = None
        for slot in MEAL_SLOTS:
            slot_counts = participant_counts.get(slot, {})
            if slot_counts:
                slot_last = max(slot_counts.keys())
                if last_logged_overall is None or slot_last > last_logged_overall:
                    last_logged_overall = slot_last

        compliance_pct = round(100 * logged_total / expected_total, 1) if expected_total else None
        avg_planned = _weighted_avg_gl(planned_day_gl, planned_day_energy)
        avg_actual = _weighted_avg_gl(actual_day_gl, actual_day_energy)
        # "On target" = actual GL didn't exceed planned that day (lower GL is
        # better for blood sugar control, same convention as routers/kpi.py's
        # _gl_indicator).
        on_target_days = sum(1 for g, a in gl_pairs if a <= g)
        gl_adherence_pct = round(100 * on_target_days / len(gl_pairs), 1) if gl_pairs else None

        result.append({
            "user_id": uid,
            "participant_id": p.get("participant_id"),
            "display_name": p.get("display_name"),
            "plan_start_date": plan_start.get(uid),
            "days": days_list,
            "logged_total": logged_total,
            "expected_total": expected_total,
            "compliance_pct": compliance_pct,
            "avg_gl_planned": avg_planned,
            "avg_gl_actual": avg_actual,
            "gl_adherence_pct": gl_adherence_pct,
            "gl_compliant_pct": gl_compliant_pct_by_uid.get(uid),
            "last_logged_date": last_logged_overall,
        })

    result.sort(key=lambda p: p["last_logged_date"] or "", reverse=True)

    today_str = str(today)
    active_today = sum(
        1 for p in result if p["days"] and p["days"][-1]["date"] == today_str and p["days"][-1]["logged_count"] > 0
    )
    compliances = [p["compliance_pct"] for p in result if p["compliance_pct"] is not None]
    adherences = [p["gl_adherence_pct"] for p in result if p["gl_adherence_pct"] is not None]
    at_risk = sum(
        1
        for p in result
        if p["plan_start_date"] and p["plan_start_date"] <= today_str
        and (p["last_logged_date"] is None or (today - date_type.fromisoformat(p["last_logged_date"])).days >= _AT_RISK_DAYS)
    )
    not_started = sum(1 for p in result if not p["plan_start_date"] or p["plan_start_date"] > today_str)
    prefs_resp = (
        sb.table("BE_Preference_onboarding_details")
        .select("user_id, breakfast_time, lunch_time, dinner_time")
        .in_("user_id", lookup_ids)
        .execute()
    )
    user_prefs: dict[str, dict] = {}
    for r in (prefs_resp.data or []):
        user_prefs[str(r.get("user_id", "")).split("@")[0]] = r

    now_ist = datetime.now(IST)
    now_minutes = now_ist.hour * 60 + now_ist.minute

    def _due_minutes(prefs: dict, slot: str) -> int:
        lookup_slot = _SNACK_DUE_AFTER_SLOT if slot == "snacks" else slot
        raw_time = prefs.get(f"{lookup_slot}_time") or ""
        return time_to_minutes(raw_time, DEFAULT_MEAL_TIMES[lookup_slot])

    missed_logs_today = []
    for p in result:
        if not p["plan_start_date"] or p["plan_start_date"] > today_str:
            continue  # plan hasn't started yet
        if not p["days"] or p["days"][-1]["date"] != today_str:
            continue  # today isn't in this participant's window (shouldn't happen once started)
        today_meals = p["days"][-1]["meals"]
        prefs = user_prefs.get(p["user_id"], {})
        missing = [
            slot for slot in MEAL_SLOTS
            if now_minutes >= _due_minutes(prefs, slot) and today_meals[slot] == 0
        ]
        if missing:
            missed_logs_today.append({
                "user_id": p["user_id"],
                "participant_id": p["participant_id"],
                "display_name": p["display_name"],
                "missing_slots": missing,
            })
    missed_logs_today.sort(key=lambda m: (-len(m["missing_slots"]), m["display_name"] or ""))
    now_utc = datetime.now(timezone.utc)
    pending_by_uid: dict[str, list[str]] = {}
    for uid, slots in pending_slots.items():
        for slot, dates in slots.items():
            for d in dates:
                group_created_ats = [
                    c for c in slot_review_pending_created_at.get(uid, {}).get(slot, {}).get(d, []) if c
                ]
                if group_created_ats:
                    pending_by_uid.setdefault(uid, []).append(min(group_created_ats))

    pending_reviews_24h = []
    for p in participants:
        uid = p["user_id"]
        created_ats = [c for c in pending_by_uid.get(uid, []) if c]
        if not created_ats:
            continue
        try:
            oldest_dt = datetime.fromisoformat(min(created_ats).replace("Z", "+00:00"))
            oldest_hours = round((now_utc - oldest_dt).total_seconds() / 3600, 1)
        except ValueError:
            oldest_hours = None
        pending_reviews_24h.append({
            "user_id": uid,
            "participant_id": p.get("participant_id"),
            "display_name": p.get("display_name"),
            "pending_count": len(created_ats),
            "oldest_pending_hours": oldest_hours,
        })
    pending_reviews_24h.sort(key=lambda r: r["oldest_pending_hours"] or 0, reverse=True)

    return {
        "today": today_str,
        "meal_slots": MEAL_SLOTS,
        "summary": {
            "total_participants": len(result),
            "active_today": active_today,
            "avg_compliance_pct": round(sum(compliances) / len(compliances), 1) if compliances else None,
            "avg_gl_adherence_pct": round(sum(adherences) / len(adherences), 1) if adherences else None,
            "at_risk_count": at_risk,
            "not_started_count": not_started,
        },
        "participants": result,
        "missed_logs_today": missed_logs_today,
        "pending_reviews_24h": pending_reviews_24h,
    }


@router.get("/infeasible/{token}")
def infeasible_generations(token: str):
    _check_token(token)
    sb = get_supabase()

    participants = (
        sb.table("UserRoles")
        .select("user_id, participant_id, display_name")
        .eq("role", "participant")
        .execute()
        .data
    ) or []
    participants = [p for p in participants if str(p.get("participant_id") or "").strip().upper().startswith("A")]
    if not participants:
        return {"generated_at": datetime.now(timezone.utc).isoformat(), "entries": []}

    all_uids = [p["user_id"] for p in participants]
    lookup_ids = _lookup_ids(all_uids)
    participant_by_uid = {p["user_id"]: p for p in participants}

    sessions = (
        sb.table("BE_Onboarding_Sessions")
        .select("onboarding_id, user_id, plan_status, created_at")
        .in_("user_id", lookup_ids)
        .execute()
        .data
    ) or []

    # Most recent generation attempt per participant.
    latest_session: dict[str, dict] = {}
    for s in sessions:
        uid = str(s.get("user_id", "")).split("@")[0]
        if uid not in participant_by_uid:
            continue
        created_at = s.get("created_at") or ""
        if uid not in latest_session or created_at > (latest_session[uid].get("created_at") or ""):
            latest_session[uid] = s

    failed_uids = [
        uid for uid, s in latest_session.items()
        if s.get("plan_status") and not str(s["plan_status"]).startswith("ok:")
    ]
    if not failed_uids:
        return {"generated_at": datetime.now(timezone.utc).isoformat(), "entries": []}

    failed_lookup_ids = _lookup_ids(failed_uids)
    plan_rows = (
        sb.table("Recommendation")
        .select("user_id, WeekNo, Date, Timings, Food_Name_desc, Food_Qty, Energy_kcal")
        .in_("user_id", failed_lookup_ids)
        .limit(20000)
        .execute()
        .data
    ) or []

    # Keep only each participant's highest WeekNo (their current/last plan).
    max_week: dict[str, int] = {}
    for r in plan_rows:
        uid = str(r.get("user_id", "")).split("@")[0]
        wk = r.get("WeekNo")
        if wk is None:
            continue
        wk = int(wk)
        if uid not in max_week or wk > max_week[uid]:
            max_week[uid] = wk

    previous_plan_rows: dict[str, list[dict]] = {}
    for r in plan_rows:
        uid = str(r.get("user_id", "")).split("@")[0]
        if r.get("WeekNo") is None or int(r["WeekNo"]) != max_week.get(uid):
            continue
        previous_plan_rows.setdefault(uid, []).append({
            "date": _normalize_date(r.get("Date") or ""),
            "timings": r.get("Timings"),
            "food_name_desc": r.get("Food_Name_desc"),
            "food_qty": r.get("Food_Qty"),
            "energy_kcal": r.get("Energy_kcal"),
        })

    entries = []
    for uid in failed_uids:
        p = participant_by_uid[uid]
        s = latest_session[uid]
        prev_week_no = max_week.get(uid)
        rows = sorted(
            previous_plan_rows.get(uid, []),
            key=lambda r: (r["date"] or "", str(r["timings"] or "")),
        )
        entries.append({
            "user_id": uid,
            "participant_id": p.get("participant_id"),
            "display_name": p.get("display_name"),
            "plan_status": s.get("plan_status"),
            "failed_at": s.get("created_at"),
            "attempted_week_no": (prev_week_no + 1) if prev_week_no is not None else 1,
            "previous_plan": {
                "week_no": prev_week_no,
                "start_date": rows[0]["date"] if rows else None,
                "end_date": rows[-1]["date"] if rows else None,
                "meals": rows,
            } if rows else None,
        })

    entries.sort(key=lambda e: e["failed_at"] or "", reverse=True)

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "entries": entries,
    }


@router.post("/contact/{token}")
def contact_participant(token: str, body: ContactParticipantRequest):
    _check_token(token)

    if body.missing_slots:
        body_text = f"You haven't logged {_format_slot_list(body.missing_slots)} yet today. Please log it in the ADAM app."
    else:
        body_text = "Please remember to log your meals in the ADAM app today."

    sent = send_push(
        user_id=body.user_id,
        title="Reminder to log your meals",
        body=body_text,
        data={"type": "coordinator_reminder"},
    )
    return {"status": "sent" if sent else "no_device"}
