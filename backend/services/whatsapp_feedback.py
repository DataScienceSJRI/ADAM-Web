"""
Backtest: what personalized WhatsApp feedback messages *would* have been sent
to each user, one per logged/missed meal-slot-day, if the messaging system had
been live since day 1 of their program (simulated as `--days` ago from today).

Read-only against Supabase (DietRecall, RecommendationsBackup, Recipe,
Main1_Main2_Mapping Subcategory, UserRoles, BE_Preference_onboarding_details)
— no writes. Output is a local Excel workbook acting as the stand-in for the
eventual "pending WhatsApp messages" table (status column included for that
reason).

Each day/slot is scored using only history strictly BEFORE that day, so the
message a user "would have gotten" on day 5 never leans on day 12's data —
this mirrors how the system would really operate day by day.

Every message carries:
- meal_source: whether the eaten dish(es) were actually what we recommended
  ("as_planned"), something the user chose themselves instead ("self_logged_deviated"
  / "mixed"), or there was no plan to compare against at all ("no_plan_available").
  A high-GL callout never tells the user to "swap it next time" for a dish that
  WE planned and they simply ate as recommended — that phrasing only applies
  when the culprit dish was the user's own substitution.
- sent_at: the IST date/time this message would actually have gone out —
  the due time for that meal slot (missed logs), or ~5 minutes after the
  user's earliest DietRecall.created_at for that occasion (reaction messages).
- a nutrition_variance row, in addition to the main message, whenever the
  slot's actual macro/sodium intake (Protein/Carbs/Fat/Fibre/Sodium) diverged
  from what was planned for that slot by >=30% (and above a noise floor).

Usage: python -m services.whatsapp_feedback [--days 20] [--output PATH]
"""
import argparse
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

import pandas as pd

from core.supabase import get_supabase
from services.recall import fetch_base_gl_map, fetch_portion_map, gl_for_quantity
from services.reminders import IST, DEFAULT_MEAL_TIMES, time_to_minutes
from services.wh_messages import mark_error, mark_sent
from services.whatsapp_gateway import get_gateway

MEAL_SLOTS = ["breakfast", "lunch", "dinner", "snacks"]
_SLOT_TIMINGS_TO_MEAL_SLOT = {"Breakfast": "breakfast", "Lunch": "lunch", "Dinner": "dinner", "Snacks": "snacks"}
# Snacks has no preference-time column of its own, so both of its reminder
# times are fixed rather than derived from a preference: the at-mealtime
# reminder (services/reminders.py) fires at 4:30 PM, and this missed-slot
# follow-up (only if still unlogged) fires later, at 6:30 PM.
_SNACK_MISSED_REMINDER_TIME = (18, 30)

_GL_TOLERANCE_PCT = 0.20
_GL_TOLERANCE_FLOOR = 1.0
_SAME_BASE_MIN_DIFF_PCT = 0.10
# A meal that exceeds its (often low) planned GL target can still be
# perfectly safe in absolute terms — e.g. planned 15, actual 25 after a
# swap is still a low-GL meal overall. Below this ceiling, "exceeded the
# plan" doesn't get a "ran high" warning.
_GL_ABSOLUTE_SAFE_CEILING = 25
_PROCESSING_DELAY_MINUTES = 5  # time the bot would need to compute GL/insight after a log
# A logged breakfast/lunch/dinner with GL below this is a red flag, not a win:
# it usually means only part of the meal got logged (e.g. one boiled egg
# standing in for the whole plate), not that the user ate an exceptionally
# low-GL meal. Never applied to snacks (genuinely meant to be tiny), and only
# when the plan itself expected something more substantial — a plan that's
# ALSO this low (or no plan at all) isn't grounds to second-guess the log.
_INCOMPLETE_MEAL_GL_FLOOR = 3

# Sentiment of each message type, for the response_status column — Positive
# (praise/reinforcement), Negative (a miss or a concern to correct), or
# Neutral (purely informational, no judgment either way). nutrition_variance
# isn't listed here since its sentiment depends on direction (good vs bad),
# computed per-row where the message itself is built.
_RESPONSE_STATUS = {
    "personal_best": "Positive",
    "same_base_lower_today": "Positive",
    "same_base_better_option_exists": "Negative",
    "gl_compliant_reinforcement": "Positive",
    "gl_high_but_safe": "Positive",
    "high_gl_culprit": "Negative",
    "high_gl_planned_review": "Negative",
    "logged_no_insight": "Neutral",
    "missed_slot_reminder": "Negative",
    "missed_slot_question": "Negative",
    "logged_unidentified": "Neutral",
    "possibly_incomplete_meal": "Negative",
}

# Macro/sodium subset of routers/kpi.py's NUTRIENT_COLS — the nutrients a
# WhatsApp message can usefully act on, plus a noise floor below which a
# planned amount is too small for a % variance to be meaningful.
NUTRIENT_COLS = ["Protein_PROTCNT_g", "TotalFat_FATCE_g", "Carbohydrate_g", "TotalDietaryFibre_FIBTG_g", "Sodium_mg"]
NUTRIENT_LABELS = {
    "Protein_PROTCNT_g": "protein", "TotalFat_FATCE_g": "fat", "Carbohydrate_g": "carbs",
    "TotalDietaryFibre_FIBTG_g": "fibre", "Sodium_mg": "sodium",
}
NUTRIENT_UNITS = {
    "Protein_PROTCNT_g": "g", "TotalFat_FATCE_g": "g", "Carbohydrate_g": "g",
    "TotalDietaryFibre_FIBTG_g": "g", "Sodium_mg": "mg",
}
NUTRIENT_FLOORS = {"Protein_PROTCNT_g": 3, "TotalFat_FATCE_g": 2, "Carbohydrate_g": 5, "TotalDietaryFibre_FIBTG_g": 1, "Sodium_mg": 50}
_NUTRITION_VARIANCE_PCT = 0.30

# Which direction is actually GOOD for each nutrient — drives whether a
# variance message praises the user or flags the plan. More protein/fibre
# than planned is good; more fat/carbs/sodium than planned is not.
NUTRIENT_HIGHER_IS_BETTER = {
    "Protein_PROTCNT_g": True, "TotalFat_FATCE_g": False, "Carbohydrate_g": False,
    "TotalDietaryFibre_FIBTG_g": True, "Sodium_mg": False,
}
# Nutrient-specific action for the good-direction case — every message ends
# with an action per the Acknowledgment/Finding/Action structure, so this is
# phrased as a next step ("keep doing X") rather than a bare compliment.
_NUTRIENT_GOOD_ACTION = {
    "Sodium_mg": "Keep going easy on the salt!",
    "TotalFat_FATCE_g": "Keep it light on the oil!",
    "Carbohydrate_g": "Keep your portions balanced!",
    "Protein_PROTCNT_g": "Keep including protein-rich foods!",
    "TotalDietaryFibre_FIBTG_g": "Keep including vegetables in your meals!",
}

def _norm_date(d) -> str:
    return str(d)[:10]


def _daterange(start: date, end: date):
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)


def _due_minutes(prefs: dict, slot: str) -> int:
    if slot == "snacks":
        hour, minute = _SNACK_MISSED_REMINDER_TIME
        return hour * 60 + minute
    raw_time = prefs.get(f"{slot}_time") or ""
    return time_to_minutes(raw_time, DEFAULT_MEAL_TIMES[slot])


