"""One-off: seed a handful of tagged mock RecipeDataIssues rows so the
/status/recipe-issues dashboard has something to look at.

Every row's description starts with "[MOCK]" so it's trivial to find and
remove afterward -- see delete_mock_recipe_issues.py in this same folder.

Run from backend/ with the project venv:
    ..\\.adam\\Scripts\\python.exe scripts\\seed_mock_recipe_issues.py
"""
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, ".")
from core.supabase import get_supabase  # noqa: E402

sb = get_supabase()

participants = (
    sb.table("UserRoles")
    .select("user_id, participant_id, display_name")
    .eq("role", "participant")
    .order("participant_id")
    .limit(4)
    .execute()
    .data
) or []

if not participants:
    raise SystemExit("No participants found in UserRoles -- can't attach realistic user_ids to mock rows.")

print("Using participants:", [(p["participant_id"], p["display_name"]) for p in participants])

now = datetime.now(timezone.utc)


def day(offset: int) -> str:
    return (now - timedelta(days=offset)).date().isoformat()


def uid(i: int) -> str:
    return participants[i % len(participants)]["user_id"]


rows = [
    # Open, GL issue
    {
        "user_id": uid(0), "meal_date": day(1), "meal_slot": "dinner",
        "recipe_code": "A005844", "recipe_name": "Ragi vermicelli upma",
        "issue_type": "gl_2x", "nutrient": None,
        "planned_value": 18.4, "actual_value": 41.2, "ratio": 2.24,
        "description": "[MOCK] GL 2.2x planned (41.2 vs 18.4) for Ragi vermicelli upma (dinner, " + day(1) + ")",
        "status": "open",
    },
    # Open, nutrient issue (sodium)
    {
        "user_id": uid(1), "meal_date": day(2), "meal_slot": "lunch",
        "recipe_code": "A002211", "recipe_name": "Curd rice",
        "issue_type": "nutrient_2x", "nutrient": "Sodium_mg",
        "planned_value": 95.0, "actual_value": 612.0, "ratio": 6.44,
        "description": "[MOCK] Sodium 6.4x planned (612mg vs 95mg) for Curd rice (lunch, " + day(2) + ")",
        "status": "open",
    },
    # Open, nutrient issue (carbs) -- different participant
    {
        "user_id": uid(2), "meal_date": day(0), "meal_slot": "breakfast",
        "recipe_code": "A001190", "recipe_name": "Idli (2 pcs)",
        "issue_type": "nutrient_2x", "nutrient": "Carbohydrate_g",
        "planned_value": 28.0, "actual_value": 71.5, "ratio": 2.55,
        "description": "[MOCK] Carbohydrate 2.6x planned (71.5g vs 28g) for Idli (2 pcs) (breakfast, " + day(0) + ")",
        "status": "open",
    },
    # Fixed, GL issue
    {
        "user_id": uid(3), "meal_date": day(5), "meal_slot": "snacks",
        "recipe_code": "A003387", "recipe_name": "Banana (1 medium)",
        "issue_type": "gl_2x", "nutrient": None,
        "planned_value": 6.0, "actual_value": 19.8, "ratio": 3.3,
        "description": "[MOCK] GL 3.3x planned (19.8 vs 6.0) for Banana (1 medium) (snacks, " + day(5) + ")",
        "status": "fixed",
        "fixed_at": (now - timedelta(days=1)).isoformat(),
        "fixed_by": "Test Coordinator",
    },
    # Fixed, nutrient issue (fibre) -- a unit/portion correction
    {
        "user_id": uid(0), "meal_date": day(6), "meal_slot": "lunch",
        "recipe_code": "A004456", "recipe_name": "Mixed vegetable sambar",
        "issue_type": "nutrient_2x", "nutrient": "TotalDietaryFibre_FIBTG_g",
        "planned_value": 4.2, "actual_value": 9.8, "ratio": 2.33,
        "description": "[MOCK] TotalDietaryFibre 2.3x planned (9.8g vs 4.2g) for Mixed vegetable sambar (lunch, " + day(6) + ")",
        "status": "fixed",
        "fixed_at": (now - timedelta(hours=6)).isoformat(),
        "fixed_by": "Test Coordinator",
    },
]

resp = sb.table("RecipeDataIssues").insert(rows).execute()
print(f"Inserted {len(resp.data or [])} mock rows.")
