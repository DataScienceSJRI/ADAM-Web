import logging

from services.push import send_push
from services.whatsapp_notify import send_whatsapp

logger = logging.getLogger("backend.services.notify")


def notify(user_id: str, title: str, body: str, data: dict | None = None) -> bool:
    push_ok = False
    try:
        push_ok = send_push(user_id=user_id, title=title, body=body, data=data)
    except Exception:
        logger.warning("Push channel failed for user_id=%s", user_id, exc_info=True)

    whatsapp_ok = False
    try:
        whatsapp_ok = send_whatsapp(user_id=user_id, title=title, body=body)
    except Exception:
        logger.warning("WhatsApp channel failed for user_id=%s", user_id, exc_info=True)

    return push_ok or whatsapp_ok
