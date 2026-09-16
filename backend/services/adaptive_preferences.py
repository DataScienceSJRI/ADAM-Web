"""Adaptive Main-dish preference learning.

On top of what a user declared during onboarding (BE_Preference_onboarding),
this learns two corrections from their real DietRecall history, per
(user_id, meal_time), scoped to dish_type == "Main" only (Main 2/Main 3 --
curries/sides -- are eaten in flexible combinations that don't isolate
cleanly to one subcategory per day the way a single Main dish does):

- Demotion: a declared-liked Main subcategory eaten fewer than
  ADAPTIVE_DEMOTE_MIN_EATEN_COUNT times across his ENTIRE logged history for
  that meal_time (from plan start, not a recent window) -- only judged once
  he has at least ADAPTIVE_MIN_RECALLS_TO_JUDGE total logged occasions for
  that meal_time; someone only 3 days into their plan has nothing removed,
  regardless of what those 3 days looked like. Floored at
  ADAPTIVE_MIN_REMAINING_AFTER_DEMOTE options surviving per meal_time --
  demoting everything under the eaten-count bar would sometimes empty a
  meal_time out entirely (real eating variety means no single subcategory
  reliably clears a count bar), which would break generation for that slot
  the same way a genuinely missing preference does; the highest eaten-count
  candidates among the would-be-demoted ones get rescued back first.
- Promotion: a Main-type subcategory he eats often (>= ADAPTIVE_PROMOTE_AFTER_COUNT
  distinct days) that was never declared as a preference at all -- e.g. he
  eats Chicken curry regularly but never selected "Meat based curry" as a
  liked Main during onboarding.

"Main-type" isn't limited to the official Main1_Main2_Mapping registry: a
subcategory not in that registry still counts as Main-eligible for a given
meal_time if, across the user's ENTIRE logged history for that meal_time,
it's the ONLY thing logged that day on a strict majority of the days it
appears -- e.g. "Egg bread" isn't a registered Main1 code, but if nothing
else is usually logged alongside it, it's evidently functioning as the real
anchor dish, not a side.

A third piece, compute_adaptive_main_combinations, learns this user's real
companion pairings for each Main (what he actually eats alongside it, from
DietRecall). This matters because the global Main1_Main2_Mapping registry has
NO entry at all for a non-registered Main (like "Egg bread" above) --
Functions_Base.py's Main-loop still lets such a Main be selected as a
candidate, but pulls in zero curries/sides/beverages to go with it, since
that expansion is keyed off the registry. The learned combinations are
blended in on top of the registry for every Main (registered or not) via
ModelOptimiser._get_main1_main2_main3_map (routers/plan.py), so his own real
pairings supplement the curated data rather than only covering the gap.

Both compute functions run live, in-memory, on every plan generation --
nothing is persisted to Supabase, so there's no cron job and no table to
keep in sync.
"""
import logging
from datetime import date

from core.supabase import get_supabase, fetch_all_rows

logger = logging.getLogger("backend.services.adaptive_preferences")

ADAPTIVE_MIN_RECALLS_TO_JUDGE = 7
ADAPTIVE_DEMOTE_MIN_EATEN_COUNT = 3
ADAPTIVE_PROMOTE_AFTER_COUNT = 3
ADAPTIVE_MIN_REMAINING_AFTER_DEMOTE = 4
ADAPTIVE_COMBINATION_MIN_COUNT = 2


def _normalize_date(raw: str) -> str | None:
    """DietRecall/RecommendationsBackup/FinalSummary Date values are stored
    in a mix of 'YYYY-MM-DD' and 'DD-MM-YYYY' -- normalize to ISO. Confirmed
    real inconsistency in this project (see routers/status_dashboard.py's
    _normalize_date), not a hypothetical."""
    if not raw:
        return None
    s = str(raw)[:10]
    if len(s) == 10 and s[4] == "-":
        return s
    try:
        dd, mm, yy = s.split("-")
        return f"{yy}-{mm}-{dd}"
    except Exception:
        return None


def _main1_universe(sb) -> set[str]:
    """The full set of subcategory codes the model treats as Main-capable --
    i.e. every code that ever appears as a Main1_Code in the combination
    table. This is the ground truth the model itself uses (see
    Functions_Base.py's _get_main1_main2_main3_map), more reliable than a
    keyword-based guess since a DietRecall-logged item carries no dish_type
    of its own to check directly."""
    rows = fetch_all_rows(lambda: sb.table("Main1_Main2_Mapping Subcategory").select("Main1_Code"))
    return {str(r["Main1_Code"]).strip().upper() for r in rows if r.get("Main1_Code")}


