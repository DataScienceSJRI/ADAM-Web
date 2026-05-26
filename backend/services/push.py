import os
import logging
import httpx
from core.supabase import get_supabase

logger = logging.getLogger("backend.services.push")

ONESIGNAL_APP_ID = os.getenv("ONESIGNAL_APP_ID", "")
ONESIGNAL_REST_KEY = os.getenv("ONESIGNAL_REST_API_KEY", "")
_ONESIGNAL_URL = "https://onesignal.com/api/v1/notifications"


def _get_player_ids(user_id: str) -> list[str]:
    sb = get_supabase()
    resp = sb.table("DeviceTokens").select("device_token").eq("user_id", user_id).execute()
    return [r["device_token"] for r in (resp.data or []) if r.get("device_token")]


def _post_notification(player_ids: list[str], title: str, body: str, data: dict | None) -> int:
    """POST a single OneSignal notification to a list of player IDs. Returns recipient count on success."""
    payload: dict = {
        "app_id": ONESIGNAL_APP_ID,
        "include_player_ids": player_ids,
        "headings": {"en": title},
        "contents": {"en": body},
    }
    if data:
        payload["data"] = data
    resp = httpx.post(
        _ONESIGNAL_URL,
        json=payload,
        headers={"Authorization": f"Basic {ONESIGNAL_REST_KEY}", "Content-Type": "application/json"},
        timeout=10,
    )
    resp.raise_for_status()
    return len(player_ids)


def send_bulk_push(player_ids: list[str], title: str, body: str, data: dict | None = None) -> int:
    """Send a push notification to an explicit list of player IDs (max 2000 per OneSignal call).
    Returns total number of recipients notified.
    """
    if not ONESIGNAL_APP_ID or not ONESIGNAL_REST_KEY:
        logger.warning("OneSignal credentials not configured — skipping bulk push")
        return 0
    if not player_ids:
        return 0

    total = 0
    for i in range(0, len(player_ids), 2000):
        chunk = player_ids[i : i + 2000]
        try:
            total += _post_notification(chunk, title, body, data)
        except Exception:
            logger.exception("Bulk push failed for chunk starting at index %d", i)
    logger.info("Bulk push sent to %d recipients: %s", total, title)
    return total


def send_push(user_id: str, title: str, body: str, data: dict | None = None) -> bool:
    """Send a push notification to all registered devices for a user. Returns True on success."""
    if not ONESIGNAL_APP_ID or not ONESIGNAL_REST_KEY:
        logger.warning("OneSignal credentials not configured — skipping push for user_id=%s", user_id)
        return False

    player_ids = _get_player_ids(user_id)
    if not player_ids:
        logger.info("No device tokens for user_id=%s — skipping push", user_id)
        return False

    try:
        _post_notification(player_ids, title, body, data)
        logger.info("Push sent to user_id=%s (recipients=%d): %s", user_id, len(player_ids), title)
        return True
    except Exception:
        logger.exception("Failed to send push notification to user_id=%s", user_id)
        return False
