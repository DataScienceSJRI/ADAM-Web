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
from datetime import date, timedelta

from core.supabase import get_supabase, fetch_all_rows

logger = logging.getLogger("backend.services.adaptive_preferences")

ADAPTIVE_MIN_RECALLS_TO_JUDGE = 7
ADAPTIVE_DEMOTE_MIN_EATEN_COUNT = 3
ADAPTIVE_PROMOTE_AFTER_COUNT = 3
ADAPTIVE_MIN_REMAINING_AFTER_DEMOTE = 4


def _plural_meal_time(meal_time: str) -> str:
    """"Breakfast"->"breakfasts", "Snacks"->"snacks" (already plural, no
    double s) -- used only in a log-visible demotion reason string."""
    lower = meal_time.lower()
    return lower if lower.endswith("s") else f"{lower}s"
ADAPTIVE_COMBINATION_MIN_COUNT = 2

DIETRECALL_DOMINANT_WINDOW_DAYS = 42
DIETRECALL_DOMINANT_MIN_COUNT = 10


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
                    f"{_plural_meal_time(meal_time)} (needs {ADAPTIVE_DEMOTE_MIN_EATEN_COUNT}+)"
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


def _compute_dietrecall_counts(
    user_id: str,
    window_days: int,
) -> list[dict]:
    """Shared core for compute_dietrecall_dominant_preferences and
    compute_dietrecall_staple_preferences: every (meal_slot, EXACT recipe)
    pair logged in the last window_days, with its raw count -- unfiltered by
    any threshold, so callers can slice different bands (an overwhelmingly
    dominant single dish vs. a merely-frequent staple) out of the same
    underlying counts without re-querying. See
    compute_dietrecall_dominant_preferences for the full rationale (exact
    recipe_code not subcategory, recent window, ADAM_Recipes==1 only)."""
    sb = get_supabase()
    cutoff = date.today() - timedelta(days=window_days)

    # Filtered in Python, not via a server-side .gte("Date", ...) -- Date is
    # a text column with a confirmed mix of 'YYYY-MM-DD' and 'DD-MM-YYYY'
    # rows in this project (see _normalize_date above), so a raw string
    # comparison would silently misorder/misfilter the DD-MM-YYYY rows.
    all_recall_rows = fetch_all_rows(lambda: (
        sb.table("DietRecall").select("Date,meal_slot,Food_Name_desc").eq("user_id", user_id)
    ))
    recall_rows = []
    for r in all_recall_rows:
        d = _normalize_date(r.get("Date"))
        if d and date.fromisoformat(d) >= cutoff:
            recall_rows.append(r)
    if not recall_rows:
        return []

    recipe_codes = {
        str(r["Food_Name_desc"]).strip().upper() for r in recall_rows if r.get("Food_Name_desc")
    }
    if not recipe_codes:
        return []

    adam_rows = fetch_all_rows(lambda: sb.table("Rec_ADAM_yes_no").select("Recipe_Code,ADAM_Recipes"))
    adam_codes = {
        str(r["Recipe_Code"]).strip().upper() for r in adam_rows
        if r.get("Recipe_Code") and str(r.get("ADAM_Recipes")) == "1"
    }
    eligible_codes = recipe_codes & adam_codes
    if not eligible_codes:
        return []

    tag_rows = fetch_all_rows(lambda: (
        sb.table("RecipeTagging").select("Recipe_Code,Subcategories").in_("Recipe_Code", list(eligible_codes))
    ))
    recipe_to_subcat = {
        str(r["Recipe_Code"]).strip().upper(): str(r.get("Subcategories") or "").strip().upper()
        for r in tag_rows
    }

    counts: dict[tuple[str, str], int] = {}
    for r in recall_rows:
        code = str(r.get("Food_Name_desc") or "").strip().upper()
        if code not in eligible_codes:
            continue
        meal_time = str(r.get("meal_slot") or "").strip().title()
        if not meal_time:
            continue
        key = (meal_time, code)
        counts[key] = counts.get(key, 0) + 1

    return [
        {
            "user_id": user_id,
            "meal_time": meal_time,
            "recipe_code": code,
            "sub_category_code": recipe_to_subcat.get(code),
            "count": count,
            "window_days": window_days,
        }
        for (meal_time, code), count in counts.items()
    ]


