"""
One-off festive mindful-eating WhatsApp reminders.

Sends exactly one message to every active, WhatsApp-activated participant on
each of 3 pre-set festival dates (2026-11-07, 2026-12-24, 2027-01-14) -- one
day before the respective festival. The message content/campaign logic here
is deliberately standalone (not folded into the missed-slot feedback content
in services/whatsapp_feedback.py) -- but it's still invoked from
services/reminder_worker.py's existing always-on loop (see
_run_festive_reminder_tick there), since that's the only thing in this
codebase that actually fires reliably on a specific future calendar date
without depending on any particular chat/agent session staying alive.

The date -> message mapping below was randomized once (from the 9 messages
the user provided) and is fixed in code rather than re-randomized per run, so
each date always sends the same message and never repeats one of the other
two dates' messages -- no cross-run state file needed to track "already
sent" across just 3 known occasions. The other 6 of the 9 messages are
unused by design (only 3 dates to send on).

send_festive_reminder() is safe to call repeatedly on the same date (e.g. an
hourly worker tick): _already_sent_today() checks WH_Messages for this exact
message text logged in the last 20 hours before sending again, so only the
first matching tick each day actually sends.

Can also be run by hand for a one-off manual send:
    python3 scripts/send_festive_reminder.py              # sends for today
    python3 scripts/send_festive_reminder.py 2026-11-07    # sends for a specific date
"""
import logging
import sys
from datetime import date, datetime, timedelta, timezone

sys.path.insert(0, __file__.rsplit("/scripts/", 1)[0])

from core.supabase import get_supabase  # noqa: E402
from services.whatsapp_notify import send_whatsapp  # noqa: E402

logger = logging.getLogger("backend.scripts.send_festive_reminder")

TITLE = "Festive Reminder"

MESSAGES_BY_DATE: dict[str, str] = {
    "2026-11-07": "A festive feast ahead? Balance your plate with vegetables, protein and smaller portions of rice.",
    "2026-12-24": "Before reaching for a second sweet, pause—one small portion may be enough.",
    "2027-01-14": "It's festive time! Enjoy sweets in small portions to help manage your blood sugar.",
}


def _get_active_whatsapp_user_ids() -> list[str]:
    """Same active+activated filtering pattern as services/reminders.py's
    send_meal_reminders: WH_Users.activated_at not null, minus anyone
    explicitly marked inactive in UserRoles."""
    sb = get_supabase()
    wh_resp = sb.table("WH_Users").select("user_id").not_.is_("activated_at", "null").execute()
    user_ids = {r["user_id"] for r in (wh_resp.data or []) if r.get("user_id")}
    if not user_ids:
        return []

    active_resp = sb.table("UserRoles").select("user_id, is_active").in_("user_id", list(user_ids)).execute()
    inactive_ids = {r["user_id"] for r in (active_resp.data or []) if r.get("is_active") is False}
    return sorted(user_ids - inactive_ids)


def _already_sent_today(message: str) -> bool:
    """True if this exact message text (as send_whatsapp formats it) was
    already logged to WH_Messages within the last 20 hours -- lets
    send_festive_reminder() be called repeatedly on the same date (e.g. an
    hourly worker tick) without re-sending to everyone each time."""
    sb = get_supabase()
    formatted = f"*{TITLE}*\n{message}"
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=20)).isoformat()
    resp = (
        sb.table("WH_Messages")
        .select("id")
        .eq("message", formatted)
        .gte("created_at", cutoff)
        .limit(1)
        .execute()
    )
    return bool(resp.data)


def send_festive_reminder(target_date: str | None = None) -> dict:
    """Sends the configured festive reminder for `target_date` (default:
    today, IST-naive -- pass an explicit date if running outside IST) to
    every active WhatsApp-activated user. No-ops safely (sent=0) if
    target_date isn't one of the 3 configured dates, so this is harmless to
    run on any day without an external date check. Also no-ops if this
    date's message was already sent within the last 20 hours (see
    _already_sent_today), so repeated calls on the same date are safe."""
    d = target_date or date.today().isoformat()
    message = MESSAGES_BY_DATE.get(d)
    if not message:
        logger.info("No festive reminder configured for %s -- skipping", d)
        return {"date": d, "message": None, "sent": 0, "failed": 0}

    if _already_sent_today(message):
        logger.info("Festive reminder for %s already sent recently -- skipping", d)
        return {"date": d, "message": message, "sent": 0, "failed": 0, "already_sent": True}

    user_ids = _get_active_whatsapp_user_ids()
    sent, failed = 0, 0
    for uid in user_ids:
        try:
            if send_whatsapp(uid, TITLE, message):
                sent += 1
            else:
                failed += 1
        except Exception:
            logger.exception("Failed to send festive reminder to user_id=%s", uid)
            failed += 1

    logger.info(
        "Festive reminder for %s: sent=%d failed=%d (of %d candidates)",
        d, sent, failed, len(user_ids),
    )
    return {"date": d, "message": message, "sent": sent, "failed": failed}


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else None
    print(send_festive_reminder(target))
