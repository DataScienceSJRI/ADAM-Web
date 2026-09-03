import logging

from core.supabase import get_supabase
from services.whatsapp_gateway import get_gateway

logger = logging.getLogger("backend.services.whatsapp_notify")


def _get_activated_phone(user_id: str) -> str | None:
    sb = get_supabase()
    resp = (
        sb.table("WH_Users")
        .select("phone")
        .eq("user_id", user_id)
        .not_.is_("activated_at", "null")
        .limit(1)
        .execute()
    )
    if not resp.data:
        return None
    return resp.data[0].get("phone")


def send_whatsapp(user_id: str, title: str, body: str) -> bool:
    """Send a WhatsApp text to a user's linked+activated number. Returns True on success,
    False (silently — no linked number is the common case) if there's nothing to send to."""
    phone = _get_activated_phone(user_id)
    if not phone:
        return False

    try:
        get_gateway().send_text(phone, f"*{title}*\n{body}")
        logger.info("WhatsApp sent to user_id=%s: %s", user_id, title)
        return True
    except Exception:
        logger.exception("Failed to send WhatsApp message to user_id=%s", user_id)
        return False
