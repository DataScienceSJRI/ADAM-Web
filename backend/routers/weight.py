import logging
from datetime import date as date_type
from fastapi import APIRouter, Depends, HTTPException
from core.auth import get_current_user
from core.roles import require_coordinator
from core.supabase import get_supabase
from models.schemas import WeightLogRequest, WeightLogUpdateRequest, WeightLogResponse, WeightLogItem
from services.recommendation_writer import get_plan_status

logger = logging.getLogger("backend.routers.weight")

router = APIRouter(prefix="/weight", tags=["weight"])

_MIN_KG = 20.0
_MAX_KG = 300.0
_MAX_DELTA_KG = 5.0

_SAFETY_MESSAGE = (
    "This weight value violates our safety/tolerance rules "
    "(too far from your previous log, or outside the allowed bounds)."
)


def _validate_weight(weight_kg: float) -> None:
    if not (_MIN_KG <= weight_kg <= _MAX_KG):
        raise HTTPException(
            status_code=422,
            detail={
                "message": _SAFETY_MESSAGE,
                "error_code": "out_of_bounds",
                "weight_kg": weight_kg,
                "min_kg": _MIN_KG,
                "max_kg": _MAX_KG,
            },
        )


def _validate_against_anchor(weight_kg: float, anchor_kg: float | None) -> None:
    if anchor_kg is None:
        return
    delta = abs(weight_kg - anchor_kg)
    if delta > _MAX_DELTA_KG:
        raise HTTPException(
            status_code=422,
            detail={
                "message": _SAFETY_MESSAGE,
                "error_code": "tolerance_exceeded",
                "weight_kg": weight_kg,
                "anchor_kg": anchor_kg,
                "max_delta_kg": _MAX_DELTA_KG,
            },
        )


def _cycle_bounds_for_date(user_id: str, log_date: date_type) -> tuple[date_type, date_type] | None:
    """Return the (start_date, end_date) of the plan cycle containing log_date, if any."""
    for p in get_plan_status(user_id)["plans"]:
        start, end = p.get("start_date"), p.get("end_date")
        if start and end and date_type.fromisoformat(start) <= log_date <= date_type.fromisoformat(end):
            return date_type.fromisoformat(start), date_type.fromisoformat(end)
    return None