def _fmt_ist(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M") + " IST"


def _missed_reminder_dt(d: date, prefs: dict, slot: str) -> datetime:
    minutes = _due_minutes(prefs, slot)
    return datetime(d.year, d.month, d.day, minutes // 60, minutes % 60, tzinfo=IST)


def _sent_at_for_missed(d: date, prefs: dict, slot: str) -> str:
    return _fmt_ist(_missed_reminder_dt(d, prefs, slot))


# Fixed escalation time for the "did you actually have X?" follow-up on a
# missed breakfast/lunch/dinner — later than the slot's own due time, giving
# the user a window to log it themselves before we ask. (hour, minute, day_offset)
_MISSED_QUESTION_TIME = {"breakfast": (12, 30, 0), "lunch": (15, 30, 0), "dinner": (8, 30, 1)}


def _missed_question_dt(d: date, slot: str) -> datetime:
    hour, minute, day_offset = _MISSED_QUESTION_TIME[slot]
    target = d + timedelta(days=day_offset)
    return datetime(target.year, target.month, target.day, hour, minute, tzinfo=IST)


def _sent_at_for_missed_question(d: date, slot: str) -> str:
    return _fmt_ist(_missed_question_dt(d, slot))


def _earliest_logged_dt(rows: list[dict]):
    """Earliest DietRecall.created_at among these rows, converted to IST — or
    None if none carry a created_at (older data)."""
    parsed = []
    for r in rows:
        ts = r.get("created_at")
        if not ts:
            continue
        try:
            dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
            if dt.tzinfo is None:
                # Supabase returns created_at without an offset even though it's
                # stored as UTC (services/recall.py writes datetime.now(timezone.utc)).
                # Without this, .astimezone(IST) below would treat the naive value
                # as already being in the SYSTEM's local timezone — which happens to
                # be IST on this machine, so it would silently pass the UTC clock
                # value through unchanged instead of shifting it by +5:30.
                dt = dt.replace(tzinfo=timezone.utc)
            parsed.append(dt)
        except ValueError:
            continue
    return min(parsed).astimezone(IST) if parsed else None


def _sent_at_for_logged(rows: list[dict], d: date, prefs: dict, slot: str) -> str:
    earliest = _earliest_logged_dt(rows)
    if earliest is None:
        # No created_at on these rows (older data) — fall back to the slot's
        # due time as a reasonable stand-in for "when this would have gone out".
        return _sent_at_for_missed(d, prefs, slot)
    sent = earliest + timedelta(minutes=_PROCESSING_DELAY_MINUTES)
    return sent.strftime("%Y-%m-%d %H:%M") + " IST"


# A photo-logged meal sits as Food_Name="Pending" until a coordinator reviews
# and approves it (services/recall.py's approve_review_diet_recall) — there's
# no separate "approved_at" column, so DietRecall.created_at (when it was
# LOGGED, not necessarily when review finished) is the best available proxy
# for how stale the meal already was by the time it became feedback-able.
# Same-day or next-day is still worth a reaction; 2+ days later, the user has
# moved on and a "nice work on Tuesday's lunch" message on Thursday just
# reads as confusing, so it's suppressed entirely (though the GL data still
# counts toward personal-best/same-base history for future comparisons).
_STALE_LOG_GAP_DAYS = 2


def _log_gap_days(rows: list[dict], d: date):
    earliest = _earliest_logged_dt(rows)
    return (earliest.date() - d).days if earliest is not None else None


def _classify_role(subcat: str, mapping_rows: list[dict]) -> str:
    """'main1' if subcat is some row's Main1_Code, 'accomp' if it only shows up
    in Main2_Code/Main3_Code/Optional, else 'unknown'. Same precedence as
    services/replacement.py's _find_column_role."""
    if not subcat:
        return "unknown"
    for row in mapping_rows:
        if str(row.get("Main1_Code") or "").strip().upper() == subcat:
            return "main1"
    for col in ("Main2_Code", "Main3_Code", "Optional"):
        for row in mapping_rows:
            vals = {c.strip().upper() for c in str(row.get(col) or "").split(",") if c.strip()}
            if subcat in vals:
                return "accomp"
    return "unknown"


def _split_base_and_accomp(rows: list[dict], recipe_category: dict, mapping_rows: list[dict]):
    """rows: this occasion's DietRecall rows (each with code/name/gl). Returns
    (base_row, accompaniment_rows). Prefers a row whose Recipe_Category is a
    Main1_Code; falls back to the highest-GL row (the staple is usually the
    biggest GL contributor anyway) when no row resolves to Main1."""
    if len(rows) == 1:
        return rows[0], []
    main1_rows = [
        r for r in rows
        if _classify_role(str(recipe_category.get(r["code"], "")).strip().upper(), mapping_rows) == "main1"
    ]
    base = main1_rows[0] if main1_rows else max(rows, key=lambda r: r["gl"] or 0)
    accomp = [r for r in rows if r is not base]
    return base, accomp


def _pick_main_dish_name(codes: list[str], recipe_category: dict, mapping_rows: list[dict], recipe_info: dict) -> str:
    """Same Main1_Code precedence as _split_base_and_accomp, for a list of
    PLANNED codes (no GL to break ties on, so falls back to the first code
    rather than the highest-GL one) — used to name just the main dish rather
    than reading out every side/curry in a slot."""
    main_codes = [
        c for c in codes
        if _classify_role(str(recipe_category.get(c, "")).strip().upper(), mapping_rows) == "main1"
    ]
    code = main_codes[0] if main_codes else codes[0]
    return recipe_info.get(code, {}).get("Recipe_Name") or code


def _meal_source(rows: list[dict], planned: bool) -> str:
    """Whether what was actually eaten matches what we planned for this
    occasion — drives whether a message may fairly ask the user to "swap"
    something (their own substitution) or must instead flag OUR recommendation
    for review (they simply ate what we gave them)."""
    if not planned:
        return "no_plan_available"
    sources = {r["source"] for r in rows}
    if sources == {"planned"}:
        return "as_planned"
    if sources == {"self_logged"}:
        return "self_logged_deviated"
    return "mixed"


def _nutrient_totals(items: list[dict], recipe_info: dict, portion_map: dict) -> dict:
    totals = {c: 0.0 for c in NUTRIENT_COLS}
    for it in items:
        info = recipe_info.get(it["code"])
        if not info:
            continue
        try:
            base_portion = float(portion_map.get(it["code"]))
            qty = float(it["qty"])
            prop = qty / base_portion if base_portion > 0 else 1.0
        except (TypeError, ValueError):
            prop = 1.0
        for c in NUTRIENT_COLS:
            val = info.get(c)
            if val is not None:
                totals[c] += float(val) * prop
    return totals


def _nutrient_row_amount(row: dict, recipe_info: dict, portion_map: dict, col: str) -> float:
    info = recipe_info.get(row["code"])
    if not info or info.get(col) is None:
        return 0.0
    try:
        base_portion = float(portion_map.get(row["code"]))
        qty = float(row.get("qty"))
        prop = qty / base_portion if base_portion > 0 else 1.0
    except (TypeError, ValueError):
        prop = 1.0
    return float(info[col]) * prop


def _nutrient_culprit_row(rows: list[dict], recipe_info: dict, portion_map: dict, col: str) -> dict:
    """Which dish in the slot actually drove the nutrient in question — NOT
    necessarily the same dish as the GL culprit (e.g. rice drives GL but has
    almost no sodium; a curry/pickle elsewhere in the same meal usually does).
    Merging both into one "mainly from X" clause would misattribute the
    nutrient to the wrong dish, so this is computed independently."""
    return max(rows, key=lambda r: _nutrient_row_amount(r, recipe_info, portion_map, col))


def _biggest_nutrient_gap(planned_n: dict, actual_n: dict):
    """Largest-magnitude relative gap among nutrients whose planned amount
    clears NUTRIENT_FLOORS (so a near-zero baseline can't produce a huge,
    meaningless %). Returns (col, planned, actual, pct) or None."""
    best = None
    for col, floor in NUTRIENT_FLOORS.items():
        p, a = planned_n.get(col, 0.0), actual_n.get(col, 0.0)
        if p < floor:
            continue
        pct = (a - p) / p
        if abs(pct) >= _NUTRITION_VARIANCE_PCT and (best is None or abs(pct) > abs(best[3])):
            best = (col, p, a, pct)
    return best


# ---------------------------------------------------------------------------
# The two functions below are the actual scoring logic, deliberately kept
# free of any bulk/multi-user/date-range fetching so they're the direct seam
# for later live automation:
#   - score_missed_occasion is the TIME-BASED half (a scheduled check finds
#     "still nothing logged past the due time" — nothing to react to, no
#     insert can trigger it).
#   - score_logged_occasion is the ENTRY-TRIGGERED half (fires right after
#     services/recall.py's log_recall()/approve_review_diet_recall() writes a
#     DietRecall row for this occasion).
# build_backtest below is ONLY the backtest-specific bulk fetch + a loop that
# calls these two — a live trigger would fetch the same (much smaller, single-
# occasion) inputs and call the same functions, then insert the returned
# dict(s) into a real Supabase table instead of appending to output_rows.
# ---------------------------------------------------------------------------

def score_missed_occasion(
    base_row: dict, slot: str, d: date, prefs: dict, planned_items: list[dict],
    planned_gl: float | None, recipe_category: dict, mapping_rows: list[dict], recipe_info: dict,
    now: datetime | None = None,
) -> dict | None:
    """One (user, slot, date) that had a plan but nothing logged. Snacks gets
    a due-time reminder; breakfast/lunch/dinner get the later, name-the-main-
    dish question instead (see _MISSED_QUESTION_TIME).

    `now` (IST-aware) is when this is being evaluated — pass the real current
    time (live: whenever the scheduled check runs; backtest: datetime.now(IST))
    so a slot whose escalation time hasn't actually arrived yet doesn't get a
    message invented for it. Returns None in that case. Without `now`, always
    scores (used for days that have already fully elapsed).

    Same short, generic reminder text for every slot (including snacks) —
    no per-dish question. Kept plan-aware inputs (planned_items, recipe_*,
    mapping_rows) in the signature for caller compatibility even though the
    message itself no longer names a specific dish."""
    send_dt = _missed_reminder_dt(d, prefs, slot) if slot == "snacks" else _missed_question_dt(d, slot)
    if now is not None and send_dt > now:
        return None
    label = slot.capitalize()
    return {
        **base_row,
        "message_type": "missed_slot_reminder",
        "message": f"*Reminder: Log Your {label}!*\nDon't forget to log your {slot} to keep your diet record up to date.",
        "meal_source": "no_plan_available", "dishes": None, "actual_gl": None,
        "planned_gl": round(planned_gl, 1) if planned_gl is not None else None,
        "sent_at": _fmt_ist(send_dt), "status": "Pending",
        "response_status": _RESPONSE_STATUS["missed_slot_reminder"],
        "energy_kcal": None, "carbs_g": None, "fibre_g": None,
    }


# Fixed morning send time for the daily logging-streak report.
_STREAK_REPORT_TIME = (7, 30)


def _streak_length(logged_dates: set, planned_dates: set, as_of: date, earliest: date) -> int:
    """Consecutive days ending at `as_of` (inclusive), walking back to the
    user's own plan-start date (`earliest`) — NOT the backtest window start,
    since the streak has to mean something from day 1 of the user's actual
    program. A day only counts toward the streak if it was PLANNED (at least
    one recipe in RecommendationsBackup for that slot/date) — planned-and-
    logged extends the streak, planned-and-not-logged breaks it, and a day
    with no plan at all is skipped entirely (neither extends nor breaks it)."""
    streak = 0
    cur = as_of
    while cur >= earliest:
        d_str = _norm_date(cur)
        if d_str in planned_dates:
            if d_str in logged_dates:
                streak += 1
            else:
                break
        cur -= timedelta(days=1)
    return streak


# A broken streak below this length isn't much of a loss (barely started),
# so it gets the plain "not logged yesterday" phrasing instead of the
# loss-framed "streak ended" one.
_STREAK_BREAK_NOTABLE_MIN = 2


def _streak_break_length(logged_dates: set, planned_dates: set, as_of: date, earliest: date) -> int | None:
    """Length of the streak that just ended, if `as_of` (yesterday) is
    ITSELF the day that broke it — planned but not logged — and it was worth
    noticing (>= _STREAK_BREAK_NOTABLE_MIN). Returns None otherwise, including
    when the streak broke on an earlier day (so the loss-framed message only
    fires once, the morning right after the break, not every day after)."""
    d_str = _norm_date(as_of)
    if d_str not in planned_dates or d_str in logged_dates:
        return None
    prior = _streak_length(logged_dates, planned_dates, as_of - timedelta(days=1), earliest)
    return prior if prior >= _STREAK_BREAK_NOTABLE_MIN else None


def _streak_phrase(n: int, broke_length: int | None = None) -> str:
    if n == 0:
        if broke_length:
            return f"{broke_length}-day streak ended — start a new one today"
        return "not logged yesterday"
    if n == 1:
        return "1-day streak"
    return f"{n}-day streak"


def score_logging_streak_report(
    base_row: dict, d: date, plan_start: date, logged_dates_by_slot: dict[str, set],
    planned_dates_by_slot: dict[str, set], now: datetime | None = None,
) -> dict | None:
    """One message per user per day, sent at a fixed morning time, reporting
    each meal slot's current consecutive-day LOGGING streak (as of yesterday
    — today isn't over yet). Separate from every GL-based message above on
    purpose: it rewards the act of logging itself, independent of how the GL
    turned out, since logging consistency (not GL quality) is the bigger
    compliance gap the data actually shows.

    `plan_start` is THIS user's own first planned date (e.g. a user starting
    today gets their first streak value tomorrow morning, reporting on today).

    `now` gates it the same way missed-slot messages are gated — returns None
    if the report's send time hasn't arrived yet today."""
    hour, minute = _STREAK_REPORT_TIME
    send_dt = datetime(d.year, d.month, d.day, hour, minute, tzinfo=IST)
    if now is not None and send_dt > now:
        return None
    as_of = d - timedelta(days=1)
    streaks = {}
    breaks = {}
    for slot in MEAL_SLOTS:
        logged, planned = logged_dates_by_slot.get(slot, set()), planned_dates_by_slot.get(slot, set())
        streaks[slot] = _streak_length(logged, planned, as_of, plan_start)
        breaks[slot] = _streak_break_length(logged, planned, as_of, plan_start)
    parts = ", ".join(
        f"{slot.capitalize()}: {_streak_phrase(streaks[slot], breaks[slot])}" for slot in MEAL_SLOTS
    )
    any_positive = any(v > 0 for v in streaks.values())
    message = (
        f"Good morning! 🔥 Your logging streaks — {parts}. Keep it up!"
        if any_positive else
        f"Good morning! Your logging streaks — {parts}. Let's turn that around today 💪"
    )
    return {
        **base_row, "meal_slot": "daily_summary",
        "message_type": "logging_streak_report", "message": message,
        "meal_source": None, "dishes": None, "actual_gl": None, "planned_gl": None,
        "sent_at": _fmt_ist(send_dt), "status": "Pending",
        "response_status": "Positive" if any_positive else "Negative",
        "energy_kcal": None, "carbs_g": None, "fibre_g": None,
    }


def score_logged_occasion(
    base_row: dict, slot: str, d: date, d_str: str, rows: list[dict],
    planned: bool, planned_gl: float | None, planned_items: list[dict], prefs: dict,
    recipe_category: dict, mapping_rows: list[dict], recipe_info: dict, portion_map: dict,
    unit_map: dict, hist: list[dict],
) -> tuple[list[dict], dict | None]:
    """Scores ONE (user, slot, date) occasion that HAS at least one DietRecall
    row. `hist` is that user+slot's rolling history — build_backtest passes
    its in-memory accumulator; a live trigger would pass a freshly-queried
    trailing window (e.g. last 14 days) from DietRecall instead.

    Returns (messages, history_entry): messages is 0-2 dicts to emit (main +
    optional nutrition_variance — empty when the occasion is too stale to
    message, per _STALE_LOG_GAP_DAYS); history_entry is what the caller
    should append to `hist` for future occasions (None when there's nothing
    usable to bank yet, e.g. GL not identified)."""
    for r in rows:
        r["source"] = "planned" if r["code"] in {it["code"] for it in planned_items} else "self_logged"
    meal_source = _meal_source(rows, planned)
    sent_at = _sent_at_for_logged(rows, d, prefs, slot)

    gl_rows = [r for r in rows if r["gl"] is not None]
    # "Pending" is the placeholder Food_Name for a photo upload nobody has
    # identified yet — never a real dish, so it must never appear in a dish
    # list.
    named_rows = [r for r in rows if str(r.get("name") or "").strip().lower() != "pending"]
    dish_names = ", ".join(r["name"] for r in named_rows)

    if len(gl_rows) < len(rows):
        # At least one dish in this slot — not necessarily all of them — is
        # still awaiting identification (e.g. one photo already reviewed,
        # another upload for the same slot still pending). A GL/nutrition
        # message built from only the identified part would be incomplete or
        # misleading, so hold off on ANY feedback until every dish in the
        # slot is verified. Still banks nothing into history for the same
        # reason — the totals aren't final yet.
        what = f" ({dish_names})" if dish_names else ""
        message = {
            **base_row,
            "message_type": "logged_unidentified",
            "message": f"Thanks for logging {slot}{what}! We're still processing it — feedback coming soon.",
            "meal_source": meal_source, "dishes": dish_names, "actual_gl": None,
            "planned_gl": round(planned_gl, 1) if planned_gl is not None else None,
            "sent_at": sent_at, "status": "Pending",
            "response_status": _RESPONSE_STATUS["logged_unidentified"],
            "energy_kcal": None, "carbs_g": None, "fibre_g": None,
        }
        return [message], {"date": d_str, "total_gl": None, "base_code": None, "accomp_codes": None}

    total_gl = round(sum(r["gl"] for r in gl_rows), 1)

    # Energy/carbs/fibre for this slot — internal columns only, never quoted
    # in the message text itself, just there so a human reviewing the sheet
    # doesn't have to go recompute them separately.
    energy_rows = [r for r in rows if r.get("energy") is not None]
    slot_energy_kcal = round(sum(r["energy"] for r in energy_rows)) if energy_rows else None
    matched_any_recipe = any(r["code"] in recipe_info for r in rows)
    slot_nutrients = _nutrient_totals(rows, recipe_info, portion_map) if matched_any_recipe else None
    slot_carbs_g = round(slot_nutrients["Carbohydrate_g"], 1) if slot_nutrients is not None else None
    slot_fibre_g = round(slot_nutrients["TotalDietaryFibre_FIBTG_g"], 1) if slot_nutrients is not None else None

    base, accomp = _split_base_and_accomp(rows, recipe_category, mapping_rows)
    base_code = base["code"]
    accomp_codes = frozenset(a["code"] for a in accomp)
    accomp_names = ", ".join(a["name"] for a in accomp) if accomp else None
    history_entry = {
        "date": d_str, "total_gl": total_gl, "base_code": base_code,
        "accomp_codes": accomp_codes, "accomp_names": accomp_names, "base": base,
        "meal_source": meal_source,
    }

    # A photo that sat waiting for coordinator approval, or any log entered
    # 2+ days after the meal, is too stale for a reaction message to be
    # useful — skip messaging entirely but still bank the GL data into
    # history so future personal-best/same-base comparisons stay accurate.
    log_gap = _log_gap_days(rows, d)
    if log_gap is not None and log_gap >= _STALE_LOG_GAP_DAYS:
        return [], history_entry

    # A suspiciously low GL for a full breakfast/lunch/dinner (not snacks)
    # usually means an incomplete log (e.g. one boiled egg standing in for
    # the whole meal), not an exceptionally good one — never praise this as
    # a personal best or "on target". Only flags when the PLAN expected
    # something more substantial; a plan that's also this low (or no plan
    # at all) isn't grounds to second-guess what was actually logged.
    if slot != "snacks" and total_gl < _INCOMPLETE_MEAL_GL_FLOOR and (
        planned_gl is None or planned_gl >= _INCOMPLETE_MEAL_GL_FLOOR
    ):
        what = dish_names or "This"
        message = {
            **base_row,
            "message_type": "possibly_incomplete_meal",
            "message": (
                f"Thanks for logging your {slot}! {what} alone may not make a complete, balanced {slot}. "
                f"Please follow your recommended meal plan, and if you had anything else, add it to your "
                f"log so we can give you accurate feedback."
            ),
            "meal_source": meal_source, "dishes": dish_names, "actual_gl": total_gl,
            "planned_gl": round(planned_gl, 1) if planned_gl is not None else None,
            "sent_at": sent_at, "status": "Pending",
            "response_status": _RESPONSE_STATUS["possibly_incomplete_meal"],
            "energy_kcal": slot_energy_kcal, "carbs_g": slot_carbs_g, "fibre_g": slot_fibre_g,
        }
        return [message], history_entry

    # Nutrition (macro/sodium) variance vs the plan for this slot — computed
    # BEFORE the GL message below so each branch can weave it into the SAME
    # short message (same occasion, same recall — one WhatsApp message, at
    # most two findings total, not a running list).
    nutrient_good = None        # (fact, action) to credit, e.g. ("more fibre (6g vs 3g planned)", "Keep including vegetables...")
    nutrient_bad_fact = None    # bare fact, e.g. "more sodium (1359mg vs 110mg planned)"
    nutrient_bad_culprit = None  # the dish that actually drove it — NOT assumed to be the GL culprit
    nutrient_type_suffix = ""
    if planned_items:
        actual_n = _nutrient_totals(rows, recipe_info, portion_map)
        planned_n = _nutrient_totals(planned_items, recipe_info, portion_map)
        gap = _biggest_nutrient_gap(planned_n, actual_n)
        if gap:
            col, p, a, pct = gap
            label_txt, unit = NUTRIENT_LABELS[col], NUTRIENT_UNITS[col]
            direction = "more" if pct > 0 else "less"
            nutrient_fact = f"{direction} {label_txt} ({round(a)}{unit} vs {round(p)}{unit} planned)"
            # Direction matters: more protein/fibre than planned, or less
            # fat/carbs/sodium than planned, is a GOOD outcome — call it out
            # specifically rather than hedging with a vague "own choice" line.
            # The opposite direction is a real concern, so for THAT case
            # never credit/blame "your choice".
            if (pct > 0) == NUTRIENT_HIGHER_IS_BETTER[col]:
                nutrient_good = (nutrient_fact, _NUTRIENT_GOOD_ACTION[col])
            else:
                nutrient_bad_fact = nutrient_fact
                # Rice drives GL but has almost no sodium — a curry/pickle
                # elsewhere in the same meal usually does. Only worth
                # resolving when there's more than one dish to distinguish.
                if len(rows) > 1:
                    nutrient_bad_culprit = _nutrient_culprit_row(rows, recipe_info, portion_map, col)
            nutrient_type_suffix = "+nutrition_variance"

    msg_type, msg = None, None

    prior_totals = [h["total_gl"] for h in hist if h["total_gl"] is not None]
    if prior_totals and total_gl < min(prior_totals):
        msg_type = "personal_best"
        if nutrient_good:
            tail = f" It also gave you {nutrient_good[0]}. {nutrient_good[1]}"
        elif nutrient_bad_fact:
            tail = f" Just note it had {nutrient_bad_fact}. Keep this one in rotation!"
        else:
            tail = " Keep this one in rotation!"
        msg = f"Great job! Today's {slot} had your lowest GL yet ({round(total_gl)} vs previous best {round(min(prior_totals))}).{tail}"

    if msg_type is None and accomp:
        same_base_prior = [
            h for h in hist
            if h["base_code"] == base_code and h["accomp_codes"] and h["accomp_codes"] != accomp_codes
            and h["total_gl"] is not None
        ]
        if same_base_prior:
            prev = same_base_prior[-1]
            hi, lo = max(total_gl, prev["total_gl"]), min(total_gl, prev["total_gl"])
            if hi > 0 and (hi - lo) / hi >= _SAME_BASE_MIN_DIFF_PCT:
                if nutrient_good:
                    nut_tail = f" It also gave you {nutrient_good[0]}."
                    action = nutrient_good[1]
                elif nutrient_bad_fact:
                    nut_tail = f" Just note it had {nutrient_bad_fact}."
                    action = "Keep making balanced food choices!"
                else:
                    nut_tail = ""
                    action = "Keep making balanced food choices!"
                if total_gl < prev["total_gl"]:
                    msg_type = "same_base_lower_today"
                    msg = (f"Good choice! Today's {slot} had a lower GL than your previous meal "
                           f"({round(total_gl)} vs {round(prev['total_gl'])}).{nut_tail} {action}")
                else:
                    msg_type = "same_base_better_option_exists"
                    msg = (f"Heads up! Today's {slot} had a higher GL than a meal you had on {prev['date']} "
                           f"({round(total_gl)} vs {round(prev['total_gl'])}).{nut_tail} "
                           f"Next time, try repeating that earlier combination.")

    if msg_type is None and planned_gl is not None:
        tolerance = max(_GL_TOLERANCE_FLOOR, planned_gl * _GL_TOLERANCE_PCT)
        exceeded = total_gl - planned_gl > tolerance
        swapped = meal_source in ("self_logged_deviated", "mixed")
        if exceeded and swapped and total_gl <= _GL_ABSOLUTE_SAFE_CEILING:
            # Exceeded the PLAN, but only because the user swapped in
            # something else — and the absolute GL is still low enough to be
            # safe on its own terms. Scoped to actual swaps only: an
            # as-planned meal that runs over is still a planning issue worth
            # flagging (high_gl_planned_review below), regardless of how low
            # the absolute GL is.
            msg_type = "gl_high_but_safe"
            if nutrient_good:
                tail = f" It also gave you {nutrient_good[0]}. {nutrient_good[1]}"
            elif nutrient_bad_fact:
                tail = f" Just note it had {nutrient_bad_fact}. Keep it up!"
            else:
                tail = " Keep it up!"
            msg = (f"Nice work! Even though your {slot} changed, the GL stayed in a safe range "
                   f"({round(total_gl)} vs {round(planned_gl)} planned).{tail}")
        elif exceeded:
            culprit = max(gl_rows, key=lambda r: r["gl"])
            culprit_name = culprit["name"]
            same_culprit = nutrient_bad_culprit is None or nutrient_bad_culprit["code"] == culprit["code"]
            if nutrient_bad_fact and not same_culprit:
                nutrient_clause = f" It also had {nutrient_bad_fact}, mainly from {nutrient_bad_culprit['name']}."
            elif nutrient_bad_fact:
                nutrient_clause = f" and {nutrient_bad_fact}"
            else:
                nutrient_clause = ""
            if culprit["source"] == "planned":
                msg_type = "high_gl_planned_review"
                gl_clause = f"Your {slot} had a higher GL than usual ({round(total_gl)} vs {round(planned_gl)} planned)"
                if nutrient_bad_fact and same_culprit:
                    msg = (f"{gl_clause}{nutrient_clause}, mainly from the portion of {culprit_name} — this was "
                           f"part of your planned meal, so we're reviewing the recommendation.")
                else:
                    msg = (f"{gl_clause}, mainly from the portion of {culprit_name} — this was part of your "
                           f"planned meal, so we're reviewing the recommendation.{nutrient_clause}")
                if nutrient_good:
                    msg += f" On the plus side, it gave you {nutrient_good[0]}."
            else:
                msg_type = "high_gl_culprit"
                gl_clause = f"Your {slot} had a higher GL ({round(total_gl)} vs {round(planned_gl)} planned)"
                if nutrient_bad_fact and same_culprit:
                    msg = f"{gl_clause}{nutrient_clause}, mainly from the portion of {culprit_name}."
                else:
                    msg = f"{gl_clause}, mainly from the portion of {culprit_name}.{nutrient_clause}"
                if nutrient_good:
                    msg += f" On the plus side, it gave you {nutrient_good[0]}."
                msg += " Next time, try a smaller portion or choose a lower-GL alternative from your meal plan."
        else:
            msg_type = "gl_compliant_reinforcement"
            if nutrient_good:
                nut_clause = f" and gave you {nutrient_good[0]}"
                action = nutrient_good[1]
            elif nutrient_bad_fact:
                nut_clause = f", though it had {nutrient_bad_fact}"
                action = "Keep making balanced food choices!"
            else:
                nut_clause = ""
                action = "Keep making balanced food choices!"
            msg = f"Great choice! Your {slot} met the planned GL target{nut_clause}. {action}"

    if msg_type is None:
        msg_type = "logged_no_insight"
        if nutrient_good:
            extra = f", and gave you {nutrient_good[0]}"
        elif nutrient_bad_fact:
            extra = f" — it had {nutrient_bad_fact}"
        else:
            extra = ""
        msg = f"Logged: {dish_names}{extra}. Thanks for keeping track!"

    messages = [{
        **base_row, "message_type": msg_type + nutrient_type_suffix, "message": msg, "meal_source": meal_source,
        "dishes": dish_names, "actual_gl": total_gl,
        "planned_gl": round(planned_gl, 1) if planned_gl is not None else None,
        "sent_at": sent_at, "status": "Pending",
        "response_status": _RESPONSE_STATUS.get(msg_type, "Neutral"),
        "energy_kcal": slot_energy_kcal, "carbs_g": slot_carbs_g, "fibre_g": slot_fibre_g,
    }]

    return messages, history_entry


# ---------------------------------------------------------------------------
# LIVE entry point. Call handle_diet_recall_entry(user_id, meal_slot, date)
# right after a DietRecall write completes for that occasion (e.g. at the end
# of services/recall.py's log_recall() or approve_review_diet_recall()) — it
# scores THAT ONE occasion with the exact same score_logged_occasion() logic
# the backtest uses, inserts each resulting message into WH_Messages, and
# immediately attempts to send it over the existing WhatsApp gateway if the
# user has a linked+activated number (same phone lookup services/
# whatsapp_notify.py's send_whatsapp() uses). Everything below this point is
# the only part of this file meant to run against live production traffic;
# build_backtest/main() above remain the offline analysis tool.
# ---------------------------------------------------------------------------

_LIVE_HISTORY_LOOKBACK_DAYS = 14  # matches routers/kpi.py's GL_TREND_WINDOW_DAYS convention


def _get_activated_phone(sb, user_id: str) -> str | None:
    resp = (
        sb.table("WH_Users").select("phone").eq("user_id", user_id)
        .not_.is_("activated_at", "null").limit(1).execute()
    )
    return resp.data[0].get("phone") if resp.data else None


def handle_diet_recall_entry(user_id: str, meal_slot: str, occasion_date: str) -> list[int]:
    """Returns the WH_Messages row ids inserted (0, 1, or 2 — main +
    optional nutrition_variance), whether or not each one could actually be
    sent. Empty list means nothing to log: no rows for this occasion (already
    deleted since the write?), or the occasion turned out too stale to
    message (see _STALE_LOG_GAP_DAYS in score_logged_occasion)."""
    from models.schemas import SLOT_TO_TIMINGS

    sb = get_supabase()
    end_date = datetime.strptime(occasion_date, "%Y-%m-%d").date()
    start_date = end_date - timedelta(days=_LIVE_HISTORY_LOOKBACK_DAYS - 1)
    start_str, end_str = str(start_date), str(end_date)
    timings = SLOT_TO_TIMINGS[meal_slot]

    recall_rows = (
        sb.table("DietRecall")
        .select("Date, Food_Name, Food_Name_desc, Food_Qty, GL, Energy_Kcal, created_at")
        .eq("user_id", user_id).eq("meal_slot", meal_slot)
        .gte("Date", start_str).lte("Date", end_str)
        .execute().data
    ) or []
    if not any(_norm_date(r["Date"]) == end_str for r in recall_rows):
        return []  # nothing logged for this occasion (yet, or it was removed) — nothing to score

    planned_rows = (
        sb.table("RecommendationsBackup")
        .select("Date, Food_Name_desc, Food_Qty")
        .eq("user_id", user_id).eq("Timings", timings)
        .gte("Date", start_str).lte("Date", end_str)
        .execute().data
    ) or []
    planned_codes = list({str(r["Food_Name_desc"]).strip() for r in planned_rows if r.get("Food_Name_desc")})
    base_gl_map = fetch_base_gl_map(sb, planned_codes)

    planned_occasions: set[str] = set()
    planned_items_by_date: dict[str, list[dict]] = defaultdict(list)
    for r in planned_rows:
        code = str(r["Food_Name_desc"]).strip()
        d_str = _norm_date(r["Date"])
        planned_occasions.add(d_str)
        planned_items_by_date[d_str].append({"code": code, "qty": r.get("Food_Qty")})

    recipe_codes = {str(r["Food_Name_desc"]).strip() for r in recall_rows if r.get("Food_Name_desc")}
    all_codes = list(recipe_codes | set(planned_codes))
    portion_map = fetch_portion_map(sb, all_codes)
    tag_rows = (
        sb.table("RecipeTagging").select("Recipe_Code, Description").in_("Recipe_Code", all_codes).execute().data
        if all_codes else []
    ) or []
    unit_map = {str(t["Recipe_Code"]).strip(): t.get("Description") for t in tag_rows if t.get("Recipe_Code")}
    recipe_rows = (
        sb.table("Recipe")
        .select("Recipe_Code, Recipe_Category, Recipe_Name, " + ", ".join(NUTRIENT_COLS))
        .in_("Recipe_Code", all_codes).execute().data
        if all_codes else []
    ) or []
    recipe_info = {str(r["Recipe_Code"]).strip(): r for r in recipe_rows}
    recipe_category = {code: info.get("Recipe_Category") for code, info in recipe_info.items()}

    planned_gl_by_date: dict[str, float] = defaultdict(float)
    for d_str, items in planned_items_by_date.items():
        for it in items:
            gl = gl_for_quantity(base_gl_map.get(it["code"]), portion_map.get(it["code"]), it["qty"])
            if gl is not None:
                planned_gl_by_date[d_str] += gl

    mapping_rows = sb.table("Main1_Main2_Mapping Subcategory").select("*").execute().data or []

    occasions_by_date: dict[str, list[dict]] = defaultdict(list)
    for r in recall_rows:
        d_str = _norm_date(r["Date"])
        occasions_by_date[d_str].append({
            "code": str(r.get("Food_Name_desc") or "").strip(),
            "name": r.get("Food_Name") or r.get("Food_Name_desc") or "that item",
            "qty": r.get("Food_Qty"), "gl": r.get("GL"),
            "energy": r.get("Energy_Kcal"), "created_at": r.get("created_at"),
        })

    prefs_rows = (
        sb.table("BE_Preference_onboarding_details")
        .select("breakfast_time, lunch_time, dinner_time").eq("user_id", user_id).limit(1).execute().data
    ) or []
    prefs = prefs_rows[0] if prefs_rows else {}

    # Replay every earlier day in the lookback window to rebuild `hist` — the
    # personal-best/same-base comparisons need real prior context, not a
    # blank slate, or day 2's message would never recognize day 1 happened.
    hist: list[dict] = []
    messages: list[dict] = []
    for d in _daterange(start_date, end_date):
        d_str = _norm_date(d)
        rows = occasions_by_date.get(d_str)
        if not rows:
            continue
        base_row = {"user_id": user_id, "date": d_str, "meal_slot": meal_slot}
        day_messages, history_entry = score_logged_occasion(
            base_row, meal_slot, d, d_str, rows,
            d_str in planned_occasions, planned_gl_by_date.get(d_str), planned_items_by_date.get(d_str, []),
            prefs, recipe_category, mapping_rows, recipe_info, portion_map, unit_map, hist,
        )
        if history_entry is not None:
            hist.append(history_entry)
        if d_str == end_str:
            messages = day_messages  # only today's messages get sent — earlier days already were, at their own trigger time

    if not messages:
        return []

    inserted_ids = []
    for m in messages:
        row = {
            "user_id": user_id, "message": m["message"], "status": "pending",
            "meal_date": m["date"], "meal_slot": m["meal_slot"], "message_type": m["message_type"],
            "meal_source": m["meal_source"], "dishes": m["dishes"],
            "actual_gl": m["actual_gl"], "planned_gl": m["planned_gl"],
            "response_status": m["response_status"], "energy_kcal": m["energy_kcal"],
            "carbs_g": m["carbs_g"], "fibre_g": m["fibre_g"], "scheduled_at": m["sent_at"],
        }
        msg_id = _insert_and_send(sb, user_id, row)
        if msg_id is not None:
            inserted_ids.append(msg_id)
    return inserted_ids


def _insert_and_send(sb, user_id: str, row: dict) -> int | None:
    """Insert one row into WH_Messages, then immediately attempt to send it
    if the user has a linked+activated WhatsApp number — shared by every
    live message-producing function so there's exactly one place that does
    this insert-then-send sequence."""
    resp = sb.table("WH_Messages").insert(row).execute()
    if not resp.data:
        return None
    msg_id = resp.data[0]["id"]
    phone = _get_activated_phone(sb, user_id)
    if not phone:
        return msg_id  # no linked+activated WhatsApp number yet — row stays 'pending'
    try:
        get_gateway().send_text(phone, row["message"])
        mark_sent(msg_id)
    except Exception as exc:
        mark_error(msg_id, str(exc))
    return msg_id


# ---------------------------------------------------------------------------
# Missed-slot messages — the TIME-BASED counterpart to
# handle_diet_recall_entry above. Call check_missed_slots() from a cron job
# (same 15-minute cadence as routers/notifications.py's /send-reminders) to
# find occasions whose escalation time just passed with nothing logged, and
# send them. Unlike handle_diet_recall_entry there is no write to react to —
# this has to go looking for the absence of one instead.
# ---------------------------------------------------------------------------

_MISSED_SLOT_LOOKBACK_DAYS = 1  # dinner's question fires 8:30am the NEXT day
# How overdue an escalation is allowed to be and still get sent. Keeps this
# strictly forward-looking from whenever it's first turned on: an occasion
# whose escalation time is further in the past than this (e.g. everything
# that was already overdue before the feature existed) is skipped forever,
# never backfilled -- only occasions that become due AFTER this has started
# running (within one cron cycle's slack) ever get a message. Wider than the
# 15-minute cron cadence to tolerate a delayed/missed cron tick.
_MISSED_SLOT_WINDOW_MINUTES = 20


def check_missed_slots(
    now: datetime | None = None,
    window_minutes: int = _MISSED_SLOT_WINDOW_MINUTES,
    user_ids: list[str] | None = None,
) -> dict[str, int]:
    """Scores every (user, slot, date) in the last day that had a plan but
    nothing logged, using the exact same score_missed_occasion() the
    backtest uses, and inserts+sends any whose escalation time
    (_missed_reminder_dt for snacks, _MISSED_QUESTION_TIME for breakfast/
    lunch/dinner) fell within the last `window_minutes` -- i.e. just became
    due, not any time further in the past. This is what keeps the feature
    forward-only: turning it on today never dredges up and messages users
    about days-old misses from before it existed.

    Idempotent: skips any (user, slot, date, message_type) that already has
    a WH_Messages row, so calling this again inside the same escalation
    window (or a late/duplicate cron fire) never double-sends.

    `user_ids`, if given, restricts scoring to exactly those users (e.g. for
    a scoped manual test) instead of every WhatsApp-activated user. Returns
    {message_type: count_sent}.
    """
    sb = get_supabase()
    now = now or datetime.now(IST)
    candidate_dates = [now.date() - timedelta(days=d) for d in range(_MISSED_SLOT_LOOKBACK_DAYS + 1)]
    date_strs = [str(d) for d in candidate_dates]

    if user_ids is None:
        users_resp = sb.table("WH_Users").select("user_id").not_.is_("activated_at", "null").execute()
        user_ids = list({r["user_id"] for r in (users_resp.data or []) if r.get("user_id")})
    if not user_ids:
        return {}

    prefs_rows = (
        sb.table("BE_Preference_onboarding_details")
        .select("user_id, breakfast_time, lunch_time, dinner_time")
        .in_("user_id", user_ids).execute().data
    ) or []
    prefs_by_user = {r["user_id"]: r for r in prefs_rows}

    planned_rows = (
        sb.table("RecommendationsBackup")
        .select("user_id, Date, Timings, Food_Name_desc, Food_Qty")
        .in_("user_id", user_ids).in_("Date", date_strs)
        .execute().data
    ) or []
    planned_items_by_occasion: dict[tuple, list[dict]] = defaultdict(list)
    for r in planned_rows:
        slot = _SLOT_TIMINGS_TO_MEAL_SLOT.get(str(r.get("Timings") or "").strip())
        d, code = r.get("Date"), r.get("Food_Name_desc")
        if not slot or not d or not code:
            continue
        key = (r["user_id"], slot, _norm_date(d))
        planned_items_by_occasion[key].append({"code": str(code).strip(), "qty": r.get("Food_Qty")})
    if not planned_items_by_occasion:
        return {}

    recall_rows = (
        sb.table("DietRecall")
        .select("user_id, Date, meal_slot")
        .in_("user_id", user_ids).in_("Date", date_strs)
        .execute().data
    ) or []
    logged_occasions = {
        (r["user_id"], str(r.get("meal_slot") or "").strip().lower(), _norm_date(r["Date"]))
        for r in recall_rows if r.get("Date")
    }

    planned_codes = list({str(r["Food_Name_desc"]).strip() for r in planned_rows if r.get("Food_Name_desc")})
    base_gl_map = fetch_base_gl_map(sb, planned_codes)
    portion_map = fetch_portion_map(sb, planned_codes)
    tag_rows = (
        sb.table("RecipeTagging").select("Recipe_Code, Description").in_("Recipe_Code", planned_codes).execute().data
        if planned_codes else []
    ) or []
    unit_map = {str(t["Recipe_Code"]).strip(): t.get("Description") for t in tag_rows if t.get("Recipe_Code")}
    recipe_rows = (
        sb.table("Recipe").select("Recipe_Code, Recipe_Category, Recipe_Name").in_("Recipe_Code", planned_codes).execute().data
        if planned_codes else []
    ) or []
    recipe_info = {str(r["Recipe_Code"]).strip(): r for r in recipe_rows}
    recipe_category = {code: info.get("Recipe_Category") for code, info in recipe_info.items()}
    mapping_rows = sb.table("Main1_Main2_Mapping Subcategory").select("*").execute().data or []

    existing_rows = (
        sb.table("WH_Messages")
        .select("user_id, meal_date, meal_slot, message_type")
        .in_("user_id", user_ids).in_("meal_date", date_strs)
        .in_("message_type", ["missed_slot_reminder", "missed_slot_question"])
        .execute().data
    ) or []
    already_sent = {(r["user_id"], r["meal_date"], r["meal_slot"], r["message_type"]) for r in existing_rows}

    counts: dict[str, int] = {}
    for (uid, slot, d_str), items in planned_items_by_occasion.items():
        if (uid, slot, d_str) in logged_occasions:
            continue  # something was logged for this occasion -- not missed

        planned_gl = 0.0
        has_gl = False
        for it in items:
            gl = gl_for_quantity(base_gl_map.get(it["code"]), portion_map.get(it["code"]), it["qty"])
            if gl is not None:
                planned_gl += gl
                has_gl = True

        d = datetime.strptime(d_str, "%Y-%m-%d").date()
        prefs = prefs_by_user.get(uid, {})
        send_dt = _missed_reminder_dt(d, prefs, slot) if slot == "snacks" else _missed_question_dt(d, slot)
        if send_dt > now:
            continue  # this slot's escalation time hasn't arrived yet
        if (now - send_dt) > timedelta(minutes=window_minutes):
            continue  # escalation was already overdue before this window -- forward-only, never backfilled

        base_row = {"user_id": uid, "date": d_str, "meal_slot": slot}
        message = score_missed_occasion(
            base_row, slot, d, prefs, items,
            planned_gl if has_gl else None, recipe_category, mapping_rows, recipe_info, now=now,
        )
        if message is None:
            continue  # defensive: score_missed_occasion agrees this isn't due yet

        key = (uid, message["date"], message["meal_slot"], message["message_type"])
        if key in already_sent:
            continue  # already sent this exact missed-slot message once

        row = {
            "user_id": uid, "message": message["message"], "status": "pending",
            "meal_date": message["date"], "meal_slot": message["meal_slot"],
            "message_type": message["message_type"], "meal_source": message["meal_source"],
            "dishes": message["dishes"], "actual_gl": message["actual_gl"], "planned_gl": message["planned_gl"],
            "response_status": message["response_status"], "energy_kcal": message["energy_kcal"],
            "carbs_g": message["carbs_g"], "fibre_g": message["fibre_g"], "scheduled_at": message["sent_at"],
        }
        msg_id = _insert_and_send(sb, uid, row)
        if msg_id is not None:
            counts[message["message_type"]] = counts.get(message["message_type"], 0) + 1

    return counts


# ---------------------------------------------------------------------------
# Next-day meal preview — a short, one-way heads-up of tomorrow's planned
# meals (dish names + time per slot, nothing else) so the user can be ready
# with ingredients/recipes ahead of time. Call send_next_day_previews() once
# a day around _NEXT_DAY_PREVIEW_TIME (7:00 PM IST) — see
# routers/notifications.py's send-next-day-preview endpoint.
# ---------------------------------------------------------------------------

_NEXT_DAY_PREVIEW_TIME = (19, 0)  # 7:00 PM IST
# Chronological, not MEAL_SLOTS' order — reads like an actual day's schedule.
_PREVIEW_SLOT_ORDER = ["breakfast", "lunch", "snacks", "dinner"]


def build_next_day_preview(
    user_id: str, tomorrow: date, dishes_by_slot: dict[str, list[str]],
) -> dict | None:
    """One user's heads-up for `tomorrow` — just slot name and dish names,
    deliberately nothing else (no time, no GL, no nutrition) per the ask to
    keep it short. Returns None if nothing is planned for tomorrow at all."""
    lines = []
    for slot in _PREVIEW_SLOT_ORDER:
        names = dishes_by_slot.get(slot)
        if not names:
            continue
        lines.append(f"{slot.capitalize()}: {', '.join(names)}")
    if not lines:
        return None
    message = "*Tomorrow's Meal Plan*\n" + "\n".join(lines)
    return {
        "user_id": user_id, "message": message, "status": "pending",
        "meal_date": _norm_date(tomorrow), "meal_slot": "next_day_summary",
        "message_type": "next_day_meal_preview",
        "meal_source": None, "dishes": None, "actual_gl": None, "planned_gl": None,
        "response_status": "Neutral", "energy_kcal": None, "carbs_g": None, "fibre_g": None,
        "scheduled_at": _fmt_ist(datetime.now(IST)),
    }


def send_next_day_previews(now: datetime | None = None) -> list[int]:
    """Sends every real study participant a short heads-up of tomorrow's
    planned meals. Call this once a day around _NEXT_DAY_PREVIEW_TIME
    (7:00 PM IST) from a cron job.

    Idempotent: skips any user who already has a next_day_meal_preview row
    for tomorrow's date, so a cron running more than once a day (e.g. every
    15 minutes, same cadence as the other reminder crons) never re-sends the
    same preview after 7 PM."""
    sb = get_supabase()
    now = now or datetime.now(IST)
    hour, minute = _NEXT_DAY_PREVIEW_TIME
    send_dt = datetime(now.year, now.month, now.day, hour, minute, tzinfo=IST)
    if now < send_dt:
        return []

    tomorrow = now.date() + timedelta(days=1)
    tomorrow_str = _norm_date(tomorrow)

    participants = sb.table("UserRoles").select("user_id, participant_id").execute().data or []
    user_ids = [
        p["user_id"] for p in participants
        if str(p.get("participant_id") or "").strip().upper().startswith("A")
    ]
    if not user_ids:
        return []

    existing = (
        sb.table("WH_Messages").select("user_id")
        .in_("user_id", user_ids).eq("meal_date", tomorrow_str).eq("message_type", "next_day_meal_preview")
        .execute().data
    ) or []
    already_sent = {r["user_id"] for r in existing}

    planned_rows = (
        sb.table("RecommendationsBackup").select("user_id, Timings, Food_Name_desc")
        .in_("user_id", user_ids).eq("Date", tomorrow_str)
        .execute().data
    ) or []
    codes = list({str(r["Food_Name_desc"]).strip() for r in planned_rows if r.get("Food_Name_desc")})
    recipe_rows = (
        sb.table("Recipe").select("Recipe_Code, Recipe_Name").in_("Recipe_Code", codes).execute().data
        if codes else []
    ) or []
    name_map = {r["Recipe_Code"]: r.get("Recipe_Name") for r in recipe_rows}

    dishes_by_user_slot: dict[tuple, list[str]] = defaultdict(list)
    for r in planned_rows:
        slot = _SLOT_TIMINGS_TO_MEAL_SLOT.get(str(r.get("Timings") or "").strip())
        code = str(r.get("Food_Name_desc") or "").strip()
        if not slot or not code:
            continue
        name = name_map.get(code) or code
        key = (r["user_id"], slot)
        if name not in dishes_by_user_slot[key]:
            dishes_by_user_slot[key].append(name)

    inserted_ids = []
    for uid in user_ids:
        if uid in already_sent:
            continue
        dishes_by_slot = {slot: dishes_by_user_slot.get((uid, slot), []) for slot in MEAL_SLOTS}
        row = build_next_day_preview(uid, tomorrow, dishes_by_slot)
        if row is None:
            continue
        msg_id = _insert_and_send(sb, uid, row)
        if msg_id is not None:
            inserted_ids.append(msg_id)
    return inserted_ids


# ---------------------------------------------------------------------------
# Weekly digest — NOT live (by explicit request). build_weekly_digest exists
# only for build_backtest, the offline analysis tool, to preview what a
# weekly summary would look like. There is no live send function or cron
# endpoint for it — do not add one without being asked again.
# ---------------------------------------------------------------------------

_WEEKLY_DIGEST_WINDOW_DAYS = 7

# Headline nutrients for the weekly digest, keyed by the internal column
# name routers/kpi.py's _daily_ear_map/Recipe table use.
_WEEKLY_NUTRIENT_COLS = {
    "Energy_ENERC_Kcal": "Energy", "Protein_PROTCNT_g": "Protein",
    "Carbohydrate_g": "Carbs", "TotalDietaryFibre_FIBTG_g": "Fibre",
}


def _weekly_nutrient_pct_met(user_id: str, week_start: date, week_end: date) -> dict[str, int]:
    """% of the FULL week's requirement met — deliberately NOT normalized by
    how many days were actually logged. An unlogged day still counts against
    the denominator on purpose: a low number here is meant to read as "log
    more" as much as "eat more," reinforcing the same logging-compliance
    push as the rest of this file. Capped at 100 per nutrient — exceeding
    target isn't something to chase further, so it's not shown as e.g. 280%.
    Skips a nutrient entirely if there's no requirement data for this user's
    profile (rather than showing a misleading 0%).

    Replicates routers/kpi.py's build_daily_nutrient_summary scaling logic
    as ONE bulk fetch across the whole week, instead of calling that function
    once per day (7x redundant profile/EAR/Recipe/RecipeTagging queries per
    user) — the per-day version made the weekly digest slow enough (100+
    seconds for just 7 users in testing) to risk a cron/HTTP timeout as the
    participant count grows."""
    from routers.kpi import _daily_ear_map
    from services.profile_builder import build_profile

    profile = build_profile(user_id)
    daily_min = _daily_ear_map(profile) if profile else {}
    if not daily_min:
        return {}

    sb = get_supabase()
    start_str, end_str = str(week_start), str(week_end)
    recall_rows = (
        sb.table("DietRecall").select("Food_Name_desc, Food_Qty")
        .eq("user_id", user_id).gte("Date", start_str).lte("Date", end_str)
        .execute().data
    ) or []
    eaten = [r for r in recall_rows if r.get("Food_Name_desc")]
    if not eaten:
        return {}

    recipe_codes = list({r["Food_Name_desc"] for r in eaten})
    recipe_cols = [c for c in _WEEKLY_NUTRIENT_COLS if c != "Energy_ENERC_Kcal"]
    recipe_rows = (
        sb.table("Recipe").select("Recipe_Code, Energy_ENERC_KJ, " + ", ".join(recipe_cols))
        .in_("Recipe_Code", recipe_codes).execute().data
    ) or []
    recipe_map = {r["Recipe_Code"]: r for r in recipe_rows}
    tag_rows = (
        sb.table("RecipeTagging").select("Recipe_Code, Portion").in_("Recipe_Code", recipe_codes).execute().data
    ) or []
    portion_map = {t["Recipe_Code"]: t.get("Portion") for t in tag_rows}

    totals = {col: 0.0 for col in _WEEKLY_NUTRIENT_COLS}
    for r in eaten:
        recipe = recipe_map.get(r["Food_Name_desc"])
        if not recipe:
            continue
        try:
            base_portion = float(portion_map.get(r["Food_Name_desc"]))
            food_qty = float(r.get("Food_Qty"))
            prop = food_qty / base_portion if base_portion > 0 else 1.0
        except (TypeError, ValueError):
            prop = 1.0
        totals["Energy_ENERC_Kcal"] += (float(recipe.get("Energy_ENERC_KJ") or 0) / 4.184) * prop
        for col in recipe_cols:
            val = recipe.get(col)
            if val is not None:
                totals[col] += float(val) * prop

    num_days = (week_end - week_start).days + 1
    result = {}
    for col, label in _WEEKLY_NUTRIENT_COLS.items():
        req = daily_min.get(col)
        if req:
            result[label] = min(100, round(totals[col] / (req * num_days) * 100))
    return result


def build_weekly_digest(user_id: str, week_end: date) -> dict | None:
    """One user's digest for the 7 days ending `week_end` (typically
    yesterday — the day it's sent hasn't fully happened yet). Returns a
    WH_Messages-shaped row dict, or None if there's nothing to report (no
    plan existed at all in the window)."""
    sb = get_supabase()
    week_start = week_end - timedelta(days=_WEEKLY_DIGEST_WINDOW_DAYS - 1)
    start_str, end_str = str(week_start), str(week_end)

    planned_rows = (
        sb.table("RecommendationsBackup")
        .select("Date, Timings, Food_Name_desc, Food_Qty")
        .eq("user_id", user_id).gte("Date", start_str).lte("Date", end_str)
        .execute().data
    ) or []
    if not planned_rows:
        return None

    planned_codes = list({str(r["Food_Name_desc"]).strip() for r in planned_rows if r.get("Food_Name_desc")})
    base_gl_map = fetch_base_gl_map(sb, planned_codes)
    portion_map = fetch_portion_map(sb, planned_codes)

    planned_occasions: set[tuple[str, str]] = set()  # (date, slot)
    planned_gl_by_occasion: dict[tuple[str, str], float] = defaultdict(float)
    for r in planned_rows:
        slot = _SLOT_TIMINGS_TO_MEAL_SLOT.get(str(r.get("Timings") or "").strip())
        d_str = _norm_date(r["Date"])
        if not slot:
            continue
        planned_occasions.add((d_str, slot))
        gl = gl_for_quantity(base_gl_map.get(str(r.get("Food_Name_desc") or "").strip()), portion_map.get(str(r.get("Food_Name_desc") or "").strip()), r.get("Food_Qty"))
        if gl is not None:
            planned_gl_by_occasion[(d_str, slot)] += gl

    recall_rows = (
        sb.table("DietRecall")
        .select("Date, meal_slot, GL")
        .eq("user_id", user_id).gte("Date", start_str).lte("Date", end_str)
        .execute().data
    ) or []
    logged_occasions: set[tuple[str, str]] = set()
    actual_gl_by_occasion: dict[tuple[str, str], float] = defaultdict(float)
    for r in recall_rows:
        slot = str(r.get("meal_slot") or "").strip().lower()
        if slot not in MEAL_SLOTS:
            continue
        d_str = _norm_date(r["Date"])
        logged_occasions.add((d_str, slot))
        if r.get("GL") is not None:
            actual_gl_by_occasion[(d_str, slot)] += float(r["GL"])

    total_planned = len(planned_occasions)
    total_logged = len(planned_occasions & logged_occasions)

    gl_compliant = 0
    for occ in planned_occasions & logged_occasions:
        planned_gl = planned_gl_by_occasion.get(occ)
        actual_gl = actual_gl_by_occasion.get(occ)
        if planned_gl is None or actual_gl is None:
            continue
        tolerance = max(_GL_TOLERANCE_FLOOR, planned_gl * _GL_TOLERANCE_PCT)
        if actual_gl - planned_gl <= tolerance:
            gl_compliant += 1

    if total_logged == total_planned and total_planned > 0:
        opener = "🎉 Perfect week"
    elif total_logged >= total_planned * 0.7:
        opener = "👍 Solid week"
    else:
        opener = "This week"

    nutrient_pct = _weekly_nutrient_pct_met(user_id, week_start, week_end)
    nutrient_line = ""
    if nutrient_pct:
        parts = ", ".join(f"{k} {v}%" for k, v in nutrient_pct.items())
        nutrient_line = f" Nutrient targets met this week: {parts} — logging every meal helps this go up."

    message = (
        f"{opener} — {total_logged}/{total_planned} meals logged, {gl_compliant} on GL target."
        f"{nutrient_line} Here's to next week!"
    )
    return {
        "user_id": user_id, "message": message, "status": "pending",
        "meal_date": end_str, "meal_slot": "weekly_summary", "message_type": "weekly_digest",
        "meal_source": None, "dishes": None, "actual_gl": None, "planned_gl": None,
        "response_status": "Positive" if total_planned and total_logged / total_planned >= 0.7 else "Negative",
        "energy_kcal": None, "carbs_g": None, "fibre_g": None,
        "scheduled_at": _fmt_ist(datetime.now(IST)),
    }


# NOTE: the daily logging-streak report and the weekly digest are NOT live —
# by explicit request, only score_logging_streak_report/build_weekly_digest
# (used below by build_backtest, the offline analysis tool) exist. There is
# no send_streak_reports/send_weekly_digests function and no cron endpoint
# for either — do not re-add one without being asked again.


def build_backtest(days: int) -> pd.DataFrame:
    sb = get_supabase()
    end_date = date.today()
    start_date = end_date - timedelta(days=days - 1)
    start_str, end_str = str(start_date), str(end_date)
    # "Today" in the window hasn't fully elapsed — passing `now` means a slot
    # whose missed-message escalation time hasn't arrived yet (e.g. it's
    # 8:39 AM and lunch's question isn't due until 3:30 PM) doesn't get a
    # message invented for it. Every earlier day in the window is already
    # fully in the past, so this is a no-op for them.
    now_ist = datetime.now(IST)

    # Participants come FIRST, independent of whether they've logged anything
    # in this window — a brand-new user (plan started today, nothing logged
    # yet) must still get missed-slot/streak messages. Deriving user_ids from
    # DietRecall instead would silently exclude exactly that user.
    participants = (
        sb.table("UserRoles")
        .select("user_id, participant_id, display_name")
        .execute().data
    ) or []
    # Only real study participants (participant_id starts with "A") — matches
    # the filter routers/status_dashboard.py applies; P-prefixed ids are
    # internal/test accounts (staff logins, QA builds) and would pollute a
    # report meant to show real per-user compliance behavior.
    participants = [p for p in participants if str(p.get("participant_id") or "").strip().upper().startswith("A")]
    labels = {p["user_id"]: p for p in participants}
    user_ids = sorted(labels.keys())
    if not user_ids:
        return pd.DataFrame()

    recall_rows = (
        sb.table("DietRecall")
        .select("user_id, Date, meal_slot, Food_Name, Food_Name_desc, Food_Qty, GL, Energy_Kcal, created_at")
        .in_("user_id", user_ids)
        .gte("Date", start_str).lte("Date", end_str)
        .execute().data
    ) or []

    prefs_rows = (
        sb.table("BE_Preference_onboarding_details")
        .select("user_id, breakfast_time, lunch_time, dinner_time")
        .in_("user_id", user_ids)
        .execute().data
    ) or []
    meal_prefs = {r["user_id"]: r for r in prefs_rows}

    planned_rows = (
        sb.table("RecommendationsBackup")
        .select("user_id, Date, Timings, Food_Name_desc, Food_Qty")
        .in_("user_id", user_ids)
        .gte("Date", start_str).lte("Date", end_str)
        .execute().data
    ) or []
    planned_codes = list({str(r["Food_Name_desc"]).strip() for r in planned_rows if r.get("Food_Name_desc")})
    base_gl_map = fetch_base_gl_map(sb, planned_codes)

    planned_gl_by_occasion: dict[tuple, float] = defaultdict(float)
    planned_occasions: set[tuple] = set()
    planned_items_by_occasion: dict[tuple, list[dict]] = defaultdict(list)
    for r in planned_rows:
        slot = _SLOT_TIMINGS_TO_MEAL_SLOT.get(str(r.get("Timings") or "").strip())
        d, code = r.get("Date"), r.get("Food_Name_desc")
        if not slot or not d or not code:
            continue
        code_norm = str(code).strip()
        key = (r["user_id"], slot, _norm_date(d))
        planned_occasions.add(key)
        planned_items_by_occasion[key].append({"code": code_norm, "qty": r.get("Food_Qty")})

    recipe_codes = {str(r["Food_Name_desc"]).strip() for r in recall_rows if r.get("Food_Name_desc")}
    all_codes = list(recipe_codes | set(planned_codes))
    portion_map = fetch_portion_map(sb, all_codes)
    tag_rows = (
        sb.table("RecipeTagging").select("Recipe_Code, Description").in_("Recipe_Code", all_codes).execute().data
        if all_codes else []
    ) or []
    unit_map = {str(t["Recipe_Code"]).strip(): t.get("Description") for t in tag_rows if t.get("Recipe_Code")}
    recipe_rows = (
        sb.table("Recipe")
        .select("Recipe_Code, Recipe_Category, Recipe_Name, " + ", ".join(NUTRIENT_COLS))
        .in_("Recipe_Code", all_codes).execute().data
        if all_codes else []
    ) or []
    recipe_info = {str(r["Recipe_Code"]).strip(): r for r in recipe_rows}
    recipe_category = {code: info.get("Recipe_Category") for code, info in recipe_info.items()}

    for key, items in planned_items_by_occasion.items():
        for it in items:
            gl = gl_for_quantity(base_gl_map.get(it["code"]), portion_map.get(it["code"]), it["qty"])
            if gl is not None:
                planned_gl_by_occasion[key] += gl

    mapping_rows = sb.table("Main1_Main2_Mapping Subcategory").select("*").execute().data or []

    occasions: dict[tuple, list[dict]] = defaultdict(list)
    for r in recall_rows:
        slot = str(r.get("meal_slot") or "").strip().lower()
        d = r.get("Date")
        if slot not in MEAL_SLOTS or not d:
            continue
        d_str = _norm_date(d)
        key = (r["user_id"], slot, d_str)
        occasions[key].append({
            "code": str(r.get("Food_Name_desc") or "").strip(),
            "name": r.get("Food_Name") or r.get("Food_Name_desc") or "that item",
            "qty": r.get("Food_Qty"),
            "gl": r.get("GL"),
            "energy": r.get("Energy_Kcal"),
            "created_at": r.get("created_at"),
        })

    # Logging-streak history — deliberately NOT limited to the --days backtest
    # window: it needs each user's full history back to their own plan-start
    # date, which for these real participants is well before this window
    # (e.g. Aug 11-13, while the window itself might only go back to Aug 16).
    streak_planned_rows = (
        sb.table("RecommendationsBackup").select("user_id, Date, Timings").in_("user_id", user_ids).execute().data
    ) or []
    plan_start_by_user: dict[str, date] = {}
    planned_dates_by_user_slot: dict[tuple, set] = defaultdict(set)
    for r in streak_planned_rows:
        slot = _SLOT_TIMINGS_TO_MEAL_SLOT.get(str(r.get("Timings") or "").strip())
        d = r.get("Date")
        if not slot or not d:
            continue
        d_str = _norm_date(d)
        planned_dates_by_user_slot[(r["user_id"], slot)].add(d_str)
        d_date = datetime.strptime(d_str, "%Y-%m-%d").date()
        if r["user_id"] not in plan_start_by_user or d_date < plan_start_by_user[r["user_id"]]:
            plan_start_by_user[r["user_id"]] = d_date

    streak_recall_rows = (
        sb.table("DietRecall").select("user_id, Date, meal_slot").in_("user_id", user_ids).execute().data
    ) or []
    logged_dates_by_user_slot: dict[tuple, set] = defaultdict(set)
    for r in streak_recall_rows:
        slot = str(r.get("meal_slot") or "").strip().lower()
        d = r.get("Date")
        if slot not in MEAL_SLOTS or not d:
            continue
        logged_dates_by_user_slot[(r["user_id"], slot)].add(_norm_date(d))

    output_rows = []
    history: dict[tuple, list[dict]] = defaultdict(list)  # (user, slot) -> chronological entries

    for uid in user_ids:
        label = labels.get(uid, {})
        prefs = meal_prefs.get(uid, {})
        for slot in MEAL_SLOTS:
            for d in _daterange(start_date, end_date):
                d_str = _norm_date(d)
                key = (uid, slot, d_str)
                rows = occasions.get(key)
                planned = key in planned_occasions
                planned_gl = planned_gl_by_occasion.get(key)
                planned_items = planned_items_by_occasion.get(key, [])
                base_row = {
                    "user_id": uid, "participant_id": label.get("participant_id"),
                    "display_name": label.get("display_name"), "date": d_str, "meal_slot": slot,
                }

                if not rows:
                    if not planned:
                        continue
                    missed_message = score_missed_occasion(
                        base_row, slot, d, prefs, planned_items, planned_gl,
                        recipe_category, mapping_rows, recipe_info, now=now_ist,
                    )
                    if missed_message is not None:
                        output_rows.append(missed_message)
                    continue

                messages, history_entry = score_logged_occasion(
                    base_row, slot, d, d_str, rows, planned, planned_gl, planned_items,
                    prefs, recipe_category, mapping_rows, recipe_info, portion_map,
                    unit_map, history[(uid, slot)],
                )
                output_rows.extend(messages)
                if history_entry is not None:
                    history[(uid, slot)].append(history_entry)

    # Daily logging-streak report — one per user per day, starting from day 2
    # of THAT USER'S OWN plan (not the --days backtest window): a user whose
    # plan starts today gets their first streak value tomorrow morning,
    # reporting on today. Runs through end_date regardless of how long ago
    # the user actually started, independent of --days.
    for uid in user_ids:
        label = labels.get(uid, {})
        plan_start = plan_start_by_user.get(uid)
        if plan_start is None:
            continue  # no plan has ever been generated for this user
        logged_dates_by_slot = {slot: logged_dates_by_user_slot.get((uid, slot), set()) for slot in MEAL_SLOTS}
        planned_dates_by_slot = {slot: planned_dates_by_user_slot.get((uid, slot), set()) for slot in MEAL_SLOTS}
        for d in _daterange(plan_start + timedelta(days=1), end_date):
            base_row = {
                "user_id": uid, "participant_id": label.get("participant_id"),
                "display_name": label.get("display_name"), "date": _norm_date(d),
            }
            streak_message = score_logging_streak_report(
                base_row, d, plan_start, logged_dates_by_slot, planned_dates_by_slot, now=now_ist,
            )
            if streak_message is not None:
                output_rows.append(streak_message)

    df = pd.DataFrame(output_rows)
    if not df.empty:
        df = df.sort_values(["display_name", "user_id", "date", "meal_slot"]).reset_index(drop=True)
    return df


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=20)
    parser.add_argument("--output", type=str, default="whatsapp_feedback_backtest.xlsx")
    args = parser.parse_args()

    df = build_backtest(args.days)
    if df.empty:
        print("No DietRecall data found in the window — nothing to write.")
        return

    df.to_excel(args.output, sheet_name="Messages", index=False)

    print(f"Wrote {len(df)} message rows for {df['user_id'].nunique()} users to {args.output}")


if __name__ == "__main__":
    main()