def compute_dietrecall_dominant_preferences(
    user_id: str,
    window_days: int = DIETRECALL_DOMINANT_WINDOW_DAYS,
    min_count: int = DIETRECALL_DOMINANT_MIN_COUNT,
) -> list[dict]:
    """Detects a strongly repeated RECENT eating pattern per (meal_slot,
    EXACT recipe) -- e.g. a user who has logged the exact same rice dish for
    lunch on most of his last 6 weeks' entries. Keyed by the specific
    recipe code, not its subcategory: confirmed for real on A003_ANISH that
    subcategory-level aggregation actively picks the wrong dish -- his
    Lunch/Main "E2A" (plain rice/stewed rice) pattern of 20 logged entries
    was 18 of those literally "Rice" (A000445, GL=40.4, the WORST-GL option
    among E2A's 6 recipes), yet subcategory-level bonus/relaxation let the
    solver settle on "Basmati rice" (R000170, GL=14.2, best-GL, but never
    once actually logged) instead -- cheaper by the objective, not what he
    actually eats. Deliberately scoped to a recent window (unlike
    compute_adaptive_main_preferences' all-time history) so a habit that's
    since changed doesn't lock in a stale bonus, and to ADAM_Recipes == 1
    codes only (Rec_ADAM_yes_no) -- the same catalog the model actually
    draws candidates from, so a DietRecall entry logged against a USDA-only
    reference code can't produce a bonus toward something the model could
    never offer as a candidate.

    sub_category_code is still resolved and returned (services/data_loader.py
    uses it to widen the candidate pool with the recipe's ADAM-catalog
    siblings, as headroom in case the exact recipe alone can't cover every
    day for a genuine GL/nutrition reason) but the bonus/cap-relaxation
    itself (see lp_optimizer.py's dietrecall_dominant_bonus) targets the
    exact recipe_code, not the whole subcategory.

    Returned as a soft-preference signal feeding BOTH an objective bonus AND
    a hard per-slot day-floor + variety-cap relaxation in lp_optimizer.py:
    exceeding min_count means the solver is required to serve that exact
    recipe at that meal_slot on several days, not just nudged toward it. Only
    meant for a genuinely overwhelming pattern (min_count defaults to 10) --
    see compute_dietrecall_staple_preferences for the much more common case
    of a merely-frequent item that should never carry a hard requirement."""
    results = [
        r for r in _compute_dietrecall_counts(user_id, window_days)
        if r["count"] > min_count
    ]
    logger.info(
        "Computed diet-recall dominant preferences for user_id=%s (last %d days): %s",
        user_id, window_days,
        [(r["meal_time"], r["recipe_code"], r["sub_category_code"], r["count"]) for r in results],
    )
    return results


# A much lower bar than DIETRECALL_DOMINANT_MIN_COUNT (10), by design: most
# people's real eating pattern is several moderately-frequent staples (rice,
# curd, a usual sambhar/chutney), not one overwhelmingly dominant dish.
# Confirmed for real on A009_PRAKASH: ~88% of his logged GL came from dishes
# outside that day's plan entirely, none of which individually crossed the
# dominant threshold (his top items logged only 5-8 times in 42 days) --
# this band is deliberately capped at DIETRECALL_DOMINANT_MIN_COUNT so an
# item that graduates into genuinely dominant territory is only ever
# governed by ONE of the two bonuses, not both at once.
DIETRECALL_STAPLE_MIN_COUNT = 3