def _onboarding_weight(sb, user_id: str) -> float | None:
    bd = (
        sb.table("BE_Basic_Details")
        .select("Weight")
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    return bd.data[0]["Weight"] if bd.data and bd.data[0].get("Weight") is not None else None


def _anchor_weight(sb, user_id: str, log_date: date_type, exclude_log_id: str | None = None) -> float | None:
    bounds = _cycle_bounds_for_date(user_id, log_date)
    if bounds:
        start, end = bounds
        resp = (
            sb.table("user_weight_log")
            .select("id, weight_kg")
            .eq("user_id", user_id)
            .gte("date", start.isoformat())
            .lte("date", end.isoformat())
            .order("date")
            .limit(2)
            .execute()
        )
        rows = [r for r in (resp.data or []) if r.get("id") != exclude_log_id]
        if rows:
            return rows[0]["weight_kg"]

    prior = (
        sb.table("user_weight_log")
        .select("id, weight_kg")
        .eq("user_id", user_id)
        .order("date", desc=True)
        .limit(2)
        .execute()
    )
    prior_rows = [r for r in (prior.data or []) if r.get("id") != exclude_log_id]
    if prior_rows:
        return prior_rows[0]["weight_kg"]

    return _onboarding_weight(sb, user_id)


# ─── Participant endpoints ──────────────────────────────────────────────────────

@router.get("/logs", response_model=list[WeightLogItem])
def get_weight_logs(user_id: str = Depends(get_current_user)):
    """Retrieve the weight log entries for the authenticated user."""
    sb = get_supabase()
    resp = (
        sb.table("user_weight_log")
        .select("*")
        .eq("user_id", user_id)
        .order("date", desc=True)
        .execute()
    )
    return [
        WeightLogItem(id=str(r.get("id", "")), weight_kg=r.get("weight_kg"), date=r.get("date"))
        for r in (resp.data or [])
    ]


@router.post("/log", response_model=WeightLogResponse)
def log_weight(body: WeightLogRequest, user_id: str = Depends(get_current_user)):
    """Log a weight entry for the authenticated user (one per date)."""
    _validate_weight(body.weight_kg)
    sb = get_supabase()
    date_str = body.date or str(date_type.today())
    _validate_against_anchor(body.weight_kg, _anchor_weight(sb, user_id, date_type.fromisoformat(date_str)))

    existing = (
        sb.table("user_weight_log")
        .select("id")
        .eq("user_id", user_id)
        .eq("date", date_str)
        .execute()
    )
    if existing.data:
        raise HTTPException(
            status_code=409,
            detail="A weight log already exists for this date. Edit the existing entry instead.",
        )

    resp = (
        sb.table("user_weight_log")
        .insert({"user_id": user_id, "weight_kg": body.weight_kg, "date": date_str})
        .execute()
    )
    if not resp.data:
        raise HTTPException(status_code=500, detail="Failed to log weight.")
    return WeightLogResponse(status="ok", id=str(resp.data[0].get("id", "")))


@router.patch("/logs/{log_id}", response_model=WeightLogItem)
def update_weight_log(
    log_id: str,
    body: WeightLogUpdateRequest,
    user_id: str = Depends(get_current_user),
):
    """Update a weight log entry belonging to the authenticated user."""
    if body.weight_kg is not None:
        _validate_weight(body.weight_kg)

    sb = get_supabase()
    existing = (
        sb.table("user_weight_log")
        .select("id, date")
        .eq("id", log_id)
        .eq("user_id", user_id)
        .execute()
    )
    if not existing.data:
        raise HTTPException(status_code=404, detail="Log entry not found.")

    if body.weight_kg is not None:
        entry_date = body.date or existing.data[0].get("date")
        _validate_against_anchor(
            body.weight_kg,
            _anchor_weight(sb, user_id, date_type.fromisoformat(entry_date), exclude_log_id=log_id),
        )

    update_data: dict = {}
    if body.weight_kg is not None:
        update_data["weight_kg"] = body.weight_kg
    if body.date is not None:
        dup = (
            sb.table("user_weight_log")
            .select("id")
            .eq("user_id", user_id)
            .eq("date", body.date)
            .neq("id", log_id)
            .execute()
        )
        if dup.data:
            raise HTTPException(status_code=409, detail="Another log already exists for this date.")
        update_data["date"] = body.date

    if not update_data:
        raise HTTPException(status_code=400, detail="No fields to update.")

    resp = (
        sb.table("user_weight_log")
        .update(update_data)
        .eq("id", log_id)
        .eq("user_id", user_id)
        .execute()
    )
    if not resp.data:
        raise HTTPException(status_code=500, detail="Failed to update.")
    r = resp.data[0]
    return WeightLogItem(id=str(r.get("id", "")), weight_kg=r.get("weight_kg"), date=r.get("date"))


@router.delete("/logs/{log_id}", status_code=204)
def delete_weight_log(log_id: str, user_id: str = Depends(get_current_user)):
    """Delete a weight log entry belonging to the authenticated user."""
    sb = get_supabase()
    existing = (
        sb.table("user_weight_log")
        .select("id")
        .eq("id", log_id)
        .eq("user_id", user_id)
        .execute()
    )
    if not existing.data:
        raise HTTPException(status_code=404, detail="Log entry not found.")
    sb.table("user_weight_log").delete().eq("id", log_id).eq("user_id", user_id).execute()


# ─── Coordinator endpoints ──────────────────────────────────────────────────────

@router.get("/coordinator")
def coordinator_list_participants(
    user_id: str = Depends(get_current_user),
    role: str = Depends(require_coordinator),
):
    """Return participants with latest weight log info (coordinator-only)."""
    sb = get_supabase()
    q = sb.table("UserRoles").select("user_id, participant_id, display_name").eq("role", "participant")
    if role == "coordinator":
        q = q.eq("coordinator_id", user_id)
    participants = q.execute().data or []

    if not participants:
        return []

    participant_ids = [p["user_id"] for p in participants]
    logs = (
        sb.table("user_weight_log")
        .select("id, user_id, weight_kg, date")
        .in_("user_id", participant_ids)
        .order("date", desc=True)
        .limit(5000)
        .execute()
        .data
    ) or []

    logs_by_user: dict = {}
    for log in logs:
        uid = log["user_id"]
        logs_by_user.setdefault(uid, []).append(log)

    result = []
    for p in participants:
        pid = p["user_id"]
        user_logs = logs_by_user.get(pid, [])
        latest = user_logs[0] if user_logs else None
        result.append({
            "user_id": pid,
            "participant_id": p.get("participant_id"),
            "display_name": p.get("display_name"),
            "total_logs": len(user_logs),
            "latest_weight_kg": latest["weight_kg"] if latest else None,
            "latest_date": latest["date"] if latest else None,
        })

    return result


@router.get("/coordinator/{participant_id}", response_model=list[WeightLogItem])
def coordinator_get_weight_logs(
    participant_id: str,
    user_id: str = Depends(get_current_user),
    role: str = Depends(require_coordinator),
):
    """Return all weight logs for a specific participant (coordinator-only)."""
    sb = get_supabase()
    if role == "coordinator":
        p = (
            sb.table("UserRoles")
            .select("user_id")
            .eq("user_id", participant_id)
            .eq("coordinator_id", user_id)
            .execute()
        )
        if not p.data:
            raise HTTPException(status_code=404, detail="Participant not found.")

    resp = (
        sb.table("user_weight_log")
        .select("*")
        .eq("user_id", participant_id)
        .order("date", desc=True)
        .execute()
    )
    return [
        WeightLogItem(id=str(r.get("id", "")), weight_kg=r.get("weight_kg"), date=r.get("date"))
        for r in (resp.data or [])
    ]


@router.patch("/coordinator/{participant_id}/logs/{log_id}", response_model=WeightLogItem)
def coordinator_update_weight_log(
    participant_id: str,
    log_id: str,
    body: WeightLogUpdateRequest,
    user_id: str = Depends(get_current_user),
    role: str = Depends(require_coordinator),
):
    """Update a participant's weight log entry (coordinator-only)."""
    if body.weight_kg is not None:
        _validate_weight(body.weight_kg)

    sb = get_supabase()
    if role == "coordinator":
        p = (
            sb.table("UserRoles")
            .select("user_id")
            .eq("user_id", participant_id)
            .eq("coordinator_id", user_id)
            .execute()
        )
        if not p.data:
            raise HTTPException(status_code=404, detail="Participant not found.")

    existing = (
        sb.table("user_weight_log")
        .select("id")
        .eq("id", log_id)
        .eq("user_id", participant_id)
        .execute()
    )
    if not existing.data:
        raise HTTPException(status_code=404, detail="Log entry not found.")

    update_data: dict = {}
    if body.weight_kg is not None:
        update_data["weight_kg"] = body.weight_kg
    if body.date is not None:
        dup = (
            sb.table("user_weight_log")
            .select("id")
            .eq("user_id", participant_id)
            .eq("date", body.date)
            .neq("id", log_id)
            .execute()
        )
        if dup.data:
            raise HTTPException(status_code=409, detail="Another log already exists for this date.")
        update_data["date"] = body.date

    if not update_data:
        raise HTTPException(status_code=400, detail="No fields to update.")

    resp = (
        sb.table("user_weight_log")
        .update(update_data)
        .eq("id", log_id)
        .eq("user_id", participant_id)
        .execute()
    )
    if not resp.data:
        raise HTTPException(status_code=500, detail="Failed to update.")
    r = resp.data[0]
    return WeightLogItem(id=str(r.get("id", "")), weight_kg=r.get("weight_kg"), date=r.get("date"))


@router.delete("/coordinator/{participant_id}/logs/{log_id}", status_code=204)
def coordinator_delete_weight_log(
    participant_id: str,
    log_id: str,
    user_id: str = Depends(get_current_user),
    role: str = Depends(require_coordinator),
):
    """Delete a participant's weight log entry (coordinator-only)."""
    sb = get_supabase()
    if role == "coordinator":
        p = (
            sb.table("UserRoles")
            .select("user_id")
            .eq("user_id", participant_id)
            .eq("coordinator_id", user_id)
            .execute()
        )
        if not p.data:
            raise HTTPException(status_code=404, detail="Participant not found.")

    existing = (
        sb.table("user_weight_log")
        .select("id")
        .eq("id", log_id)
        .eq("user_id", participant_id)
        .execute()
    )
    if not existing.data:
        raise HTTPException(status_code=404, detail="Log entry not found.")
    sb.table("user_weight_log").delete().eq("id", log_id).eq("user_id", participant_id).execute()
