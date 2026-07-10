import logging
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Query
from core.auth import get_current_user
from core.supabase import get_supabase
from services.data_loader import _fetch_cached
from services.profile_builder import build_profile

router = APIRouter(prefix="/kpi", tags=["kpi"])
logger = logging.getLogger("backend.routers.kpi")

# Same nutrient set build_weekly_nutrient_summary() (routers/plan.py) reports on,
# kept identical so the two summaries stay directly comparable.
NUTRIENT_COLS = [
    "Energy_ENERC_Kcal", "Protein_PROTCNT_g", "TotalFat_FATCE_g", "TotalDietaryFibre_FIBTG_g",
    "CalciumCa_CA_mg", "ZincZn_ZN_mg", "IronFe_FE_mg", "MagnesiumMg_MG_mg", "VA_RAE_mcg",
    "TotalFolatesB9_FOLSUM_mcg", "VB12_mcg", "ThiamineB1_THIA_mg", "RiboflavinB2_RIBF_mg",
    "NiacinB3_NIA_mg", "TotalB6A_VITB6A_mg", "TotalAscorbicAcid_VITC_mg",
    "Carbohydrate_g", "Sodium_mg", "VITE_mg", "PhosphorusP_mg", "PotassiumK_mg", "Cholesterol_mg",
]

# Display name + unit for each nutrient column, e.g. "Protein (g)".
NUTRIENT_LABELS = {
    "Energy_ENERC_Kcal": "Energy (kcal)",
    "Protein_PROTCNT_g": "Protein (g)",
    "TotalFat_FATCE_g": "Fat (g)",
    "TotalDietaryFibre_FIBTG_g": "Dietary Fibre (g)",
    "CalciumCa_CA_mg": "Calcium (mg)",
    "ZincZn_ZN_mg": "Zinc (mg)",
    "IronFe_FE_mg": "Iron (mg)",
    "MagnesiumMg_MG_mg": "Magnesium (mg)",
    "VA_RAE_mcg": "Vitamin A (mcg)",
    "TotalFolatesB9_FOLSUM_mcg": "Folate / B9 (mcg)",
    "VB12_mcg": "Vitamin B12 (mcg)",
    "ThiamineB1_THIA_mg": "Vitamin B1 / Thiamine (mg)",
    "RiboflavinB2_RIBF_mg": "Vitamin B2 / Riboflavin (mg)",
    "NiacinB3_NIA_mg": "Vitamin B3 / Niacin (mg)",
    "TotalB6A_VITB6A_mg": "Vitamin B6 (mg)",
    "TotalAscorbicAcid_VITC_mg": "Vitamin C (mg)",
    "Carbohydrate_g": "Carbohydrate (g)",
    "Sodium_mg": "Sodium (mg)",
    "VITE_mg": "Vitamin E (mg)",
    "PhosphorusP_mg": "Phosphorus (mg)",
    "PotassiumK_mg": "Potassium (mg)",
    "Cholesterol_mg": "Cholesterol (mg)",
}

# Nutrient column -> BaseEar "Nutrients_name" row. Only nutrients with an EAR
# entry get a Daily_Requirement / Percent_Requirement_Met; the rest are reported
# achieved-only, mirroring build_weekly_nutrient_summary's recipe_to_ear_name map.
_NUTRIENT_TO_EAR_NAME = {
    "Energy_ENERC_Kcal": "Energy",
    "Protein_PROTCNT_g": "Protein",
    "TotalFat_FATCE_g": "Fat",
    "TotalDietaryFibre_FIBTG_g": "Dietary_Fibre",
    "CalciumCa_CA_mg": "Calcium",
    "ZincZn_ZN_mg": "Zinc",
    "IronFe_FE_mg": "Iron",
    "MagnesiumMg_MG_mg": "Magnesium",
    "VA_RAE_mcg": "VA",
    "TotalFolatesB9_FOLSUM_mcg": "Folate",
    "VB12_mcg": "VB12",
    "ThiamineB1_THIA_mg": "VB1",
    "RiboflavinB2_RIBF_mg": "VB2",
    "NiacinB3_NIA_mg": "VB3",
    "TotalB6A_VITB6A_mg": "VB6",
    "TotalAscorbicAcid_VITC_mg": "VC",
}

# Carbohydrate has no direct EAR row in BaseEar — it's conventionally set as a
# share of total energy rather than an absolute nutrient requirement.
CARB_ENERGY_FRACTION = 0.5   # 50% of daily energy from carbs
CARB_KCAL_PER_G = 4.0

_PAL_BY_ACTIVITY_LEVEL = {
    "Sedentary": 1.2,
    "Lightly Active": 1.375,
    "Moderately Active": 1.55,
    "Very Active": 1.725,
    "Extra Active": 1.9,
}


