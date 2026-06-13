import logging
from datetime import date as date_type
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from core.auth import get_current_user
from core.supabase import get_supabase
from models.schemas import ActivityLogRequest, ActivityLogResponse, ActivityHistoryItem, ActivityHistoryResponse
from services.activity import log_activity

logger = logging.getLogger("backend.routers.activity")

router = APIRouter(prefix="/activity", tags=["activity"])


MAX_ACTIVITY_LOGS = 10


@router.post("/log", response_model=ActivityLogResponse)
def activity_log(body: ActivityLogRequest, user_id: str = Depends(get_current_user)):
    """Log a physical activity entry for the authenticated user."""
    sb = get_supabase()
    count_resp = (
        sb.table("user_physical_activity_recall")
        .select("ID", count="exact")
        .eq("UID", user_id)
        .eq("Date", body.date or str(date_type.today()))
        .execute()
    )
    if (count_resp.count or 0) >= MAX_ACTIVITY_LOGS:
        raise HTTPException(
            status_code=400,
            detail=f"Maximum of {MAX_ACTIVITY_LOGS} activities per day already reached.",
        )
    activity_id = log_activity(
        user_id=user_id,
        pa_name=body.pa_name,
        duration_min=body.duration_min,
        intensity=body.intensity,
        date=body.date,
    )
    return ActivityLogResponse(status="ok", activity_id=activity_id)


@router.get("", response_model=ActivityHistoryResponse)
def get_activity_history(
    date: Optional[str] = Query(None, description="Filter by date YYYY-MM-DD"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user_id: str = Depends(get_current_user),
):
    """Return the authenticated user's activity log history."""
    sb = get_supabase()
    query = sb.table("user_physical_activity_recall").select("*", count="exact").eq("UID", user_id)
    if date:
        query = query.eq("Date", date)
    query = query.order("Date", desc=True).range(offset, offset + limit - 1)
    resp = query.execute()
    items = [
        ActivityHistoryItem(
            id=str(r.get("ID", "")),
            pa_name=r.get("PA_Name"),
            duration_min=r.get("Duration"),
            intensity=r.get("intensity"),
            time_of_day=r.get("Time"),
            date=r.get("Date"),
        )
        for r in (resp.data or [])
    ]
    return ActivityHistoryResponse(items=items, total=resp.count or len(items))


@router.delete("/{activity_id}")
def delete_activity(activity_id: str, user_id: str = Depends(get_current_user)):
    """Delete an activity log entry belonging to the authenticated user."""
    sb = get_supabase()
    resp = sb.table("user_physical_activity_recall").delete().eq("ID", activity_id).eq("UID", user_id).execute()
    if not resp.data:
        raise HTTPException(status_code=404, detail="Activity log not found")
    return {"status": "deleted", "id": activity_id}
