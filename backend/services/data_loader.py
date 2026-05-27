"""
Fetches all dataset tables from Supabase and returns the same dict-of-DataFrames
structure that Functions_Base.load_data() would produce from local CSVs.
"""

import logging
import time
import pandas as pd
from typing import Optional
from core.supabase import get_supabase

logger = logging.getLogger("backend.data_loader")


_FETCH_LIMIT = 5000  # Supabase PostgREST default max is 1000; raise to cover full datasets

# Tables that never change during a session — cached for 1 hour per worker process
_CACHE_TTL = 3600
_STATIC_TABLES = {
    "Recipe", "RecipeTagging", "SubCategory", "SubCategory_Onboarding",
    "DataModelling", "BaseEar", "BaseTul", "Main1_Main2_Mapping Subcategory",
    "Rec_ADAM_yes_no", "SubCategory_foods_GI_GL", "RecipeINGDBFormat",
    "USER_Recipes_name_changed",
}
_cache: dict[str, tuple[pd.DataFrame, float]] = {}


_CONNECTION_ERR_TAGS = ("Server disconnected", "ConnectionTerminated", "RemoteProtocolError", "StreamReset")


def _is_connection_err(exc: Exception) -> bool:
    msg = str(exc)
    return any(tag in msg for tag in _CONNECTION_ERR_TAGS)


def _fetch(table: str, filters: Optional[dict] = None) -> pd.DataFrame:
    """Fetch all rows using pagination. Retries up to 2 times on HTTP/2 connection errors,
    resetting the Supabase client before each retry so a fresh connection is used."""
    for attempt in range(3):
        try:
            supabase = get_supabase()
            all_rows: list = []
            batch_size = 1000
            start = 0

            while True:
                query = supabase.table(table).select("*").range(start, start + batch_size - 1)
                if filters:
                    for col, val in filters.items():
                        query = query.eq(col, val)

                try:
                    response = query.execute()
                    data = response.data
                except Exception as batch_err:
                    if all_rows:
                        logger.warning(
                            "Partial fetch for %s at offset %d (%s) — returning %d rows",
                            table, start, batch_err, len(all_rows),
                        )
                        break
                    raise

                if not data:
                    break
                all_rows.extend(data)
                if len(data) < batch_size:
                    break
                start += batch_size

            return pd.DataFrame(all_rows)

        except Exception as e:
            if attempt < 2 and _is_connection_err(e):
                from core.supabase import reset_supabase_client
                reset_supabase_client()
                wait = 1.5 * (attempt + 1)
                logger.warning(
                    "Connection error fetching %s (attempt %d): %s — resetting client, retrying in %.1fs",
                    table, attempt + 1, e, wait,
                )
                time.sleep(wait)
            else:
                logger.warning("[WARN] Failed to fetch %s: %s", table, e)
                return pd.DataFrame()

    return pd.DataFrame()


def _fetch_cached(table: str) -> pd.DataFrame:
    """Fetch a static table, returning a cached copy if still fresh.
    Empty DataFrames (failed fetches) are never cached so the next call retries.
    """
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
    """Fetch all static tables sequentially, using cache where available.
    Sequential (not parallel) to avoid cascading HTTP/2 stream failures when
    multiple concurrent requests share the same connection and it drops."""
    return {t: _fetch_cached(t) for t in _STATIC_TABLES}


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
    Static tables are fetched in parallel and cached for 1 hour.
    """
    ds = {}

    # Fetch all static tables in parallel (cache hit = near-instant on second load_data() call)
    static = _prefetch_static()

    _recipes_raw = static.get("Recipe", pd.DataFrame())
    for _col in _RECIPE_NUMERIC_COLS:
        if _col in _recipes_raw.columns:
            _recipes_raw[_col] = pd.to_numeric(_recipes_raw[_col], errors="coerce")
    # NaN fiber → NaN GL series → stray return in Functions_Base line 476 → AttributeError on .shape
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
    ds["recipe_tag"] = static.get("RecipeTagging", pd.DataFrame())
    ds["main1_main2_mapping"] = static.get("Main1_Main2_Mapping Subcategory", pd.DataFrame())
    ds["ear_100"] = static.get("BaseEar", pd.DataFrame())
    ds["tul"] = static.get("BaseTul", pd.DataFrame())
    ds["model"] = static.get("DataModelling", pd.DataFrame())
    ds["recipe_ingredients"] = static.get("RecipeINGDBFormat", pd.DataFrame())
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
        if "sub_category" in prefs.columns:
            _code_to_name: dict = {}
            for _src in [_subcat, _subcat_onboarding]:
                if not _src.empty and {"Code", "SubCategory"}.issubset(_src.columns):
                    _code_to_name.update(dict(zip(
                        _src["Code"].astype(str).str.strip().str.upper(),
                        _src["SubCategory"].astype(str).str.strip()
                    )))
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
        user_df = user_df[(user_df["ADAM_Recipes"] == "1") | (user_df["ADAM_Recipes"] == 1)].copy()
        if not user_df.empty:
            code_col = next((c for c in ["Recipe_Code"] if c in user_df.columns), None)
            if code_col:
                user_codes = set(user_df[code_col].astype(str).str.strip().str.upper())
                if user_codes:
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
                    if "Recipe_Code" in ds.get("recipe_tag", pd.DataFrame()).columns:
                        ds["recipe_tag"] = ds["recipe_tag"][
                            ds["recipe_tag"]["Recipe_Code"].astype(str).str.strip().str.upper().isin(user_codes)
                        ].copy()
                    elif "Recipe code" in ds.get("recipe_tag", pd.DataFrame()).columns:
                        ds["recipe_tag"] = ds["recipe_tag"][
                            ds["recipe_tag"]["Recipe code"].astype(str).str.strip().str.upper().isin(user_codes)
                        ].copy()

    print("Diet type", str(profile.get("diet_type", "")).strip().lower())
    print("No of recipes - BEFORE", len(ds["recipes"]))

    try:
        if profile:
            diet = str(profile.get("diet_type", "")).strip().lower()
            rt = ds.get("recipe_tag", pd.DataFrame()).copy()
            if not rt.empty and "Recipe_Code" in rt.columns:
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
                                    .astype(str).str.strip().str.upper()
                                    .dropna().unique()
                                )
                                ds["recipes"] = ds["recipes"][
                                    ds["recipes"]["Recipe_Code"]
                                    .astype(str).str.strip().str.upper()
                                    .isin(valid_codes)
                                ].copy()
        print("No of recipes - AFTER", len(ds["recipes"]))
    except Exception:
        logger.exception("Vegetarian recipe filtering failed for user_id=%s — serving unfiltered recipes", user_id)

    # Exclude recipes the user has explicitly disliked in previous plans
    try:
        disliked = _fetch("Recommendation", {"user_id": user_id, "Reaction": "disliked"})
        if not disliked.empty and "Food_Name_desc" in disliked.columns:
            disliked_codes = set(
                disliked["Food_Name_desc"].dropna().astype(str).str.strip().str.upper().unique()
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