def compute_dietrecall_staple_preferences(
    user_id: str,
    window_days: int = DIETRECALL_DOMINANT_WINDOW_DAYS,
    min_count: int = DIETRECALL_STAPLE_MIN_COUNT,
    max_count: int = DIETRECALL_DOMINANT_MIN_COUNT,
) -> list[dict]:
    """Detects a merely-frequent (meal_slot, EXACT recipe) pattern -- logged
    more than min_count but not enough to qualify as fully dominant. Feeds
    ONLY a soft objective bonus in lp_optimizer.py (ds["dietrecall_staple_
    bonus"]) -- deliberately NEVER a hard day-floor or variety-cap
    relaxation the way compute_dietrecall_dominant_preferences' result is.
    Applying a hard requirement at this much lower, much more common bar
    would multiply exactly the kind of Infeasible failure already fixed for
    A006_RAJENDRA/A008_NAGABHUSHA (multiple hard floors competing for the
    same day budget) -- a soft bonus can't break feasibility by
    construction, so it's safe to apply broadly across every user."""
    results = [
        r for r in _compute_dietrecall_counts(user_id, window_days)
        if min_count < r["count"] <= max_count
    ]
    logger.info(
        "Computed diet-recall staple preferences for user_id=%s (last %d days): %s",
        user_id, window_days,
        [(r["meal_time"], r["recipe_code"], r["sub_category_code"], r["count"]) for r in results],
    )
    return results


DIETRECALL_SUBCAT_MIN_COUNT = 2


def _diet_tag_from_row(row: dict | None) -> str:
    """Classifies a RecipeTagging row into "egg" / "veg" / "non-veg".
    Ovo-vegetarian==1 takes priority over Vegetarian -- this dataset tags
    several egg dishes BOTH Non-vegetarian=1 and Ovo-vegetarian=1 at once,
    and "contains egg" is the more specific, useful signal here than the
    inconsistent non-veg flag. Shared by compute_dietrecall_subcategory_bonus
    and compute_dietrecall_diettag_floor so both sides of the egg-vs-veg
    split (the LP's Diet_Tag column included) agree on the same rule."""
    if row is None:
        return "other"
    if str(row.get("Ovo-vegetarian") or "").strip() == "1":
        return "egg"
    if str(row.get("Vegetarian") or "").strip() == "1":
        return "veg"
    return "non-veg"


