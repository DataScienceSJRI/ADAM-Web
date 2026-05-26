import os
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query

from core.auth import get_current_user
from core.supabase import get_supabase
from models.schemas import RegisterTokenRequest
from services.push import send_bulk_push, send_push

logger = logging.getLogger("backend.routers.notifications")

router = APIRouter(prefix="/notifications", tags=["notifications"])

_CRON_SECRET = os.getenv("CRON_SECRET", "")

# Times stored in DB are IST (UTC+5:30); we compare against current IST time
_IST = timezone(timedelta(hours=5, minutes=30))

# Default meal times (HH, MM) used when a user has no preference set
_DEFAULTS: dict[str, tuple[int, int]] = {
    "breakfast": (8, 30),
    "lunch": (13, 0),
    "dinner": (19, 30),
}

_SLOT_LABELS = {
    "breakfast": "Breakfast",
    "lunch": "Lunch",
    "dinner": "Dinner",
}


def _time_to_minutes(time_str: str, default: tuple[int, int]) -> int:
    try:
        parts = time_str.split(":")
        return int(parts[0]) * 60 + int(parts[1])
    except Exception:
        return default[0] * 60 + default[1]


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
    sent = send_push(
        user_id=user_id,
        title="Test notification",
        body="Push notifications are working!",
        data={"type": "test"},
    )
    if not sent:
        raise HTTPException(
            status_code=424,
            detail="Not sent — check ONESIGNAL_APP_ID / ONESIGNAL_REST_API_KEY env vars, or register a device token first",
        )
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

    sb = get_supabase()

    # --- Gather all registered device tokens, grouped by user_id ---
    tokens_resp = sb.table("DeviceTokens").select("user_id, device_token").execute()
    user_tokens: dict[str, list[str]] = {}
    for row in (tokens_resp.data or []):
        uid = row.get("user_id")
        token = row.get("device_token")
        if uid and token:
            user_tokens.setdefault(uid, []).append(token)

    if not user_tokens:
        return {"status": "ok", "message": "No registered devices", "recipients": {}}

    # --- Fetch meal time preferences for all users with tokens ---
    all_user_ids = list(user_tokens.keys())
    prefs_resp = (
        sb.table("BE_Preference_onboarding_details")
        .select("user_id, breakfast_time, lunch_time, dinner_time")
        .in_("user_id", all_user_ids)
        .execute()
    )
    user_prefs: dict[str, dict] = {r["user_id"]: r for r in (prefs_resp.data or [])}

    # --- Compare against current IST time ---
    now_ist = datetime.now(_IST)
    now_minutes = now_ist.hour * 60 + now_ist.minute

    # Collect player IDs per slot
    slot_player_ids: dict[str, list[str]] = {"breakfast": [], "lunch": [], "dinner": []}

    for uid, player_ids in user_tokens.items():
        prefs = user_prefs.get(uid, {})
        for slot, default in _DEFAULTS.items():
            raw_time = prefs.get(f"{slot}_time") or ""
            meal_minutes = _time_to_minutes(raw_time, default) if raw_time else (default[0] * 60 + default[1])
            if abs(now_minutes - meal_minutes) <= window_minutes:
                slot_player_ids[slot].extend(player_ids)

    # --- Send one notification per active slot ---
    results: dict[str, int] = {}
    for slot, player_ids in slot_player_ids.items():
        if not player_ids:
            continue
        label = _SLOT_LABELS[slot]
        count = send_bulk_push(
            player_ids=player_ids,
            title=f"Reminder: Log your {label}",
            body="Keeping an accurate diet log helps the study team track your progress.",
            data={"type": "meal_reminder", "meal_slot": slot},
        )
        results[slot] = count
        logger.info("Meal reminder sent: slot=%s recipients=%d", slot, count)

    return {"status": "ok", "recipients": results}
