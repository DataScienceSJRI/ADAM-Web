"""
Fetches all dataset tables from Supabase and returns the same dict-of-DataFrames
structure that Functions_Base.load_data() would produce from local CSVs.
"""

import logging
import pandas as pd
from typing import Optional
from core.supabase import get_supabase

logger = logging.getLogger("backend.data_loader")


_FETCH_LIMIT = 5000  # Supabase PostgREST default max is 1000; raise to cover full datasets


def _fetch(table: str, filters: Optional[dict] = None) -> pd.DataFrame:
    """Fetch all rows using pagination."""
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

        return pd.DataFrame(all_rows)

    except Exception as e:
        print(f"[WARN] Failed to fetch {table}: {e}")
        return pd.DataFrame()
    

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

    _recipes_raw = _fetch("Recipe")
    for _col in _RECIPE_NUMERIC_COLS:
        if _col in _recipes_raw.columns:
            _recipes_raw[_col] = pd.to_numeric(_recipes_raw[_col], errors="coerce")
    ds["recipes"] = _recipes_raw

    _subcat = _fetch("SubCategory")
    # drop sub_category_code — Functions_Base re-derives it; having it pre-set causes duplicate columns
    if "sub_category_code" in _subcat.columns:
        _subcat = _subcat.drop(columns=["sub_category_code"])
    ds["subcategories"] = _subcat
    ds["sub_category"] = ds["subcategories"]

    _subcat_onboarding = _fetch("SubCategory_Onboarding")
    ds["recipe_tag"] = _fetch_recipe_tag()
    ds["main1_main2_mapping"] = _fetch_main_code()
    ds["ear_100"] = _fetch_ear()
    ds["tul"] = _fetch_tul()
    ds["model"] = _fetch("DataModelling")
    ds["recipe_ingredients"] = _fetch("RecipeINGDBFormat")
    ds["sub_category_gi_gl"] = _fetch_gi_gl()
    ds["recipe_name_changed"] = _fetch("USER_Recipes_name_changed")

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
        if "dish_type" in prefs.columns:
            prefs["dish_type"] = prefs["dish_type"].apply(
                lambda x: "Main 2" if x == "Main2" else (x if x == "Main" else "Main")
            )
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
    user_df = _fetch("Rec_ADAM_yes_no")
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
                if col and col in rt.columns and col != "Non vegetarian":
                    mask = pd.to_numeric(rt[col], errors="coerce") == 1
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
        print("No of recipes - BEFORE",len(ds["recipes"]))
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
    return _fetch("RecipeTagging")


def _fetch_main_code() -> pd.DataFrame:
    return _fetch("Main1_Main2_Mapping")


def _fetch_ear() -> pd.DataFrame:
    return _fetch("BaseEar")


def _fetch_tul() -> pd.DataFrame:
    return _fetch("BaseTul")


def _fetch_gi_gl() -> pd.DataFrame:
    return _fetch("SubCategory_foods_GI_GL")