def compute_dietrecall_subcategory_bonus(
    user_id: str,
    window_days: int = DIETRECALL_DOMINANT_WINDOW_DAYS,
    min_count: int = DIETRECALL_SUBCAT_MIN_COUNT,
) -> list[dict]:
    """Same recall data as compute_dietrecall_dominant_preferences/
    compute_dietrecall_staple_preferences, but aggregated by (meal_time,
    sub_category_code) across every recipe code that shares it, instead of
    one exact recipe -- "how often does he eat something from THIS
    category", not "how often does he eat THIS EXACT dish".

    Confirmed for real on A003_ANISH that exact-recipe matching alone misses
    most of the picture: his diet-recall-to-plan overlap is only ~9-12% at
    the exact-recipe level, but ~45-50% at the subcategory level -- the
    model is already landing on the right food CATEGORY roughly half the
    time, it just usually picks a different specific dish within it (the
    GL-cheapest sibling, not the one he actually eats). This feeds a soft,
    subcategory-wide bonus in lp_optimizer.py (ds["dietrecall_subcat_bonus"])
    that nudges the objective toward his frequently-eaten categories as a
    whole, raising the odds some member of that category (not necessarily
    the one exact code) gets picked more consistently.

    Deliberately a SEPARATE signal from the exact-recipe staple/dominant
    bonuses above, not a replacement -- those still target the specific dish
    once a category is already a strong enough match on its own. Soft only:
    no hard floor, no variety-cap relaxation, so it can't cause Infeasible
    the way a hard requirement could. min_count defaults low (2) since a
    whole category naturally accumulates counts faster than one exact
    recipe -- this still only fires on a real, repeated pattern, not a
    single one-off.

    Deliberately does NOT reuse _compute_dietrecall_counts here, unlike the
    exact-recipe bonuses above -- that helper pre-filters to ADAM_Recipes==1
    codes BEFORE resolving a subcategory, which is right for a bonus that
    targets one exact recipe (no point biasing toward a dish the model could
    never actually serve), but wrong for a category-level signal: a logged
    "Egg bread" on a USDA-only reference code still tells you he eats eggy
    breakfasts often, even though that exact code isn't recommendable.
    Confirmed for real on A003_ANISH: his logged "Egg bread" alone (11x) was
    being silently dropped before ever reaching the subcategory count,
    undercounting the real pattern -- the subcategory is resolved from EVERY
    logged code here, eligible or not; only the resulting bonus/pool-
    widening (in lp_optimizer.py/data_loader.py) is restricted to ADAM-
    eligible siblings, so nothing non-recommendable can ever actually get
    served."""
    sb = get_supabase()
    cutoff = date.today() - timedelta(days=window_days)

    all_recall_rows = fetch_all_rows(lambda: (
        sb.table("DietRecall").select("Date,meal_slot,Food_Name_desc").eq("user_id", user_id)
    ))
    recall_rows = []
    for r in all_recall_rows:
        d = _normalize_date(r.get("Date"))
        if d and date.fromisoformat(d) >= cutoff:
            recall_rows.append(r)

    all_codes = {
        str(r["Food_Name_desc"]).strip().upper() for r in recall_rows if r.get("Food_Name_desc")
    }
    tag_rows = fetch_all_rows(lambda: (
        sb.table("RecipeTagging")
        .select('Recipe_Code,Subcategories,Vegetarian,"Ovo-vegetarian"')
        .in_("Recipe_Code", list(all_codes))
    )) if all_codes else []
    recipe_to_subcat = {
        str(r["Recipe_Code"]).strip().upper(): str(r.get("Subcategories") or "").strip().upper()
        for r in tag_rows
    }
    # Diet tag ("egg" / "veg" / "non-veg") per logged code, so the bonus/
    # floor built from this can target "the same subcategory AND the same
    # egg-or-not profile he actually eats" rather than the whole
    # subcategory indiscriminately. Confirmed necessary for real on
    # A003_ANISH: a plain floor on G1C ("bread/toast" subcategory) got
    # satisfied by a non-egg paneer sandwich instead of the egg sandwich he
    # actually logged, because the floor only required SOME G1C item, not
    # specifically an egg one. Ovo-vegetarian==1 takes priority over
    # Vegetarian -- this dataset tags several egg dishes BOTH
    # Non-vegetarian=1 and Ovo-vegetarian=1 at once, and "contains egg" is
    # the more specific, more useful signal than the inconsistent
    # non-veg flag here.
    recipe_to_tagrow = {str(r["Recipe_Code"]).strip().upper(): r for r in tag_rows}

    counts: dict[tuple[str, str, str], int] = {}
    meal_totals: dict[str, int] = {}
    for r in recall_rows:
        code = str(r.get("Food_Name_desc") or "").strip().upper()
        subcat = recipe_to_subcat.get(code)
        meal_time = str(r.get("meal_slot") or "").strip().title()
        if not code or not meal_time:
            continue
        # Every logged entry at this meal_time counts toward its total
        # (the proportion's denominator), regardless of whether its
        # subcategory resolved -- an unresolved code still really was eaten
        # at that meal_time.
        meal_totals[meal_time] = meal_totals.get(meal_time, 0) + 1
        if not subcat:
            continue
        diet_tag = _diet_tag_from_row(recipe_to_tagrow.get(code))
        key = (meal_time, subcat, diet_tag)
        counts[key] = counts.get(key, 0) + 1

    results = [
        {
            "user_id": user_id,
            "meal_time": meal_time,
            "sub_category_code": subcat,
            "diet_tag": diet_tag,
            "count": count,
            "meal_total": meal_totals.get(meal_time, count),
            "proportion": count / meal_totals.get(meal_time, count),
            "window_days": window_days,
        }
        for (meal_time, subcat, diet_tag), count in counts.items()
        if count >= min_count
    ]
    logger.info(
        "Computed diet-recall subcategory bonus for user_id=%s (last %d days): %s",
        user_id, window_days,
        [(r["meal_time"], r["sub_category_code"], r["diet_tag"], r["count"]) for r in results],
    )
    return results


