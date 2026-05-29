import os
import logging
from dotenv import load_dotenv
load_dotenv(override=True)

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from routers import auth, profile, plan, daily, reaction, recall, activity, recipes, notifications, kpi

# Configure simple logging for the backend
logging.basicConfig(
    format="[%(asctime)s] %(levelname)s %(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("backend")

_tags_metadata = [
    {
        "name": "auth",
        "description": "Login, logout, token refresh. All other endpoints require `Authorization: Bearer <access_token>`.",
    },
    {
        "name": "user",
        "description": "Read and update the authenticated user's profile (age, weight, diet type, meal times).",
    },
    {
        "name": "plan",
        "description": "Generate a 7-day personalised meal plan, view daily meals, and request food swaps (pre-approved or on-demand).",
    },
    {
        "name": "reaction",
        "description": "Like or dislike a meal combination. Used to personalise future plans.",
    },
    {
        "name": "recall",
        "description": "Log what the user actually ate (as planned, something different, or skipped). Supports text and photo logging.",
    },
    {
        "name": "activity",
        "description": "Log and view physical activity entries.",
    },
    {
        "name": "recipes",
        "description": "Browse and search the recipe catalogue. Use `/recipes/search?q=` for plain-text search.",
    },
    {
        "name": "notifications",
        "description": "Register/remove device tokens and send push notifications. "
                       "`POST /send-reminders` is cron-protected (X-Cron-Secret header) and sends meal-logging reminders "
                       "to users whose preferred meal time falls within the configured window.",
    },
]

_root_path = os.environ.get("ROOT_PATH", "")

app = FastAPI(
    title="ADAM API",
    version="1.0.0",
    root_path=_root_path,
    description="""
## ADAM — Personalised Meal Planning for Diabetics

This API powers the ADAM mobile app. It handles authentication, meal plan generation,
daily meal viewing, food swaps, diet recall logging, activity tracking, and push notifications.

### Authentication
All endpoints (except `/auth/login`, `/auth/token`, `/auth/refresh`) require a Bearer token.

Get a token from `POST /auth/login`, then click **Authorize** at the top and paste it.

### Image Uploads
Meal photos are uploaded **directly to Supabase Storage** by the Flutter app.
Pass the resulting public URL to `POST /recall/image`.

### Typical Flutter App Flow
1. `POST /auth/login` → store `access_token` + `refresh_token`
2. `GET /plan/daily` → display today's meals
3. `POST /recall/log` → user confirms they ate as planned
4. `GET /plan/replacements` → show swap options
5. `POST /plan/replacements/request` → confirm a food swap
6. `POST /plan/reaction` → like / dislike a meal
7. `POST /activity/log` → log physical activity
""",
    openapi_tags=_tags_metadata,
)

_raw = os.environ.get("ALLOWED_ORIGINS", "http://localhost:3000")
_origins = [o.strip() for o in _raw.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class PrivateNetworkAccessMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        if request.headers.get("Access-Control-Request-Private-Network"):
            response.headers["Access-Control-Allow-Private-Network"] = "true"
        return response

app.add_middleware(PrivateNetworkAccessMiddleware)

V1 = "/api/v1"

app.include_router(auth.router,          prefix=V1)
app.include_router(profile.router,       prefix=V1)
app.include_router(plan.router,          prefix=V1)
app.include_router(daily.router,         prefix=V1)
app.include_router(reaction.router,      prefix=V1)
app.include_router(recall.router,        prefix=V1)
app.include_router(activity.router,      prefix=V1)
app.include_router(recipes.router,       prefix=V1)
app.include_router(notifications.router, prefix=V1)
app.include_router(kpi.router,           prefix=V1)


@app.get("/health")
def health():
    from core.supabase import get_supabase
    try:
        get_supabase().table("Recipe").select("Recipe_Code").limit(1).execute()
        db = "ok"
    except Exception as exc:
        logger.error("Health check: Supabase unreachable: %s", exc)
        db = "unreachable"
    return {"status": "ok" if db == "ok" else "degraded", "db": db}
