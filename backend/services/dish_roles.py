"""Single source of truth for which dish ROLE a subcategory may play in a
Breakfast/Lunch/Dinner combination.

Two classes, decided purely from the subcategory code (a subcategory's
MainCategoryCode is always its first two characters, e.g. C1A -> C1):

- ANCHOR (Main only): the staple / carb base of the meal -- dosa, idli,
  upma, poha, paratha (A1), rotis/chapathi/puri (C1), seasoned/plain/curd
  rice and khichdi (E1/E2/E3), porridge/cereals (L1), plus the other
  carb-based or complete-meal bases (breads/sandwich, rolls, noodles,
  pizza/pasta/burger, sushi, burritos, rice and beans). An anchor is ONLY ever the Main
  of a meal -- never a Main 2 / Main 3 / Optional companion -- so a meal can
  never end up with two staples (e.g. Onion rava bhakri + Chapathi) or with
  a staple tacked on as an "extra".

- COMPANION (Main 2 / Main 3 / Optional only, whenever an anchor Main is
  available for that meal_time): curries, dals, sambar, chutneys, dry
  sabzis, raita, pickles, salads/sweetcorn/sprouts, sundal, soup, chaat,
  fruit, egg sides, beverages, etc. Which of the three companion roles it
  takes is decided per Main by the Main1_Main2_Mapping registry (plus the
  user's learned pairings), not here.

Confirmed necessary for real on A006_RAJENDRA (week 11): "Onion slices"
(G2A, a declared Lunch Main option) won the Main slot with a chutney as
Main 2 and Chapathi riding along as an Optional extra; "Sweet corn" (G2A)
won Main with a curry and no carb at all; and "Onion rava bhakri" (C1B)
was served together with Chapathi (C1A) as a second staple.
"""
from __future__ import annotations

import pandas as pd

ANCHOR_MAIN_CATEGORIES = frozenset({"A1", "C1", "E1", "E2", "E3", "L1"})

ANCHOR_SUBCATEGORIES = frozenset({
    "G1C",  # Sandwich / masala toast / yeast bread
    "G2E",  # Rolls
    "G2G",  # Breads
    "G2H",  # Maggie / cup noodles
    "I1A", "I1C", "I1D", "I1E", "I1G",  # pizza, pasta, pancakes/waffles, burger, bagel/croissant
    "J1A", "J1B",                       # noodles/fried rice, sushi
    "K1A", "K1C",                       # burritos/tacos, rice and beans
    # Deliberately NOT anchors: I1B/I1I/I1J/I1K/I1H (mixed meat/poultry/
    # fish/veg dishes -- butter chicken, beef gravy, stewed fish...),
    # J1C/J1D/J1E (oriental meat/seafood/veg-in-sauce dishes) and K1B. Those
    # are curries/gravies eaten WITH a staple, i.e. companions. Confirmed for
    # real on A011_ARUN: "Egg omelette" is tagged J1D and is his everyday
    # side to bread toast -- treating J1D as a staple dropped it.
})

# ACCOMPANIMENT (Optional only): small add-ons that complete a meal but are
# never its gravy/side -- papad, pickles, sweets/payasam, fruit, nuts and
# drinks. Without this, a learned pairing could put papad in the single
# Main 2 slot that the dal/sambar/curry needs. Confirmed for real on
# A009_PRAKASH: "Rice + Papad + Carrot slices" lunches with no gravy at all,
# because his rice+papad habit taught the system papad as rice's Main 2.
# Curd/buttermilk/yogurt (H1A, H1B, H5F) are deliberately NOT here: with
# pulao/biryani/khichdi they genuinely are the accompaniment-gravy (raita,
# curd), and the registry places them as Main 2 for those Mains.
ACCOMPANIMENT_MAIN_CATEGORIES = frozenset({"F3", "H2", "H3", "H4"})  # pickles, beverages, sweets, ghee/butter
ACCOMPANIMENT_SUBCATEGORIES = frozenset({
    "H1C",                                # Papad
    "G1A", "G1B", "G1E", "G1F", "G1G",    # tikki, bajji/vada/pakora, appetizers, nachos, fries
    "G2S", "G2O", "G2P", "G2I",           # fruit, berries, dried fruit, nuts/seeds
    "H5A", "H5B", "H5C", "H5D", "H5E",    # coffee/tea/milk drinks
})

MAIN_MEAL_TIMES = frozenset({"Breakfast", "Lunch", "Dinner"})
COMPANION_ROLES = ("Main 2", "Main 3", "Optional")


def normalize_subcat(code) -> str:
    return str(code or "").strip().upper()


def is_anchor(subcat_code) -> bool:
    """True if this subcategory is a staple/carb base that may only ever be
    the Main of a meal."""
    c = normalize_subcat(subcat_code)
    if not c:
        return False
    return c[:2] in ANCHOR_MAIN_CATEGORIES or c in ANCHOR_SUBCATEGORIES


def is_accompaniment(subcat_code) -> bool:
    """True if this subcategory may only ever be an Optional add-on (never
    the Main 2 gravy or Main 3 side of a meal)."""
    c = normalize_subcat(subcat_code)
    if not c:
        return False
    return c[:2] in ACCOMPANIMENT_MAIN_CATEGORIES or c in ACCOMPANIMENT_SUBCATEGORIES