def compute_dietrecall_diettag_floor(
    user_id: str,
    window_days: int = DIETRECALL_DOMINANT_WINDOW_DAYS,
    top_n: int = 2,
    min_meal_total: int = 5,
) -> list[dict]:
    """For each meal_time, classifies every logged DietRecall entry into a
    diet_tag ("egg"/"veg"/"non-veg", via _diet_tag_from_row) across EVERY
    subcategory at once, and returns the top `top_n` diet_tags by how often
    they were logged at that meal_time, each with its share of that
    meal_time's total.

    Meant to drive a day-count floor in lp_optimizer.py that targets the
    overall COMPOSITION of a meal_time, not any one subcategory: if half of
    someone's logged breakfasts are egg-based (across however many
    different egg dishes/subcategories), roughly half the new week's
    breakfasts should serve something egg-based too -- from ANY
    subcategory, not pinned to the one he happened to log most. This is a
    different signal from compute_dietrecall_subcategory_bonus (which
    targets one specific subcategory's egg-or-not profile); this one
    targets the meal_time's overall egg/veg/non-veg split.

    Deliberately capped to the top `top_n` patterns per meal_time (not
    every diet_tag ever logged) -- this is about matching the DOMINANT
    patterns, not reproducing every observed value down to a single rare
    non-veg day. A meal_time with fewer than `min_meal_total` total logged
    entries is skipped entirely -- too little data for a proportion to mean
    anything."""
    sb = get_supabase()
    cutoff = date.today() - timedelta(days=window_days)

    all_recall_rows = fetch_all_rows(lambda: (
        sb.table("DietRecall").select("Date,meal_slot,Food_Name_desc").eq("user_id", user_id)
    ))
    recall_rows = []
    for r in all_recall_rows:
        d = _normalize_date(r.get("Date"))
        if d and date.fromisoformat(d) >= cutoff:
            recall_rows.append(r)

    all_codes = {
        str(r["Food_Name_desc"]).strip().upper() for r in recall_rows if r.get("Food_Name_desc")
    }
    tag_rows = fetch_all_rows(lambda: (
        sb.table("RecipeTagging")
        .select('Recipe_Code,Vegetarian,"Ovo-vegetarian"')
        .in_("Recipe_Code", list(all_codes))
    )) if all_codes else []
    recipe_to_tagrow = {str(r["Recipe_Code"]).strip().upper(): r for r in tag_rows}

    meal_totals: dict[str, int] = {}
    meal_diettag_counts: dict[tuple[str, str], int] = {}
    for r in recall_rows:
        code = str(r.get("Food_Name_desc") or "").strip().upper()
        meal_time = str(r.get("meal_slot") or "").strip().title()
        if not code or not meal_time:
            continue
        diet_tag = _diet_tag_from_row(recipe_to_tagrow.get(code))
        meal_totals[meal_time] = meal_totals.get(meal_time, 0) + 1
        key = (meal_time, diet_tag)
        meal_diettag_counts[key] = meal_diettag_counts.get(key, 0) + 1

    results = []
    for meal_time, total in meal_totals.items():
        if total < min_meal_total:
            continue
        tag_counts = sorted(
            ((tag, c) for (mt, tag), c in meal_diettag_counts.items() if mt == meal_time),
            key=lambda t: -t[1],
        )[:top_n]
        for diet_tag, count in tag_counts:
            results.append({
                "user_id": user_id,
                "meal_time": meal_time,
                "diet_tag": diet_tag,
                "count": count,
                "meal_total": total,
                "proportion": count / total,
                "window_days": window_days,
            })
    logger.info(
        "Computed diet-recall diet-tag floor proportions for user_id=%s (last %d days): %s",
        user_id, window_days,
        [(r["meal_time"], r["diet_tag"], round(r["proportion"], 2)) for r in results],
    )
    return results
