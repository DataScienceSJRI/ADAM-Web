"""
Fetches all dataset tables from Supabase and returns the same dict-of-DataFrames
structure that Functions_Base.load_data() would produce from local CSVs.
"""

import pandas as pd
from typing import Optional
from core.supabase import get_supabase


_FETCH_LIMIT = 5000  # Supabase PostgREST default max is 1000; raise to cover full datasets


def _fetch(table: str, filters: Optional[dict] = None) -> pd.DataFrame:
    """Fetch all rows from a Supabase table, return as DataFrame."""
    try:
        supabase = get_supabase()
        query = supabase.table(table).select("*").limit(_FETCH_LIMIT)
        if filters:
            for col, val in filters.items():
                query = query.eq(col, val)
        response = query.execute()
        if response.data:
            return pd.DataFrame(response.data)
        return pd.DataFrame()
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


def load_data_from_supabase(user_id: str, profile: Optional[dict] = None) -> dict:
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

    prefs = _fetch("BE_Preference_onboarding", {"user_id": user_id})
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

    ds["user_recipes"] = pd.DataFrame()

    try:
        if profile and str(profile.get("diet_type", "")).strip().lower() == "veg":
            rt = ds.get("recipe_tag", pd.DataFrame()).copy()
            if not rt.empty and "Vegetarian" in rt.columns and "Recipe_Code" in rt.columns:
                mask = pd.to_numeric(rt["Vegetarian"], errors="coerce") == 1
                rt_sub = rt[mask].copy()
                if not rt_sub.empty:
                    ds["recipe_tag"] = rt_sub
                    codes = set(
                        rt_sub["Recipe_Code"].astype(str).str.strip().str.upper().dropna().unique()
                    )
                    if codes and "Recipe_Code" in ds["recipes"].columns:
                        ds["recipes"] = ds["recipes"][
                            ds["recipes"]["Recipe_Code"].astype(str).str.strip().str.upper().isin(codes)
                        ].copy()
    except Exception:
        pass

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
        pass

    return ds


def _fetch_recipe_tag() -> pd.DataFrame:
    return _fetch("RecipeTagging")


def _fetch_main_code() -> pd.DataFrame:
    df = _fetch("MainCode")
    if df.empty:
        return df
    keep = [c for c in ["Main1_Code", "Main2_Code", "Optional"] if c in df.columns]
    return df[keep].copy()


def _fetch_ear() -> pd.DataFrame:
    return _fetch("BaseEar")


def _fetch_tul() -> pd.DataFrame:
    return _fetch("BaseTul")


def _fetch_gi_gl() -> pd.DataFrame:
    return pd.DataFrame()
