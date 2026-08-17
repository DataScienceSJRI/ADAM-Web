"""
Fetches all dataset tables from Supabase and returns the same dict-of-DataFrames
structure that Functions_Base.load_data() would produce from local CSVs.
"""

import logging
import time
import pandas as pd
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional
from core.supabase import get_supabase

logger = logging.getLogger("backend.data_loader")


_FETCH_LIMIT = 5000  # Supabase PostgREST default max is 1000; raise to cover full datasets

# Tables that do not change during a plan-generation run. Cached per worker
# process so concurrent jobs do not repeatedly pull the full catalog.
_CACHE_TTL = 3600
_STATIC_TABLES = {
    "Recipe", "RecipeTagging", "SubCategory", "SubCategory_Onboarding",
    "DataModelling", "BaseEar", "BaseTul", "Main1_Main2_Mapping Subcategory",
    "Rec_ADAM_yes_no", "SubCategory_foods_GI_GL", "Recipes_ingredient",
    "USER_Recipes_name_changed", "Millet_Recipes",
}
_cache: dict[str, tuple[pd.DataFrame, float]] = {}

# Manual "shadow" additions to Main1_Main2_Mapping Subcategory (the combination
# table): subcategories with no entry anywhere in the underlying sheet yet, but
# that clearly belong wherever a close existing subcategory already appears (same
# dish role). Applied immediately after every fetch of this table so both plan
# generation (services/data_loader.load_data_from_supabase) and swap suggestions
# (services/replacement._new_mapping_subcategories) see the patch without the
# underlying sheet needing manual edits. If the curator later adds one of the
# shadowed codes to a new row by hand, the added code follows automatically —
# this isn't a frozen snapshot of today's rows.
#
# (code_to_add, codes_it_shadows)
_COMBINATION_TABLE_NAME = "Main1_Main2_Mapping Subcategory"
_COMBINATION_SHADOW_RULES: list[tuple[str, tuple[str, ...]]] = [
    # Yogurt (H5F): no entry anywhere. Buttermilk (H1A) / Curd (H1B) are the same
    # dairy-side role and are already correctly placed throughout the table.
    ("H5F", ("H1A", "H1B")),
    # "beverages" (H2E): no entry anywhere. Shadows the existing drink family
    # (Black Coffee, Milk Coffee, Milk, Turmeric milk).
    ("H2E", ("H5A", "H5B", "H5C", "H5D")),
]
_COMBINATION_COLUMNS = ("Main2_Code", "Main3_Code", "Optional")


def apply_combination_table_overrides(rows: list[dict]) -> list[dict]:
    """
    Apply _COMBINATION_SHADOW_RULES to raw Main1_Main2_Mapping Subcategory rows
    (list of dicts, the shape Supabase returns before conversion to a DataFrame).
    Returns a new list of new dicts — does not mutate the input.
    """
    patched = [dict(row) for row in rows]
    for row in patched:
        for col in _COMBINATION_COLUMNS:
            codes = [c.strip() for c in str(row.get(col) or "").split(",") if c.strip()]
            codes_upper = {c.upper() for c in codes}
            for add_code, shadow_codes in _COMBINATION_SHADOW_RULES:
                if add_code.upper() in codes_upper:
                    continue
                if any(sc in codes_upper for sc in shadow_codes):
                    codes.append(add_code)
                    codes_upper.add(add_code.upper())
            row[col] = ", ".join(codes)
    return patched


def _fetch(table: str, filters: Optional[dict] = None, _retries: int = 3) -> pd.DataFrame:
    """Fetch all rows using pagination, with retries on transient connection errors."""
    for attempt in range(1, _retries + 1):
        try:
            supabase = get_supabase()
            all_rows = []
            batch_size = 1000
            start = 0

            while True:
                query = supabase.table(table).select("*").range(start, start + batch_size - 1)

                if filters:
                    for col, val in filters.items():
                        query = query.eq(col, val)

                response = query.execute()
                data = response.data

                if not data:
                    break

                all_rows.extend(data)

                if len(data) < batch_size:
                    break

                start += batch_size

            if table == _COMBINATION_TABLE_NAME:
                all_rows = apply_combination_table_overrides(all_rows)

            return pd.DataFrame(all_rows)

        except Exception as e:
            print(f"[WARN] Failed to fetch {table} (attempt {attempt}/{_retries}): {e}")
            if attempt < _retries:
                time.sleep(2 ** attempt)  # 2s, 4s backoff
            else:
                return pd.DataFrame()