def enforce_dish_roles(candidates, subcat_col: str = "Recipe_Category", recall_pairs=None):
    """Applies the role rules to an LP candidate table (one row per
    Recipe x Meal_Time x Dish_Type x Preference_Row_ID). Returns
    (filtered_candidates, stats_dict).

    Rule 1: an anchor recipe is dropped from every companion role
            (Main 2 / Main 3 / Optional) at Breakfast/Lunch/Dinner.
    Rule 2: at a Breakfast/Lunch/Dinner meal_time that has at least one
            anchor Main candidate, every non-anchor Main candidate is
            dropped -- the Main must be the staple. (A meal_time whose
            candidates are entirely non-anchor, e.g. a fruit/sprouts-only
            breakfast, is left untouched so it still has a Main.)
    Rule 3: accompaniments in Main 2 / Main 3 are re-labelled Optional.
    Rule 4: a Main with no companion at all is dropped, UNLESS the user
            has actually logged that exact recipe at that meal_time in
            DietRecall (recall_pairs: set of (Meal_Time, Recipe_Code)).

    Companions whose own combination lost its Main through Rule 2 are left
    in place; the LP's per-Preference_Row_ID pairing constraints already
    force a Main-less combination's companions to zero.
    """
    if candidates is None or candidates.empty:
        return candidates, {}
    if subcat_col not in candidates.columns:
        subcat_col = "Preferred_SubCategory_code"
    meal_time = candidates["Meal_Time"].astype(str).str.strip().str.title()
    dish_type = candidates["Dish_Type"].astype(str).str.strip()
    anchor = candidates[subcat_col].map(is_anchor)
    in_main_meal = meal_time.isin(MAIN_MEAL_TIMES)

    drop_anchor_as_companion = in_main_meal & anchor & dish_type.isin(COMPANION_ROLES)

    meal_times_with_anchor_main = set(meal_time[in_main_meal & anchor & (dish_type == "Main")])
    drop_nonanchor_main = (
        in_main_meal
        & ~anchor
        & (dish_type == "Main")
        & meal_time.isin(meal_times_with_anchor_main)
    )

    drop = drop_anchor_as_companion | drop_nonanchor_main

    # Rule 3: an accompaniment (papad, pickle, sweet, fruit, nuts, drink) in
    # a Main 2 / Main 3 role is re-labelled Optional within the SAME
    # combination, so it can still come with that Main but never occupies
    # the gravy/side slot. Duplicates created by the re-label are dropped.
    relabel = in_main_meal & ~drop & dish_type.isin(("Main 2", "Main 3")) & candidates[subcat_col].map(is_accompaniment)
    out = candidates[~drop].copy()
    relabel = relabel[~drop]
    if relabel.any():
        out.loc[relabel, "Dish_Type"] = "Optional"
        out = out.drop_duplicates(subset=["Meal_Time", "Dish_Type", "Recipe_Code", "Preference_Row_ID"])

    # Rule 4: a Breakfast/Lunch/Dinner combination that is ONLY a Main (no
    # Main 2 / Main 3 / Optional candidate at all) would be served as a
    # bare staple -- e.g. "Vangi bath" alone at Dinner, "only carbs"
    # (A009_PRAKASH; he only ever logged vangi bath at Lunch, with rice/sambar).
    # Typically a diet-recall staple injected without companions. Dropped
    # whenever that meal_time still has at least one combination that does
    # carry companions, so a meal_time is never emptied out.
    lone_main_groups_dropped = 0
    if not out.empty and "Preference_Row_ID" in out.columns:
        mt_out = out["Meal_Time"].astype(str).str.strip().str.title()
        key = list(zip(mt_out, out["Preference_Row_ID"].astype(str)))
        key_s = pd.Series(key, index=out.index)
        dts_by_group = out.groupby(key_s)["Dish_Type"].agg(lambda s: set(s.astype(str).str.strip()))
        lone = {k for k, dts in dts_by_group.items() if dts == {"Main"} and k[0] in MAIN_MEAL_TIMES}
        with_companions_mts = {k[0] for k, dts in dts_by_group.items() if "Main" in dts and len(dts) > 1}
        lone = {k for k in lone if k[0] in with_companions_mts}
        if lone:
            lone_mask = key_s.isin(lone)
            # Per explicit request: a bare staple that is in this user's
            # own diet recall at this meal_time may still come -- it's how
            # he really eats it (e.g. A009's Lemon rice, logged alone at
            # Breakfast). Only recipes never logged there are dropped.
            pairs = {(str(m).strip().title(), str(c).strip().upper()) for m, c in (recall_pairs or set())}
            in_recall = pd.Series(
                [(m, str(c).strip().upper()) in pairs for m, c in zip(mt_out, out["Recipe_Code"])],
                index=out.index,
            )
            drop_lone = lone_mask & ~in_recall
            lone_main_groups_dropped = int(drop_lone.sum())
            out = out[~drop_lone].copy()

    stats = {
        "lone_main_recipes_dropped": lone_main_groups_dropped,
        "accompaniment_relabelled_optional": int(relabel.sum()),
        "anchor_as_companion_dropped": int(drop_anchor_as_companion.sum()),
        "nonanchor_main_dropped": int(drop_nonanchor_main.sum()),
        "nonanchor_main_dropped_subcats": sorted(
            set(candidates.loc[drop_nonanchor_main, subcat_col].astype(str))
        ),
        "anchor_as_companion_dropped_subcats": sorted(
            set(candidates.loc[drop_anchor_as_companion, subcat_col].astype(str))
        ),
    }
    return out, stats