def _norm_key(value) -> str:
    return str(value).strip().lower().replace(" ", "").replace("_", "")


def _daily_energy_requirement(profile: dict) -> Optional[float]:
    """Mifflin-St Jeor BMR * activity PAL, matching Functions_Base._get_weekly_requirement_maps."""
    try:
        height = float(profile.get("height"))
        age = float(profile.get("age"))
        weight = float(profile.get("weight"))
    except (TypeError, ValueError):
        return None
    sex = str(profile.get("gender") or "")
    bmr = 10 * weight + 6.25 * height - 5 * age + (5 if sex.lower() == "male" else -161)
    pal = _PAL_BY_ACTIVITY_LEVEL.get(str(profile.get("activity_levels") or "").strip(), 1.2)
    return bmr * pal


def _daily_ear_map(profile: dict) -> dict:
    """Per-day nutrient requirements (EAR) for the user's age/gender/activity group."""
    ear_df = _fetch_cached("BaseEar")
    age_group_col = profile.get("age_group_col")
    if ear_df.empty or not age_group_col or age_group_col not in ear_df.columns:
        return {}

    ear_lookup: dict = {}
    for _, row in ear_df.iterrows():
        try:
            v = float(row.get(age_group_col))
        except (TypeError, ValueError):
            continue
        ear_lookup[_norm_key(row.get("Nutrients_name"))] = v

    daily_min: dict = {}
    for col, ear_name in _NUTRIENT_TO_EAR_NAME.items():
        key = _norm_key(ear_name)
        if key in ear_lookup:
            daily_min[col] = ear_lookup[key]

    energy = _daily_energy_requirement(profile)
    if energy is not None:
        daily_min["Energy_ENERC_Kcal"] = energy
        daily_min["Carbohydrate_g"] = (CARB_ENERGY_FRACTION * energy) / CARB_KCAL_PER_G

    return daily_min


def build_daily_nutrient_summary(user_id: str, target_date: str) -> list[dict]:
    """DietRecall equivalent of build_weekly_nutrient_summary (routers/plan.py).

    Sums the nutrients of what the user actually logged as eaten on target_date
    and compares each against their daily EAR requirement.
    """
    sb = get_supabase()

    profile = build_profile(user_id)
    daily_min = _daily_ear_map(profile) if profile else {}

    recall_rows = (
        sb.table("DietRecall")
        .select("Food_Name_desc, Food_Qty")
        .eq("user_id", user_id)
        .eq("Date", target_date)
        .execute()
        .data
    ) or []

    # Skipped meals carry no recipe code (services/recall.py only sets
    # Food_Name_desc when a recipe was actually eaten or substituted).
    eaten = [r for r in recall_rows if r.get("Food_Name_desc")]

    if not eaten:
        rows = []
        for col in NUTRIENT_COLS:
            req = daily_min.get(col)
            rows.append({
                "Nutrient": NUTRIENT_LABELS[col],
                "Requirement": req,
                "Intake": 0.0,
                "% Met": 0.0 if req else None,
            })
        return rows

    recipe_codes = list({r["Food_Name_desc"] for r in eaten})
    # NUTRIENT_COLS minus Energy_ENERC_Kcal, which Recipe stores in kJ.
    recipe_nutrient_cols = [c for c in NUTRIENT_COLS if c != "Energy_ENERC_Kcal"]
    recipe_resp = (
        sb.table("Recipe")
        .select("Recipe_Code, Energy_ENERC_KJ, " + ", ".join(recipe_nutrient_cols))
        .in_("Recipe_Code", recipe_codes)
        .execute()
    )
    recipe_map = {r["Recipe_Code"]: r for r in (recipe_resp.data or [])}

    # RecipeTagging.Portion is the recipe's canonical full-serving count (e.g.
    # "1.2 Cup") — the same unit DietRecall.Food_Qty is recorded in
    # (services/recommendation_writer.py: Food_Qty = Serving_fraction * Portion).
    # Recipe's nutrient columns are defined per that one full Portion, so
    # Food_Qty / Portion recovers the eaten fraction to scale them by.
    tag_resp = (
        sb.table("RecipeTagging")
        .select("Recipe_Code, Portion")
        .in_("Recipe_Code", recipe_codes)
        .execute()
    )
    portion_map = {t["Recipe_Code"]: t.get("Portion") for t in (tag_resp.data or [])}

    totals = {col: 0.0 for col in NUTRIENT_COLS}
    for r in eaten:
        code = r["Food_Name_desc"]
        recipe = recipe_map.get(code)
        if not recipe:
            continue
        try:
            base_portion = float(portion_map.get(code))
            food_qty = float(r.get("Food_Qty"))
            prop = food_qty / base_portion if base_portion > 0 else 1.0
        except (TypeError, ValueError):
            prop = 1.0

        totals["Energy_ENERC_Kcal"] += (float(recipe.get("Energy_ENERC_KJ") or 0) / 4.184) * prop
        for col in recipe_nutrient_cols:
            val = recipe.get(col)
            if val is not None:
                totals[col] += float(val) * prop

    rows = []
    for col in NUTRIENT_COLS:
        req = daily_min.get(col)
        ach = totals[col]
        pct = (100.0 * ach / req) if req else None
        rows.append({
            "Nutrient": NUTRIENT_LABELS[col],
            "Requirement": round(req, 1) if req is not None else None,
            "Intake": round(ach, 2),
            "% Met": round(pct, 1) if pct is not None else None,
        })
    return rows


