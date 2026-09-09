"""Classifies each user into Portion 1 / Portion 2 / Portion 3 from their
Usual Portion Size Questions answers, and maps (portion_class, week_no) to
the taper overrides routers/plan.py applies to the LP profile.

Replaces the old calendar-week-only taper (every user got the same week1/
week2 relaxation regardless of whether they actually eat larger-than-target
portions) with a classification-driven one:
  - Portion 3 (usual portions already close to/under the model's target):
    no taper at all, any week.
  - Portion 2 (moderately larger than target): weeks 1-2 use the Portion 2
    bounds, week 3+ is untouched system defaults.
  - Portion 1 (usual portions much larger than target): week 1 uses the
    Portion 1 bounds (most generous), week 2 steps down to Portion 2, week
    3+ is untouched system defaults.

Data source boundary: get_user_portion_answers() is the ONLY function that
knows where the raw questionnaire answers live — the Usual_Portion_Size_Answers
Supabase table. classify_portion_class(), get_user_portion_class(), and
get_taper_overrides_for_week() all operate on the returned dict/answers and
don't care where it came from, so a future schema change only touches this
function and _SUPABASE_COLUMN_TO_CATEGORY below.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

logger = logging.getLogger("backend.services.portion_profile")

# --- Data source boundary ---

_ANSWERS_TABLE = os.environ.get("PORTION_ANSWERS_TABLE", "Usual_Portion_Size_Answers")

# Supabase column name -> the category label classify_portion_class() reads.
# Only the 11 keys used by NARROW_TARGETS actually drive classification; the
# rest are carried through for completeness/future use but currently unused.
_SUPABASE_COLUMN_TO_CATEGORY = {
    "dosa": "Dosa (number)",
    "idli": "Idli (number)",
    "chapati": "Chapati (number)",
    "roti": "Roti (number)",
    "rice_cups": "Rice (cups)",
    "millet_rice_cups": "Millet rice (cups)",
    "khichdi_cups": "Khichdi (cups)",
    "pongal_cups": "Pongal (cups)",
    "upma_cups": "Upma (cups)",
    "dal_sambar_curry_cups": "Dal/Sambar/Curry (cups)",
    "vegetable_side_dish_cups": "Vegetable side dish (cups)",
    "tea_cups_day": "Tea (cups/day)",
    "coffee_cups_day": "Coffee (cups/day)",
    "milk_glasses_day": "Milk (glasses/day)",
    "buttermilk_glasses_day": "Buttermilk (glasses/day)",
    "usual_serving_size": "Usual serving size (6b)",
    "eggs_count": "Eggs (count)",
    "paneer_cubes": "Paneer (cubes)",
    "chicken_pieces": "Chicken (pieces)",
    "fish_pieces": "Fish (pieces)",
    "meat_pieces": "Meat (pieces)",
    "fruits_servings_day": "Fruits (servings/day)",
}


def get_user_portion_answers(user_id: str) -> Optional[Dict[str, Any]]:
    """Returns the raw questionnaire answer row for `user_id` (mapped to
    the category labels classify_portion_class() expects), or None if they
    haven't answered (e.g. onboarded before this feature, or simply
    haven't filled it in yet) or the table can't be read.

    Fetches the whole table and matches user_id client-side with
    whitespace stripped on both sides — observed live rows carry stray
    trailing newlines on text fields (including user_id itself, e.g.
    "A002_NASIR\\n"), so a server-side .eq() would silently miss real
    matches. This is a read-only call; it never writes to Supabase.
    """
    try:
        from core.supabase import get_supabase

        res = get_supabase().table(_ANSWERS_TABLE).select("*").execute()
    except Exception:
        logger.exception("Could not read %s for user_id=%s", _ANSWERS_TABLE, user_id)
        return None

    target = user_id.strip()
    matches = [row for row in res.data if str(row.get("user_id", "")).strip() == target]
    if not matches:
        return None

    # A user who filled the form more than once -> use their most recent answer.
    row = max(matches, key=lambda r: r.get("created_at") or "")

    answers: Dict[str, Any] = {}
    for column, category in _SUPABASE_COLUMN_TO_CATEGORY.items():
        value = row.get(column)
        if isinstance(value, str):
            value = value.strip()
        answers[category] = value
    return answers


# --- Classification ---
# Only categories that actually feed a taper knob (_main_taper_bounds /
# _other_taper_bounds) are used — staples (carb mains) and dal/veg sides.
# Beverages, protein sides (egg/paneer/chicken/fish/meat), fruit, and meal
# repetition are collected in the questionnaire for other clinical purposes
# but don't map to any taper bound today, so including them only dilutes
# the ratio with noise (confirmed on synthetic data: A002 moved from
# Portion 2 to Portion 1 once they were excluded, driven by a consistently
# large staple/carb habit that a full 21-category average was masking).

CUP_BUCKET_VALUE = {
    "Do not eat": 0.0,
    "1/2 cup": 0.5,
    "1 cup": 1.0,
    "1 1/2 cups": 1.5,
    "2 cups": 2.0,
    "More than 2 cups": 2.5,
}
DAL_BUCKET_VALUE = {"1/4 cup": 0.25, "1/2 cup": 0.5, "1 cup": 1.0, "1 1/2 cups": 1.5, "2+ cups": 2.0}
VEG_BUCKET_VALUE = {"1/2 cup": 0.5, "1 cup": 1.0, "1 1/2 cups": 1.5, "2+ cups": 2.0}

# Reference/target portion for each category: the model's own default
# reference portion (modal RecipeTagging Portion/Portion description value
# for that food). A judgment call, not a fixed clinical table — revisit if
# real usage shows these targets are off.
NARROW_TARGETS = {
    "Dosa (number)": 2.0,
    "Idli (number)": 2.0,
    "Chapati (number)": 2.0,
    "Roti (number)": 2.0,
    "Rice (cups)": 1.0,
    "Millet rice (cups)": 1.0,
    "Khichdi (cups)": 1.0,
    "Pongal (cups)": 1.0,
    "Upma (cups)": 1.0,
    "Dal/Sambar/Curry (cups)": 1.0,
    "Vegetable side dish (cups)": 1.0,
}

# ratio <= this -> Portion 3 (usual already close to/under target, no taper)
PORTION_3_MAX_RATIO = 1.1
# this < ratio <= PORTION_2_MAX_RATIO -> Portion 2; above it -> Portion 1
PORTION_2_MAX_RATIO = 1.5


def _bucket_to_value(raw: Any) -> float:
    if isinstance(raw, (int, float)):
        return float(raw)
    if raw is None:
        return 0.0
    if raw in CUP_BUCKET_VALUE:
        return CUP_BUCKET_VALUE[raw]
    if raw in DAL_BUCKET_VALUE:
        return DAL_BUCKET_VALUE[raw]
    if raw in VEG_BUCKET_VALUE:
        return VEG_BUCKET_VALUE[raw]
    raise ValueError(f"Unrecognized portion-question answer: {raw!r}")


def classify_portion_class(answers: Dict[str, Any]) -> str:
    """Returns "Portion 1" / "Portion 2" / "Portion 3" from a raw answers
    row (as returned by get_user_portion_answers)."""
    ratios = []
    for category, target in NARROW_TARGETS.items():
        value = _bucket_to_value(answers.get(category))
        if value <= 0:
            continue  # doesn't eat this -> not a portion-size signal
        ratios.append(value / target)

    overall = sum(ratios) / len(ratios) if ratios else 1.0

    if overall <= PORTION_3_MAX_RATIO:
        return "Portion 3"
    if overall <= PORTION_2_MAX_RATIO:
        return "Portion 2"
    return "Portion 1"


def get_user_portion_class(user_id: str) -> str:
    """Portion 1 (the full three-step taper: week1 most generous -> week2
    moderate -> week3+ default) is the fallback for a user with no
    questionnaire answers on file yet -- matches the original calendar-only
    taper every user got before this classification existed, rather than
    guessing they need no taper at all with zero evidence either way."""
    answers = get_user_portion_answers(user_id)
    if not answers:
        return "Portion 1"
    return classify_portion_class(answers)


# --- Portion-class -> weekly taper overrides ---
# Bounds carried over unchanged from the old week-number-keyed
# WEEK_TAPER_CONFIG in routers/plan.py (week1 -> Portion 1, week2 ->
# Portion 2) — same values, same tuning history, just re-keyed by portion
# class instead of calendar week.

PORTION_1_BOUNDS = {
    # Loosened from (1.4,2.5)/(1.1,2.0)/50/150/(1.0,1.3): those values
    # worked for A001 but were genuinely Infeasible for A002 even with
    # macro bands, energy band, and GL caps all disabled individually and
    # together — the combination itself was too tight for A002's candidate
    # pool. These looser values keep the underlying nutrition constraints
    # (macro %, GL floor, sodium/cholesterol/salt) completely untouched and
    # were confirmed Optimal for A002 week 1.
    # Main upper bound tightened 2.5 -> 2.0; Main2/Main3 and Snacks left
    # as-is.
    "_main_taper_bounds": (1.1, 2.0),
    "_other_taper_bounds": (0.85, 2.0),
    "_snack_taper_bounds": (0.5, 1.0),
    "_per_meal_gl_cap_override": 60,
    "_per_day_gl_cap_override": 180,
    # Per-meal GL floor stays at the system default here too —
    # Breakfast/Dinner >= 15, no floor on Lunch (not overridden here).
    "_bmi_age_reduction_strength": 0.0,  # no reduction at all
    # Tightened from (0.8, 1.5): the wide 80-150% band let
    # GL-minimization (which has no incentive to add food once inside a
    # legal band) settle near the floor with nothing pulling it toward the
    # actual target — realized energy came in at 80-95% of eff_daily
    # across a full test week, not the intended ~100%. 90-120% narrows both
    # ends without removing the extra headroom over Portion 3's tighter
    # 90-110% band.
    "_energy_band_override": (0.9, 1.2),
}

PORTION_2_BOUNDS = {
    # Loosened from (1.0,2.0)/40/120/(1.0,1.2): same reason as Portion 1 —
    # A002 also fell back to the no-taper retry under the tighter values.
    # Confirmed Optimal for A002 with these.
    "_main_taper_bounds": (0.8, 2.0),
    "_other_taper_bounds": (0.75, 1.75),
    "_snack_taper_bounds": (0.5, 1.0),
    "_per_meal_gl_cap_override": 50,
    "_per_day_gl_cap_override": 150,
    # Breakfast alone was landing higher than Portion 1's realized GL
    # under the flat cap — tighten it specifically so this stays below
    # Portion 1's at every slot, not just in aggregate.
    "_per_meal_gl_cap_by_slot": {"Breakfast": 22},
    # Dinner was dipping below Portion 3's typical realized GL — raise its
    # floor so this stays above Portion 3's there too.
    "_meal_gl_floor_by_slot": {"Dinner": 26},
    "_bmi_age_reduction_strength": 0.5,  # half the normal reduction
    # Same 90-120% tightening as Portion 1 above, for the same reason.
    "_energy_band_override": (0.9, 1.2),
}

# Portion 3 has no entry anywhere -> always the untouched system defaults
# (_bmi_age_reduction_strength's default of 1.0, lp_optimizer.py's default
# (0.9, 1.1) energy band, default portion bounds/GL caps).
PORTION_TAPER_SCHEDULE = {
    "Portion 1": {1: PORTION_1_BOUNDS, 2: PORTION_2_BOUNDS},
    "Portion 2": {1: PORTION_2_BOUNDS, 2: PORTION_2_BOUNDS},
    "Portion 3": {},
}


def get_taper_overrides_for_week(portion_class: str, week_no: int) -> Dict[str, Any]:
    """Returns the profile overrides to apply for this user's portion class
    at this week number. Empty dict (no override -> full system defaults)
    for Portion 3 at any week, and for week 3+ of any class."""
    return PORTION_TAPER_SCHEDULE.get(portion_class, {}).get(week_no, {})
