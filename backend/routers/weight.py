import logging
from datetime import date as date_type
from fastapi import APIRouter, Depends, HTTPException
from core.auth import get_current_user
from core.supabase import get_supabase
from models.schemas import WeightLogRequest, WeightLogResponse, WeightLogItem

logger = logging.getLogger("backend.routers.weight")

router = APIRouter(prefix="/weight", tags=["weight"])

@router.get("/logs", response_model=list[WeightLogItem])
def get_weight_logs(user_id: str = Depends(get_current_user)):
    """Retrieve the weight log entries for the authenticated user."""
    sb = get_supabase()
    resp = sb.table("user_weight_log").select("*").eq("user_id", user_id).order("date", desc=True).execute()
    return [
        WeightLogItem(id=str(r.get("id", "")), weight_kg=r.get("weight_kg"), date=r.get("date"))
        for r in (resp.data or [])
    ]


@router.post("/log", response_model=WeightLogResponse)
def log_weight(body: WeightLogRequest, user_id: str = Depends(get_current_user)):
    """Log a weight entry for the authenticated user."""
    sb = get_supabase()
    resp = (
        sb.table("user_weight_log")
        .insert({
            "user_id": user_id,
            "weight_kg": body.weight_kg,
            "date": body.date or str(date_type.today()),
        })
        .execute()
    )
    if not resp.data:
        raise HTTPException(status_code=500, detail="Failed to log weight.")
    return WeightLogResponse(status="ok", id=str(resp.data[0].get("id", "")))