def _fetch_nonveg_code_to_items(sb) -> dict[str, set[str]]:
    """
    Nonveg_Options.Codes -> the set of Food Item names (Chicken/Beef/Pork/Fish/
    Goat/sheep/Egg) that code belongs to. A handful of codes (mixed-meat broth
    ingredients etc.) belong to more than one item, so this must be set-valued —
    a single-value map would silently pick the wrong item for those.

    Codes match against Recipes_ingredient in one of two columns depending on
    recipe source: ADAM-native recipes via Food_Code (alpha-prefixed, e.g.
    "N001"), USDA-imported recipes via Ing_Id (plain numeric, e.g. "4542").
    """
    rows = sb.table("Nonveg_Options").select("*").execute().data or []
    code_to_items: dict[str, set[str]] = {}
    for row in rows:
        # lowercased for case-insensitive matching against non_veg_types — the
        # source table itself is inconsistent ("Chicken" vs "sheep")
        item = str(row.get("Food Item") or "").strip().lower()
        if not item:
            continue
        for code in str(row.get("Codes") or "").split(","):
            code = code.strip().upper()
            if code:
                code_to_items.setdefault(code, set()).add(item)
    return code_to_items


def get_recipes_excluded_by_nonveg_types(non_veg_types: list) -> set[str]:
    """
    Recipe codes to exclude because they contain a non-veg ingredient OUTSIDE the
    user's selected non_veg_types (e.g. selected ["Goat", "Fish", "Pork"] excludes
    any recipe with a Chicken, Beef, sheep, or Egg ingredient) — even if the same
    recipe ALSO contains an allowed ingredient. A recipe made of both chicken and
    pork is excluded when only Pork is selected, since it isn't exclusively made
    of selected types.

    Only meant to restrict the non-veg portion of the catalog on top of the base
    Vegetarian/Ovo-vegetarian diet filter — vegetarian-flagged recipes are never
    looked at here, callers should apply this only to already non-veg-filtered
    candidates. Returns an empty set (no restriction) when non_veg_types is
    empty/missing, matching today's behavior for the vast majority of users who
    haven't set this onboarding field yet.
    """
    selected = {str(t).strip().lower() for t in (non_veg_types or []) if str(t).strip()}
    if not selected:
        return set()

    sb = get_supabase()
    code_to_items = _fetch_nonveg_code_to_items(sb)
    if not code_to_items:
        return set()

    ing_df = _fetch_cached("Recipes_ingredient")
    if ing_df.empty or "Recipe_Code" not in ing_df.columns:
        return set()

    excluded: set[str] = set()
    for col in ("Food_Code", "Ing_Id"):
        if col not in ing_df.columns:
            continue
        codes = ing_df[col].astype(str).str.strip().str.upper()
        matched_mask = codes.isin(code_to_items.keys())
        if not matched_mask.any():
            continue
        matched = ing_df.loc[matched_mask, ["Recipe_Code"]].copy()
        matched["_items"] = codes[matched_mask].map(code_to_items)
        # exclude if ANY matched item for this ingredient row isn't in the selected set
        disallowed_mask = matched["_items"].apply(lambda items: bool(items - selected))
        excluded.update(
            matched.loc[disallowed_mask, "Recipe_Code"].astype(str).str.strip().str.upper().unique()
        )

    return excluded


def _fetch_cached(table: str) -> pd.DataFrame:
    """Fetch a static table, returning a cached copy while the cache is fresh."""
    if table not in _STATIC_TABLES:
        return _fetch(table)

    now = time.monotonic()
    entry = _cache.get(table)
    if entry is not None:
        df, ts = entry
        if now - ts < _CACHE_TTL and not df.empty:
            return df.copy()

    df = _fetch(table)
    if not df.empty:
        _cache[table] = (df, now)
        logger.info("Cached %s (%d rows)", table, len(df))
    else:
        logger.warning("Empty result for %s — not caching, will retry next call", table)
    return df.copy()


def _prefetch_static() -> dict[str, pd.DataFrame]:
    """Fetch all static tables in parallel, using cache where available."""
    results: dict[str, pd.DataFrame] = {}
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {pool.submit(_fetch_cached, table): table for table in _STATIC_TABLES}
        for future in as_completed(futures):
            results[futures[future]] = future.result()
    return results