class _UserRecallContext:
    """Shared per-user recall data both compute_adaptive_main_preferences and
    compute_adaptive_main_combinations need, loaded once."""

    def __init__(self, sb, user_id: str):
        self.sb = sb
        self.user_id = user_id
        self.main1_codes = _main1_universe(sb)

        declared_rows = fetch_all_rows(lambda: (
            sb.table("BE_Preference_onboarding")
            .select("meal_time,dish_type,sub_category,Reaction")
            .eq("user_id", user_id)
            .eq("dish_type", "Main")
        ))
        self.declared: dict[str, set[str]] = {}
        for r in declared_rows:
            if r.get("Reaction") == "disliked":
                continue
            meal_time = str(r.get("meal_time") or "").strip().title()
            code = str(r.get("sub_category") or "").strip().upper()
            if meal_time and code:
                self.declared.setdefault(meal_time, set()).add(code)

        recall_rows = fetch_all_rows(lambda: (
            sb.table("DietRecall").select("Date,meal_slot,Food_Name_desc").eq("user_id", user_id)
        ))
        recipe_codes = {str(r["Food_Name_desc"]).strip() for r in recall_rows if r.get("Food_Name_desc")}
        tag_rows = fetch_all_rows(lambda: (
            sb.table("RecipeTagging").select("Recipe_Code,Subcategories").in_("Recipe_Code", list(recipe_codes))
        )) if recipe_codes else []
        recipe_to_subcat = {r["Recipe_Code"]: str(r.get("Subcategories") or "").strip().upper() for r in tag_rows}

        # all_codes_by_day: every subcategory logged on each (meal_time,
        # date), unfiltered -- used to find subcategories that stand alone,
        # and (for combinations) everything actually eaten alongside a Main.
        self.all_codes_by_day: dict[str, dict[date, set[str]]] = {}
        self.recall_days: dict[str, set[date]] = {}
        for r in recall_rows:
            d = _normalize_date(r.get("Date"))
            meal_time = str(r.get("meal_slot") or "").strip().title()
            code = recipe_to_subcat.get(str(r.get("Food_Name_desc") or "").strip())
            if not d or not meal_time:
                continue
            d_parsed = date.fromisoformat(d)
            self.recall_days.setdefault(meal_time, set()).add(d_parsed)
            if code:
                self.all_codes_by_day.setdefault(meal_time, {}).setdefault(d_parsed, set()).add(code)

        # effective_main_codes: main1_codes, PLUS -- per meal_time -- any
        # subcategory that isn't in the official Main1 registry but is,
        # across the user's ENTIRE logged history for that meal_time, the
        # ONLY thing logged that day on a strict majority of the days it
        # appears. A single noisy exception (e.g. one day weeks ago it
        # happened to share a log entry with something else) shouldn't
        # permanently disqualify an otherwise-clear pattern.
        solo_count: dict[str, dict[str, int]] = {}
        total_count: dict[str, dict[str, int]] = {}
        for meal_time, by_day in self.all_codes_by_day.items():
            for codes_that_day in by_day.values():
                solo = len(codes_that_day) == 1
                for c in codes_that_day:
                    total_count.setdefault(meal_time, {})[c] = total_count.setdefault(meal_time, {}).get(c, 0) + 1
                    if solo:
                        solo_count.setdefault(meal_time, {})[c] = solo_count.setdefault(meal_time, {}).get(c, 0) + 1

        self.effective_main_codes: dict[str, set[str]] = {}
        for meal_time, totals in total_count.items():
            solos = solo_count.get(meal_time, {})
            majority_solo = {c for c, n in totals.items() if solos.get(c, 0) > n / 2}
            self.effective_main_codes[meal_time] = self.main1_codes | majority_solo

        # eaten: distinct-day counts per (meal_time, subcategory), for both
        # the demotion eaten-count check and promotion.
        self.eaten: dict[str, dict[str, list[date]]] = {}
        for meal_time, by_day in self.all_codes_by_day.items():
            main_codes_here = self.effective_main_codes.get(meal_time, self.main1_codes)
            for d_parsed, codes_that_day in by_day.items():
                for code in codes_that_day:
                    if code not in main_codes_here:
                        continue
                    self.eaten.setdefault(meal_time, {}).setdefault(code, []).append(d_parsed)


