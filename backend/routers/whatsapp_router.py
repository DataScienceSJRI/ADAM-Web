import logging
import os
import re
from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Request

from core.auth import get_current_user
from core.roles import require_coordinator
from core.supabase import get_supabase
from models.schemas import LinkPhoneRequest
from services.whatsapp_gateway import IncomingMessage, get_gateway

logger = logging.getLogger("backend.routers.whatsapp")
router = APIRouter(prefix="/whatsapp", tags=["whatsapp"])

_WEBHOOK_SECRET = os.getenv("WAHA_WEBHOOK_SECRET", "")
_IST = timezone(timedelta(hours=5, minutes=30))

_NOT_LINKED_REPLY = (
    "This number isn't linked to an ADAM account yet. Ask your study coordinator to "
    "link it, then send #HELLOADAM to activate."
)
_NOT_ACTIVATED_REPLY = "Send #HELLOADAM to activate meal reminders and plan updates on this number."
_WELCOME_REPLY = "You're activated! You'll get meal reminders and plan updates here."
_FALLBACK_REPLY = (
    "This line sends meal reminders and plan updates only — for help, contact your study coordinator."
)


def handle_message(msg: IncomingMessage) -> None:
    sb = get_supabase()
    gateway = get_gateway()

    link_resp = sb.table("WH_Users").select("*").eq("phone", msg.phone).limit(1).execute()
    if not link_resp.data:
        gateway.send_text(msg.phone, _NOT_LINKED_REPLY)
        return

    link = link_resp.data[0]
    user_id = link["user_id"]

    sb.table("WH_Users").update(
        {"last_message_at": datetime.now(timezone.utc).isoformat()}
    ).eq("phone", msg.phone).execute()

    text = (msg.text or "").strip()
    text_upper = text.upper()

    if text_upper == "#HELLOADAM":
        if not link.get("activated_at"):
            sb.table("WH_Users").update(
                {"activated_at": datetime.now(timezone.utc).isoformat()}
            ).eq("phone", msg.phone).execute()
        gateway.send_text(msg.phone, _WELCOME_REPLY)
        return

    if not link.get("activated_at"):
        gateway.send_text(msg.phone, _NOT_ACTIVATED_REPLY)
        return

    if text_upper == "#NEXTPLAN" or "next plan" in text.lower():
        session_resp = (
            sb.table("BE_Onboarding_Sessions")
            .select("next_plan_at")
            .eq("user_id", user_id)
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        next_plan_at = session_resp.data[0].get("next_plan_at") if session_resp.data else None
        if next_plan_at:
            gateway.send_text(msg.phone, f"Your next plan is scheduled for {next_plan_at}.")
        else:
            gateway.send_text(msg.phone, "No plan is currently scheduled.")
        return

    gateway.send_text(msg.phone, _FALLBACK_REPLY)


@router.post("/webhook")
async def webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    x_webhook_secret: Optional[str] = Header(None, alias="X-Webhook-Secret"),
):
    if _WEBHOOK_SECRET and x_webhook_secret != _WEBHOOK_SECRET:
        raise HTTPException(status_code=403, detail="Invalid or missing webhook secret")

    payload = await request.json()
    msg = get_gateway().parse_incoming(payload)
    if msg is None or not msg.phone:
        return {"status": "ignored"}

    background_tasks.add_task(handle_message, msg)
    return {"status": "received"}


@router.post("/link")
def link_phone(
    body: LinkPhoneRequest,
    coordinator_id: str = Depends(get_current_user),
    role: str = Depends(require_coordinator),
):
    phone = re.sub(r"\D", "", body.phone)
    if not phone:
        raise HTTPException(status_code=400, detail="Invalid phone number")

    sb = get_supabase()
    sb.table("WH_Users").upsert(
        {
            "phone": phone,
            "user_id": body.user_id,
            "linked_by": coordinator_id,
            "linked_at": datetime.now(timezone.utc).isoformat(),
        },
        on_conflict="phone",
    ).execute()
    logger.info("Linked phone for user_id=%s by coordinator=%s", body.user_id, coordinator_id)
    return {"status": "ok"}


@router.delete("/link/{user_id}")
def unlink_phone(
    user_id: str,
    coordinator_id: str = Depends(get_current_user),
    role: str = Depends(require_coordinator),
):
    sb = get_supabase()
    sb.table("WH_Users").delete().eq("user_id", user_id).execute()
    logger.info("Unlinked WhatsApp for user_id=%s by coordinator=%s", user_id, coordinator_id)
    return {"status": "ok"}
