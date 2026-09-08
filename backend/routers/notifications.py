import os
import logging
from datetime import datetime, timezone
from typing import Optional
from services.push import ONESIGNAL_APP_ID, ONESIGNAL_REST_KEY, _get_player_ids

from fastapi import APIRouter, Depends, Header, HTTPException, Query

from core.auth import get_current_user
from core.supabase import get_supabase
from models.schemas import RegisterTokenRequest
from services.push import send_push
from services.reminders import send_meal_reminders as _send_meal_reminders

logger = logging.getLogger("backend.routers.notifications")

router = APIRouter(prefix="/notifications", tags=["notifications"])

_CRON_SECRET = os.getenv("CRON_SECRET", "")


@router.post("/register-token")
def register_token(body: RegisterTokenRequest, user_id: str = Depends(get_current_user)):
    """Register (or refresh) a OneSignal device token for push notifications."""
    sb = get_supabase()
    sb.table("DeviceTokens").upsert(
        {
            "user_id": user_id,
            "device_token": body.device_token,
            "platform": body.platform,
            "last_active": datetime.now(timezone.utc).isoformat(),
        },
        on_conflict="device_token",
    ).execute()
    return {"status": "ok"}


@router.delete("/device-token")
def delete_token(
    device_token: str = Query(..., description="OneSignal player_id to remove"),
    user_id: str = Depends(get_current_user),
):
    """Remove a device token so the user stops receiving push notifications on that device."""
    sb = get_supabase()
    sb.table("DeviceTokens").delete().eq("device_token", device_token).eq(
        "user_id", user_id
    ).execute()
    return {"status": "ok"}


@router.post("/test-push")
def test_push(user_id: str = Depends(get_current_user)):
    """Send a test push notification to all devices registered for the current user.
    Use this to verify OneSignal credentials and device token registration.
    """
    
    if not ONESIGNAL_APP_ID or ONESIGNAL_APP_ID == "your-onesignal-app-id-here":
        raise HTTPException(status_code=424, detail="ONESIGNAL_APP_ID is not set on the backend server")
    if not ONESIGNAL_REST_KEY or ONESIGNAL_REST_KEY == "your-onesignal-rest-api-key-here":
        raise HTTPException(status_code=424, detail="ONESIGNAL_REST_API_KEY is not set on the backend server")

    player_ids = _get_player_ids(user_id)
    if not player_ids:
        raise HTTPException(
            status_code=424,
            detail=f"No device token registered for this account. Open the web app, click 'Notify me when ready', and allow notifications first.",
        )

    sent = send_push(
        user_id=user_id,
        title="Test notification",
        body="Push notifications are working!",
        data={"type": "test"},
    )
    if not sent:
        raise HTTPException(status_code=424, detail="OneSignal API call failed — check server logs for details")
    return {"status": "sent"}


@router.post("/send-reminders")
def send_meal_reminders(
    window_minutes: int = Query(7, description="Half-width of the time window in minutes (default ±7 min)"),
    x_cron_secret: Optional[str] = Header(None, alias="X-Cron-Secret"),
):
    """Send meal-logging reminders to users whose preferred meal time falls within ±window_minutes of now (IST).

    Call this every 15 minutes from a cron job. Protected by X-Cron-Secret header — set CRON_SECRET env var.

    Falls back to default times (Breakfast 08:30, Lunch 13:00, Dinner 19:30 IST) for users with no preference set.

    Notification text:
    - Title: "Reminder: Log your Breakfast / Lunch / Dinner"
    - Body:  "Keeping an accurate diet log helps the study team track your progress."
    """
    if not _CRON_SECRET or x_cron_secret != _CRON_SECRET:
        raise HTTPException(status_code=403, detail="Invalid or missing cron secret")

    results = _send_meal_reminders(window_minutes=window_minutes)
    return {"status": "ok", "recipients": results}


@router.post("/send-missed-slot")
def send_missed_slot_messages(
    x_cron_secret: Optional[str] = Header(None, alias="X-Cron-Secret"),
):
    """Find WhatsApp-linked users' occasions whose escalation time just
    passed with nothing logged for that meal slot, and send a missed-slot
    message for each one that hasn't already gotten one.

    Call this every 15 minutes from a cron job, same cadence and secret as
    /send-reminders. Escalation times: snacks gets a reminder at its own due
    time; breakfast/lunch/dinner instead get a later "did you have X"
    question at 12:30pm / 3:30pm / 8:30am the next day respectively
    (see services.whatsapp_feedback._MISSED_QUESTION_TIME). Idempotent —
    safe to call repeatedly, never sends the same occasion's message twice.
    """
    if not _CRON_SECRET or x_cron_secret != _CRON_SECRET:
        raise HTTPException(status_code=403, detail="Invalid or missing cron secret")

    from services.whatsapp_feedback import check_missed_slots
    counts = check_missed_slots()
    return {"status": "ok", "messages_sent": counts}


@router.post("/send-weekly-digest")
def send_weekly_digest(
    x_cron_secret: Optional[str] = Header(None, alias="X-Cron-Secret"),
):
    """Send each real study participant a one-way WhatsApp summary of the
    past 7 days (meals logged, GL-target hits) — no reply expected, deliberately
    not a poll. Call this once a week (e.g. Sunday evening) from a cron job.
    Protected by X-Cron-Secret, same as /send-reminders.
    """
    if not _CRON_SECRET or x_cron_secret != _CRON_SECRET:
        raise HTTPException(status_code=403, detail="Invalid or missing cron secret")

    from services.whatsapp_feedback import send_weekly_digests
    inserted_ids = send_weekly_digests()
    return {"status": "ok", "messages_sent": len(inserted_ids)}