def compute_adaptive_main_preferences(user_id: str) -> list[dict]:
    """Recomputes this user's adaptive Main-preference demotions/promotions,
    live from DietRecall history -- called on every plan generation. Returns
    the list of rows (for logging/visibility) -- an empty list means no
    adaptive corrections apply right now (declared preferences already match
    real behavior closely enough). Purely in-memory: nothing is persisted."""
    sb = get_supabase()
    ctx = _UserRecallContext(sb, user_id)
    results: list[dict] = []

    # Demotion: a declared Main subcategory eaten fewer than
    # ADAPTIVE_DEMOTE_MIN_EATEN_COUNT times across the user's entire logged
    # history for that meal_time (from plan start). Only judged once he has
    # at least ADAPTIVE_MIN_RECALLS_TO_JUDGE total logged occasions for that
    # meal_time -- e.g. someone only 3 days into their plan has nothing
    # removed no matter what those 3 days looked like.
    # Floor: never let demotion take a meal_time below
    # ADAPTIVE_MIN_REMAINING_AFTER_DEMOTE declared options. If demoting
    # everything under the eaten-count bar would drop below that, the
    # highest eaten-count candidates among the would-be-demoted ones are
    # rescued back (closest to actually clearing the bar first) until the
    # floor is met or there's nothing left to rescue.
    for meal_time, codes in ctx.declared.items():
        total_occasions = len(ctx.recall_days.get(meal_time, set()))
        if total_occasions < ADAPTIVE_MIN_RECALLS_TO_JUDGE:
            continue
        eaten_counts = {code: len(set(dates)) for code, dates in ctx.eaten.get(meal_time, {}).items()}

        to_demote = [c for c in codes if eaten_counts.get(c, 0) < ADAPTIVE_DEMOTE_MIN_EATEN_COUNT]
        remaining_after = len(codes) - len(to_demote)
        if remaining_after < ADAPTIVE_MIN_REMAINING_AFTER_DEMOTE:
            rescue_needed = min(
                len(to_demote),
                ADAPTIVE_MIN_REMAINING_AFTER_DEMOTE - remaining_after,
            )
            # Highest eaten-count first -- closest to having actually
            # cleared the bar, so the least arbitrary ones to keep.
            to_demote.sort(key=lambda c: eaten_counts.get(c, 0), reverse=True)
            rescued = set(to_demote[:rescue_needed])
            to_demote = [c for c in to_demote if c not in rescued]

        for code in to_demote:
            eaten_count = eaten_counts.get(code, 0)
            results.append({
                "user_id": user_id,
                "meal_time": meal_time,
                "sub_category_code": code,
                "action": "demote",
                "reason": (
                    f"eaten only {eaten_count}x in {total_occasions} logged "
                    f"{meal_time.lower()}s (needs {ADAPTIVE_DEMOTE_MIN_EATEN_COUNT}+)"
                ),
            })

    # Promotion: a Main-type subcategory eaten often that was never declared.
    for meal_time, by_code in ctx.eaten.items():
        declared_codes = ctx.declared.get(meal_time, set())
        for code, dates in by_code.items():
            if code in declared_codes:
                continue
            distinct_days = len(set(dates))
            if distinct_days >= ADAPTIVE_PROMOTE_AFTER_COUNT:
                results.append({
                    "user_id": user_id,
                    "meal_time": meal_time,
                    "sub_category_code": code,
                    "action": "promote",
                    "reason": f"eaten on {distinct_days} distinct days, never declared as a preference",
                })

    logger.info(
        "Computed adaptive Main preferences for user_id=%s: %d demotions, %d promotions",
        user_id,
        sum(1 for r in results if r["action"] == "demote"),
        sum(1 for r in results if r["action"] == "promote"),
    )
    return results


def compute_adaptive_main_combinations(user_id: str) -> list[dict]:
    """Learns this user's real companion pairings for each effective Main
    subcategory, per meal_time, from DietRecall -- whatever else was logged
    alongside it on the same day, at least ADAPTIVE_COMBINATION_MIN_COUNT
    times. Blended in on top of the global Main1_Main2_Mapping registry (see
    ModelOptimiser._get_main1_main2_main3_map in routers/plan.py) for every
    Main, registered or not -- closes the gap where a Main outside the
    registry (e.g. a promoted subcategory like "Egg bread") would otherwise
    get zero curry/side/beverage candidates to pair with it. Called live on
    every plan generation; purely in-memory, nothing is persisted."""
    sb = get_supabase()
    ctx = _UserRecallContext(sb, user_id)

    pair_counts: dict[tuple[str, str, str], int] = {}
    for meal_time, by_day in ctx.all_codes_by_day.items():
        main_codes_here = ctx.effective_main_codes.get(meal_time, ctx.main1_codes)
        for codes_that_day in by_day.values():
            mains_today = codes_that_day & main_codes_here
            companions_today = codes_that_day - mains_today
            for main_code in mains_today:
                for companion_code in companions_today:
                    key = (meal_time, main_code, companion_code)
                    pair_counts[key] = pair_counts.get(key, 0) + 1

    results = [
        {
            "user_id": user_id,
            "meal_time": meal_time,
            "main_subcategory_code": main_code,
            "companion_subcategory_code": companion_code,
            "co_occurrence_count": count,
        }
        for (meal_time, main_code, companion_code), count in pair_counts.items()
        if count >= ADAPTIVE_COMBINATION_MIN_COUNT
    ]

    logger.info(
        "Recomputed adaptive Main combinations for user_id=%s: %d learned pairing(s)",
        user_id, len(results),
    )
    return results