_RECIPE_NUMERIC_COLS = [
    "Energy_ENERC_Kcal", "Energy_ENERC_KJ",
    "Protein_PROTCNT_g", "TotalFat_FATCE_g", "TotalDietaryFibre_FIBTG_g",
    "Carbohydrate_g", "CalciumCa_CA_mg", "ZincZn_ZN_mg", "IronFe_FE_mg",
    "MagnesiumMg_MG_mg", "VA_RAE_mcg", "TotalFolatesB9_FOLSUM_mcg", "VB12_mcg",
    "ThiamineB1_THIA_mg", "RiboflavinB2_RIBF_mg", "NiacinB3_NIA_mg",
    "TotalB6A_VITB6A_mg", "TotalAscorbicAcid_VITC_mg", "Sodium_mg", "VITE_mg",
    "PhosphorusP_mg", "PotassiumK_mg", "Cholesterol_mg",
    "Sugar_g", "Serving_g",
]


def load_data_from_supabase(user_id: str, profile: Optional[dict] = None, onboarding_id: str | None = None) -> dict:
    """
    Builds the same `ds` dict that Functions_Base.load_data() returns,
    but sourced from Supabase instead of local CSV files.
    """
    ds = {}
    static = _prefetch_static()

    _recipes_raw = static.get("Recipe", pd.DataFrame())
    for _col in _RECIPE_NUMERIC_COLS:
        if _col in _recipes_raw.columns:
            _recipes_raw[_col] = pd.to_numeric(_recipes_raw[_col], errors="coerce")
    if "TotalDietaryFibre_FIBTG_g" in _recipes_raw.columns:
        _recipes_raw["TotalDietaryFibre_FIBTG_g"] = _recipes_raw["TotalDietaryFibre_FIBTG_g"].fillna(0)
    ds["recipes"] = _recipes_raw

    _subcat = static.get("SubCategory", pd.DataFrame())
    # drop sub_category_code — Functions_Base re-derives it; having it pre-set causes duplicate columns
    if "sub_category_code" in _subcat.columns:
        _subcat = _subcat.drop(columns=["sub_category_code"])
    ds["subcategories"] = _subcat
    ds["sub_category"] = ds["subcategories"]

    _subcat_onboarding = static.get("SubCategory_Onboarding", pd.DataFrame())
    _recipe_tag = static.get("RecipeTagging", pd.DataFrame())
    if not _recipe_tag.empty:
        _recipe_tag = _recipe_tag.rename(columns={
            "Recipe code": "Recipe_Code",
            "Recipe Name": "Recipe_Name",
        })
    ds["recipe_tag"] = _recipe_tag
    ds["main1_main2_mapping"] = static.get("Main1_Main2_Mapping Subcategory", pd.DataFrame())
    ds["ear_100"] = static.get("BaseEar", pd.DataFrame())
    ds["tul"] = static.get("BaseTul", pd.DataFrame())
    ds["model"] = static.get("DataModelling", pd.DataFrame())
    ds["recipe_ingredients"] = static.get("Recipes_ingredient", pd.DataFrame())
    ds["sub_category_gi_gl"] = static.get("SubCategory_foods_GI_GL", pd.DataFrame())
    ds["recipe_name_changed"] = static.get("USER_Recipes_name_changed", pd.DataFrame())

    _pref_filters: dict = {"user_id": user_id}
    if onboarding_id:
        _pref_filters["onboarding_id"] = onboarding_id
    prefs = _fetch("BE_Preference_onboarding", _pref_filters)
    if not prefs.empty:
        prefs = prefs.rename(columns={"user_id": "UID"})
        if "Reaction" in prefs.columns:
            prefs = prefs[prefs["Reaction"] != "disliked"].copy()
        # drop columns that model.run() adds via merge to prevent duplicate column errors
        prefs = prefs.drop(columns=[c for c in ["sub_category_code", "sub_category_norm",
                                                 "SubCategory_merge", "codeoccurance",
                                                 "MainCategoryCode"] if c in prefs.columns])
        # "Main2" (frontend) → "Main 2" (Functions_Base internal label) so side dishes share the LP slot
        # if "dish_type" in prefs.columns:
        #     prefs["dish_type"] = prefs["dish_type"].apply(
        #         lambda x: "Main 2" if x == "Main2" else (x if x == "Main" else "Main")
        #     )
        # map SubCategory codes (e.g. "A1A") → names (e.g. "Dosa") so the model's merge resolves correctly
        if "sub_category" in prefs.columns:
            _code_to_name: dict = {}
            for _src in [_subcat, _subcat_onboarding]:
                if not _src.empty and {"Code", "SubCategory"}.issubset(_src.columns):
                    _code_to_name.update(dict(zip(
                        _src["Code"].astype(str).str.strip().str.upper(),
                        _src["SubCategory"].astype(str).str.strip()
                    )))
            # Also build an uppercase-name → canonical-name map to normalise case
            # when names (rather than codes) are already stored in sub_category.
            _name_to_canonical: dict = {}
            for _src in [_subcat, _subcat_onboarding]:
                if not _src.empty and "SubCategory" in _src.columns:
                    _name_to_canonical.update(dict(zip(
                        _src["SubCategory"].astype(str).str.strip().str.upper(),
                        _src["SubCategory"].astype(str).str.strip()
                    )))

            def _resolve_subcat(val: str) -> str:
                v = str(val).strip()
                v_upper = v.upper()
                if v_upper in _code_to_name:
                    return _code_to_name[v_upper]
                if v_upper in _name_to_canonical:
                    return _name_to_canonical[v_upper]
                return v

            prefs["sub_category"] = prefs["sub_category"].apply(_resolve_subcat)
    ds["preferences"] = prefs

    # Fetch Rec_ADAM_yes_no and subset recipes/recipe_tag to only "ADAM_Recipes"
    user_df = static.get("Rec_ADAM_yes_no", pd.DataFrame())
    ds["Rec_ADAM_yes_no"] = user_df
    if not user_df.empty and "ADAM_Recipes" in user_df.columns:
        # it can be "0" or int(0)    
        user_df = user_df[(user_df["ADAM_Recipes"] == "1") | (user_df["ADAM_Recipes"] == 1)].copy()
        if not user_df.empty:
            code_col = next((c for c in ["Recipe_Code"] if c in user_df.columns), None)
            if code_col:
                user_codes = set(user_df[code_col].astype(str).str.strip().str.upper())
                if user_codes:
                    # subset recipes
                    if "Recipe_Code" in ds.get("recipes", pd.DataFrame()).columns:
                        ds["recipes"] = ds["recipes"][
                            ds["recipes"]["Recipe_Code"].astype(str).str.strip().str.upper().isin(user_codes)
                        ].copy()
                    else:
                        for rc in ["Recipe code", "RecipeCode"]:
                            if rc in ds.get("recipes", pd.DataFrame()).columns:
                                ds["recipes"] = ds["recipes"][
                                    ds["recipes"][rc].astype(str).str.strip().str.upper().isin(user_codes)
                                ].copy()
                                break
                    # subset recipe_tag
                    if "Recipe_Code" in ds.get("recipe_tag", pd.DataFrame()).columns:
                        ds["recipe_tag"] = ds["recipe_tag"][
                            ds["recipe_tag"]["Recipe_Code"].astype(str).str.strip().str.upper().isin(user_codes)
                        ].copy()
                    elif "Recipe code" in ds.get("recipe_tag", pd.DataFrame()).columns:
                        ds["recipe_tag"] = ds["recipe_tag"][
                            ds["recipe_tag"]["Recipe code"].astype(str).str.strip().str.upper().isin(user_codes)
                        ].copy()

    print("Diet type",str(profile.get("diet_type", "")).strip().lower())
    print("No of recipes - BEFORE",len(ds["recipes"]))

    try:
        if profile:
            diet = str(profile.get("diet_type", "")).strip().lower()
            rt = ds.get("recipe_tag", pd.DataFrame()).copy()
            if not rt.empty and "Recipe_Code" in rt.columns:
                # One-to-one mapping
                diet_column_map = {
                    "veg": "Vegetarian",
                    "vegan": "Vegetarian",
                    "non-veg": "Non vegetarian",
                    "egg": "Ovo-vegetarian",
                    "ovo-veg": "Ovo-vegetarian",
                }

                col = diet_column_map.get(diet)
                if col and col in rt.columns:
                    if col == "Ovo-vegetarian":
                        veg_series = pd.to_numeric(rt.get("Vegetarian"), errors="coerce")
                        ovo_series = pd.to_numeric(rt.get("Ovo-vegetarian"), errors="coerce")
                        mask = (veg_series == 1) | ((veg_series == 0) & (ovo_series == 1))
                    elif col != "Non vegetarian":
                        mask = pd.to_numeric(rt[col], errors="coerce") == 1
                    else:
                        mask = None

                    if mask is not None:
                        rt_sub = rt[mask].copy()
                        if not rt_sub.empty:
                            ds["recipe_tag"] = rt_sub
                            if "Recipe_Code" in ds["recipes"].columns:
                                valid_codes = (
                                    rt_sub["Recipe_Code"]
                                    .astype(str)
                                    .str.strip()
                                    .str.upper()
                                    .dropna()
                                    .unique()
                                )
                                ds["recipes"] = ds["recipes"][
                                    ds["recipes"]["Recipe_Code"]
                                    .astype(str)
                                    .str.strip()
                                    .str.upper()
                                    .isin(valid_codes)
                                ].copy()
                    elif col == "Non vegetarian":
                        # No Vegetarian/Ovo-vegetarian restriction for non-veg eaters, but
                        # narrow further to the specific meat types they selected at
                        # onboarding (non_veg_types), if any — e.g. selecting only
                        # Goat/Fish/Pork removes chicken- or beef-based recipes too.
                        excluded_nonveg = get_recipes_excluded_by_nonveg_types(profile.get("non_veg_types"))
                        if excluded_nonveg:
                            ds["recipe_tag"] = rt[
                                ~rt["Recipe_Code"].astype(str).str.strip().str.upper().isin(excluded_nonveg)
                            ].copy()
                            if "Recipe_Code" in ds["recipes"].columns:
                                ds["recipes"] = ds["recipes"][
                                    ~ds["recipes"]["Recipe_Code"]
                                    .astype(str)
                                    .str.strip()
                                    .str.upper()
                                    .isin(excluded_nonveg)
                                ].copy()
        print("No of recipes - AFTER",len(ds["recipes"]))
    except Exception:
        logger.exception("Vegetarian recipe filtering failed for user_id=%s — serving unfiltered recipes", user_id)

    # Exclude recipes the user has explicitly disliked — from the standalone
    # recipes page (Recipes_LU, Interaction="U") and from mobile meal-plan
    # reactions (Recommendation.Reaction / Combo_Reaction == "dislike"), so
    # disliked recipes never enter personalization scoring to begin with.
    # (Recommendation.Reaction stores ReactionType.DISLIKE.value == "dislike",
    # not "disliked" — a prior version of this filter used the wrong string
    # and silently never matched anything.)
    try:
        disliked_codes: set = set()

        lu_disliked = _fetch("Recipes_LU", {"UID": user_id, "Interaction": "U"})
        if not lu_disliked.empty and "Recipe_Code" in lu_disliked.columns:
            disliked_codes.update(
                lu_disliked["Recipe_Code"].dropna().astype(str).str.strip().str.upper().unique()
            )

        reaction_disliked = _fetch("Recommendation", {"user_id": user_id, "Reaction": "dislike"})
        if not reaction_disliked.empty and "Food_Name_desc" in reaction_disliked.columns:
            disliked_codes.update(
                reaction_disliked["Food_Name_desc"].dropna().astype(str).str.strip().str.upper().unique()
            )

        combo_disliked = _fetch("Recommendation", {"user_id": user_id, "Combo_Reaction": "dislike"})
        if not combo_disliked.empty and "Food_Name_desc" in combo_disliked.columns:
            disliked_codes.update(
                combo_disliked["Food_Name_desc"].dropna().astype(str).str.strip().str.upper().unique()
            )

        if disliked_codes:
            if "Recipe_Code" in ds["recipes"].columns:
                ds["recipes"] = ds["recipes"][
                    ~ds["recipes"]["Recipe_Code"].astype(str).str.strip().str.upper().isin(disliked_codes)
                ].copy()
            rt = ds.get("recipe_tag", pd.DataFrame())
            if not rt.empty and "Recipe_Code" in rt.columns:
                ds["recipe_tag"] = rt[
                    ~rt["Recipe_Code"].astype(str).str.strip().str.upper().isin(disliked_codes)
                ].copy()
    except Exception:
        logger.exception("Disliked recipe exclusion failed for user_id=%s — disliked recipes may reappear", user_id)

    # Exclude recipes built from an ingredient the user is allergic to, per
    # BE_Preference_onboarding_details.health_details.allergy_food_codes (a list
    # of ingredient codes matching Recipes_ingredient.Ing_Id). Same hard-exclude
    # shape as the disliked-recipe filter above — allergen recipes should never
    # reach personalization scoring.
    try:
        health_filters: dict = {"user_id": user_id}
        if onboarding_id:
            health_filters["onboarding_id"] = onboarding_id
        health_rows = _fetch("BE_Preference_onboarding_details", health_filters)

        allergy_codes: set = set()
        if not health_rows.empty and "health_details" in health_rows.columns:
            for details in health_rows["health_details"].dropna():
                if isinstance(details, dict):
                    allergy_codes.update(
                        str(c).strip() for c in (details.get("allergy_food_codes") or []) if c is not None
                    )

        if allergy_codes:
            ing_resp = (
                get_supabase()
                .table("Recipes_ingredient")
                .select("Recipe_Code, Ing_Id")
                .in_("Ing_Id", list(allergy_codes))
                .execute()
            )
            allergy_recipe_codes = {
                str(r["Recipe_Code"]).strip().upper() for r in (ing_resp.data or []) if r.get("Recipe_Code")
            }

            if allergy_recipe_codes:
                if "Recipe_Code" in ds["recipes"].columns:
                    ds["recipes"] = ds["recipes"][
                        ~ds["recipes"]["Recipe_Code"].astype(str).str.strip().str.upper().isin(allergy_recipe_codes)
                    ].copy()
                rt = ds.get("recipe_tag", pd.DataFrame())
                if not rt.empty and "Recipe_Code" in rt.columns:
                    ds["recipe_tag"] = rt[
                        ~rt["Recipe_Code"].astype(str).str.strip().str.upper().isin(allergy_recipe_codes)
                    ].copy()
    except Exception:
        logger.exception("Allergy recipe exclusion failed for user_id=%s — allergen recipes may reappear", user_id)

    # Collect liked recipes (same two sources) so run() can force them into the
    # LP's candidate pool even if they didn't score high enough naturally.
    try:
        liked_codes: set = set()

        lu_liked = _fetch("Recipes_LU", {"UID": user_id, "Interaction": "L"})
        if not lu_liked.empty and "Recipe_Code" in lu_liked.columns:
            liked_codes.update(
                lu_liked["Recipe_Code"].dropna().astype(str).str.strip().str.upper().unique()
            )

        reaction_liked = _fetch("Recommendation", {"user_id": user_id, "Reaction": "like"})
        if not reaction_liked.empty and "Food_Name_desc" in reaction_liked.columns:
            liked_codes.update(
                reaction_liked["Food_Name_desc"].dropna().astype(str).str.strip().str.upper().unique()
            )

        combo_liked = _fetch("Recommendation", {"user_id": user_id, "Combo_Reaction": "like"})
        if not combo_liked.empty and "Food_Name_desc" in combo_liked.columns:
            liked_codes.update(
                combo_liked["Food_Name_desc"].dropna().astype(str).str.strip().str.upper().unique()
            )

        # Millet-based recipes are always treated as liked for every user
        # (not tied to any actual reaction), so _inject_liked_recipes gives
        # them the same candidate-pool/objective-bonus treatment.
        millet_recipes = _fetch_cached("Millet_Recipes")
        millet_codes: set = set()
        if not millet_recipes.empty and "Recipe_Code" in millet_recipes.columns:
            millet_codes = set(
                millet_recipes["Recipe_Code"].dropna().astype(str).str.strip().str.upper().unique()
            )
            liked_codes.update(millet_codes)

        ds["liked_recipe_codes"] = liked_codes
        # Kept separate from liked_recipe_codes: services/lp_optimizer.py uses
        # this set for a stronger, millet-only soft-forced-inclusion
        # constraint, not applied to ordinary liked recipes.
        ds["millet_recipe_codes"] = millet_codes
    except Exception:
        logger.exception("Liked recipe lookup failed for user_id=%s — liked recipes won't be force-included", user_id)
        ds["liked_recipe_codes"] = set()
        ds["millet_recipe_codes"] = set()

    return ds


def _fetch_recipe_tag() -> pd.DataFrame:
    return _fetch_cached("RecipeTagging")


def _fetch_main_code() -> pd.DataFrame:
    return _fetch_cached("Main1_Main2_Mapping Subcategory")


def _fetch_ear() -> pd.DataFrame:
    return _fetch_cached("BaseEar")


def _fetch_tul() -> pd.DataFrame:
    return _fetch_cached("BaseTul")


def _fetch_gi_gl() -> pd.DataFrame:
    return _fetch_cached("SubCategory_foods_GI_GL")
