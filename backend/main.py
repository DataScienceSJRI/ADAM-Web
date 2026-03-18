import os
import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from routers import plan

# Configure simple logging for the backend
logging.basicConfig(
    format="[%(asctime)s] %(levelname)s %(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("backend")

app = FastAPI(title="ADAM Meal Plan API", version="1.0.0")

_raw = os.environ.get("ALLOWED_ORIGINS", "http://localhost:3000")
_origins = [o.strip() for o in _raw.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(plan.router)


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
