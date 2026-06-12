import logging
import os
import re
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from core.auth import get_current_user
from core.roles import get_current_role, require_coordinator
from core.supabase import get_supabase

logger = logging.getLogger("backend.routers.users")
router = APIRouter(prefix="/users", tags=["users"])

_PARTICIPANT_PASSWORD = os.getenv("PARTICIPANT_DEFAULT_PASSWORD", "")


class CreateParticipantRequest(BaseModel):
    display_name: str


class ParticipantResponse(BaseModel):
    user_id: str
    participant_id: str
    display_name: str | None
    coordinator_id: str | None
    plan_status: str | None = None
    last_plan_at: str | None = None
    created_at: str | None = None
    password: str | None = None


@router.post("", response_model=ParticipantResponse)
def create_participant(
    body: CreateParticipantRequest,
    coordinator_id: str = Depends(get_current_user),
    role: str = Depends(require_coordinator),
):
    """Create a new participant account. Only coordinators and admins can do this."""
    sb = get_supabase()

    # Auto-generate next participant ID (P001_JOHN, P002_PRIYA, ...)
    existing = sb.table("UserRoles").select("participant_id").eq("role", "participant").execute()
    max_num = 0
    for row in (existing.data or []):
        pid = row.get("participant_id") or ""
        m = re.match(r"^P(\d+)", pid.upper())
        if m:
            max_num = max(max_num, int(m.group(1)))

    # Build name slug: first word of display_name, uppercase letters/digits only, max 10 chars
    first_word = (body.display_name.strip().split()[0] if body.display_name.strip() else "")
    name_slug = re.sub(r"[^A-Z0-9]", "", first_word.upper())[:10]
    participant_id = f"P{max_num + 1:03d}_{name_slug}" if name_slug else f"P{max_num + 1:03d}"

    email = f"{participant_id}@adam.participant"

    # Create Supabase auth account — non-fatal so the UserRoles entry is always created
    # even if auth account creation fails (coordinator can create it manually later).
    auth_ok = False
    if _PARTICIPANT_PASSWORD:
        try:
            sb.auth.admin.create_user({
                "email": email,
                "password": _PARTICIPANT_PASSWORD,
                "email_confirm": True,
            })
            auth_ok = True
        except Exception as exc:
            logger.warning("Could not create auth account for %s: %s", participant_id, exc)
    else:
        logger.warning("PARTICIPANT_DEFAULT_PASSWORD not set — skipping auth account creation for %s", participant_id)

    sb.table("UserRoles").insert({
        "user_id": participant_id,
        "role": "participant",
        "coordinator_id": coordinator_id,
        "display_name": body.display_name.strip(),
        "participant_id": participant_id,
    }).execute()

    logger.info("Created participant %s by coordinator %s (auth_account=%s)", participant_id, coordinator_id, auth_ok)
    return ParticipantResponse(
        user_id=participant_id,
        participant_id=participant_id,
        display_name=body.display_name.strip(),
        coordinator_id=coordinator_id,
        password=_PARTICIPANT_PASSWORD if auth_ok else None,
    )


@router.get("", response_model=list[ParticipantResponse])
def list_participants(
    user_id: str = Depends(get_current_user),
    role: str = Depends(require_coordinator),
):
    """List participants. Admin sees all; coordinator sees only their own."""
    sb = get_supabase()
    query = sb.table("UserRoles").select(
        "user_id, participant_id, display_name, coordinator_id, created_at"
    ).eq("role", "participant")
    if role == "coordinator":
        query = query.eq("coordinator_id", user_id)
    participants = query.order("created_at", desc=True).execute().data or []

    if not participants:
        return []

    # Enrich with latest plan status

    p_ids = [p["user_id"] for p in participants]
    sessions = (
        sb.table("BE_Onboarding_Sessions")
        .select("user_id, plan_status, created_at, plan_id")
        .in_("user_id", p_ids)
        .order("created_at", desc=True)
        .execute()
        .data or []
    )
    session_map: dict = {}
    for s in sessions:
        uid = s.get("user_id")
        if uid and uid not in session_map:
            session_map[uid] = s

    result = []
    for p in participants:
        s = session_map.get(p["user_id"], {})
        result.append(ParticipantResponse(
            user_id=p["user_id"],
            participant_id=p.get("participant_id") or "",
            display_name=p.get("display_name"),
            coordinator_id=p.get("coordinator_id"),
            plan_status=s.get("plan_status"),
            last_plan_at=s.get("created_at"),
            created_at=p.get("created_at"),
        ))
    return result


@router.get("/me/role")
def get_my_role(
    user_id: str = Depends(get_current_user),
    role: str = Depends(get_current_role),
):
    sb = get_supabase()
    row = sb.table("UserRoles").select("display_name, participant_id").eq("user_id", user_id).limit(1).execute()
    info = row.data[0] if row.data else {}
    return {
        "user_id": user_id,
        "role": role,
        "display_name": info.get("display_name"),
        "participant_id": info.get("participant_id"),
    }
