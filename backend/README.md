# ADAM Web — Backend

FastAPI service that generates personalised 7-day meal plans for ADAM study participants and writes them to Supabase.

## Tech Stack

- **Framework:** FastAPI + Uvicorn
- **Language:** Python 3.11+
- **Optimisation:** PuLP (LP solver)
- **Data:** pandas, numpy
- **Database:** Supabase (via `supabase-py` v2)
- **Config:** python-dotenv

## Project Structure

```
backend/
├── main.py                        # FastAPI app, CORS, router registration
├── Functions_Base.py              # Core ML/LP model — DO NOT MODIFY
├── requirements.txt
├── core/
│   ├── supabase.py                # Supabase client singleton (lru_cache)
│   └── auth.py                    # JWT auth — extracts user_id from Supabase token
├── models/
│   └── schemas.py                 # Pydantic request/response schemas
├── routers/
│   └── plan.py                    # POST /plan, GET /plan/status, DELETE /plan
│                                  # ModelOptimiser subclass defined here
└── services/
    ├── data_loader.py             # Fetches Supabase tables → ds dict for model
    ├── profile_builder.py         # Builds user profile from onboarding tables
    ├── recommendation_writer.py   # Writes weekly_menu → Recommendation table
    └── lp_optimizer.py            # Custom LP (relaxed macro constraints)
```

## API Endpoints

All `/plan` endpoints require a Supabase JWT in the `Authorization: Bearer <token>` header. The `user_id` is extracted from the token automatically.

## Architecture

```
POST /plan
  └─ get_current_user()              ← extracts user email from JWT
  └─ build_profile(user_id)          ← BE_Basic_Details + BE_Preference_onboarding_details
  └─ ModelOptimiser.run()
       ├─ load_data()                 ← data_loader fetches all Recipe/preference tables
       └─ optimize_weekly_menu()      ← lp_optimizer (relaxed constraints)
  └─ write_recommendations()         ← writes rows to Recommendation table with plan_id
```

`ModelOptimiser` subclasses `ADAMPersonalizationModel` (in `Functions_Base.py`) to inject Supabase data without modifying the core model.

## Supabase Tables

| Table | Used for |
|-------|----------|
| `BE_Basic_Details` | User demographics (Age, Gender, Weight, Height, Hba1c, Activity_levels) |
| `BE_Preference_onboarding` | User meal preferences (meal_time, dish_type, sub_category, Reaction) |
| `BE_Preference_onboarding_details` | Dietary details (diet_restrictions, meal times) |
| `Recipe` | Recipe nutrition data |
| `RecipeTagging` | Recipe meal-time and diet flags |
| `SubCategory` | Subcategory code → name mapping |
| `MainCode` | Main1→Main2 meal pairing |
| `BaseEar` / `BaseTul` | Nutrient EAR/TUL requirements |
| `DataModelling` | Glucose response data per meal |
| `RecipeINGDBFormat` | Ingredient data for sugar/salt constraints |
| `Recommendation` | Output — written by this service (includes `plan_id` for history) |

### Required DB migration

```sql
-- Add plan_id column to support plan history
ALTER TABLE "Recommendation" ADD COLUMN plan_id text;
```

## Getting Started

### Prerequisites

- Python 3.11+
- A Supabase project with the tables above

### Installation

```bash
cd backend
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### Environment Variables

Create a `.env` file in the `backend/` directory (see `.env.example`):

```env
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SERVICE_KEY=your_service_role_key
```

> Use the **service role key** (not the anon key) so the backend can read all tables without RLS restrictions.

### Running

```bash
uvicorn main:app --reload --port 8000
```

API docs available at [http://localhost:8000/docs](http://localhost:8000/docs).

## Known Limitations

- The LP solver falls back to an unoptimised plan for Indian food — hard macro constraints (carbs 45–50%) in `Functions_Base` cannot be satisfied by high-carb Indian recipes. The custom `lp_optimizer.py` relaxes these.
- `load_data()` is called twice internally by `Functions_Base.run()` when `user_preference="yes"`, doubling Supabase queries. This is a known limitation that cannot be fixed without modifying `Functions_Base.py`.
- GL scoring is disabled — the `SubCategory_GI_GL` table does not exist in Supabase.
- using `MainCode`.
- `RecipeINGDBFormat` table is empty — sugar/salt constraints are skipped.

