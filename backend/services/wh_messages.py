import logging
from datetime import datetime, timezone

from core.supabase import get_supabase

logger = logging.getLogger("backend.services.wh_messages")


def log_pending(user_id: str, message: str) -> int | None:
    """Insert a 'pending' WH_Messages row for an outbound WhatsApp send.
    Returns the new row id, or None if the insert itself failed (send should
    still proceed — this log is best-effort)."""
    try:
        resp = (
            get_supabase()
            .table("WH_Messages")
            .insert({"user_id": user_id, "message": message, "status": "pending"})
            .execute()
        )
        return resp.data[0]["id"] if resp.data else None
    except Exception:
        logger.exception("Failed to log pending WH_Messages row for user_id=%s", user_id)
        return None


def mark_sent(message_id: int | None) -> None:
    if message_id is None:
        return
    try:
        get_supabase().table("WH_Messages").update(
            {"status": "sent", "sent_at": datetime.now(timezone.utc).isoformat()}
        ).eq("id", message_id).execute()
    except Exception:
        logger.exception("Failed to mark WH_Messages id=%s as sent", message_id)


def mark_error(message_id: int | None, error: str) -> None:
    if message_id is None:
        return
    try:
        get_supabase().table("WH_Messages").update(
            {"status": "error", "error": error[:2000]}
        ).eq("id", message_id).execute()
    except Exception:
        logger.exception("Failed to mark WH_Messages id=%s as error", message_id)