def _latest_plan_id(sb, user_id: str) -> Optional[str]:
    resp = (
        sb.table("BE_Onboarding_Sessions")
        .select("plan_id")
        .eq("user_id", user_id)
        .not_.is_("plan_id", "null")
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    return resp.data[0]["plan_id"] if resp.data else None


@router.get("")
def get_kpi(
    plan_date: Optional[str] = Query(None, description="YYYY-MM-DD, defaults to today"),
    user_id: str = Depends(get_current_user),
):
    """
    Returns blood sugar control score and today's nutrition totals
    (carbs, protein, fat, fibre) from the user's active meal plan.
    """
    sb = get_supabase()
    target_date = plan_date or str(date.today())
    plan_id = _latest_plan_id(sb, user_id)

    if not plan_id:
        return {
            "date": target_date,
            "blood_sugar_control_score": None,
            "gl_per_day": None,
            "nutrition": {"carbs_g": 0, "protein_g": 0, "fat_g": 0, "fibre_g": 0},
            "nutrient_summary": build_daily_nutrient_summary(user_id, target_date),
            "message": "No plan found.",
        }

    # Fetch today's rows from FinalSummary
    summary_resp = (
        sb.table("FinalSummary")
        .select("Recipe_Code, Optimal_proportion, Carbohydrate_g, TotalDietaryFibre_FIBTG_g, GL")
        .eq("user_id", user_id)
        .eq("plan_id", plan_id)
        .eq("Date", target_date)
        .execute()
    )
    rows = summary_resp.data or []

    if not rows:
        return {
            "date": target_date,
            "blood_sugar_control_score": None,
            "gl_per_day": None,
            "nutrition": {"carbs_g": 0, "protein_g": 0, "fat_g": 0, "fibre_g": 0},
            "nutrient_summary": build_daily_nutrient_summary(user_id, target_date),
            "message": "No meals found for this date.",
        }

    # Fetch protein + fat from Recipe for today's recipe codes
    recipe_codes = list({r["Recipe_Code"] for r in rows if r.get("Recipe_Code")})
    recipe_resp = (
        sb.table("Recipe")
        .select("Recipe_Code, Protein_PROTCNT_g, TotalFat_FATCE_g")
        .in_("Recipe_Code", recipe_codes)
        .execute()
    )
    nutrient_map = {
        r["Recipe_Code"]: {
            "protein": float(r.get("Protein_PROTCNT_g") or 0),
            "fat": float(r.get("TotalFat_FATCE_g") or 0),
        }
        for r in (recipe_resp.data or [])
    }

    # Aggregate
    total_carbs = total_fibre = total_protein = total_fat = total_gl = 0.0
    for r in rows:
        prop = float(r.get("Optimal_proportion") or 1.0)
        total_carbs  += float(r.get("Carbohydrate_g") or 0)           # already weighted in FinalSummary
        total_fibre  += float(r.get("TotalDietaryFibre_FIBTG_g") or 0)
        total_gl     += float(r.get("GL") or 0)
        rc = r.get("Recipe_Code", "")
        total_protein += nutrient_map.get(rc, {}).get("protein", 0) * prop
        total_fat     += nutrient_map.get(rc, {}).get("fat", 0) * prop

    # Blood sugar control score: 100 = perfect (GL=0), 0 = at/above daily cap (GL≥90)
    score = round(max(0.0, min(100.0, (1 - total_gl / 90.0) * 100)), 1)

    return {
        "date": target_date,
        "blood_sugar_control_score": score,
        "gl_per_day": round(total_gl, 1),
        "nutrition": {
            "carbs_g": round(total_carbs, 1),
            "protein_g": round(total_protein, 1),
            "fat_g": round(total_fat, 1),
            "fibre_g": round(total_fibre, 1),
        },
        "nutrient_summary": build_daily_nutrient_summary(user_id, target_date),
    }
