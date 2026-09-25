import logging
import os
import time

from services.reminders import send_meal_reminders
from services.whatsapp_feedback import send_pending_meal_feedback

logger = logging.getLogger("backend.services.reminder_worker")

_INTERVAL_MINUTES = int(os.getenv("MEAL_REMINDER_INTERVAL_MINUTES", "15"))
_WINDOW_MINUTES = int(os.getenv("MEAL_REMINDER_WINDOW_MINUTES", "7"))
_FEEDBACK_POLL_SECONDS = int(os.getenv("MEAL_FEEDBACK_POLL_SECONDS", "60"))


def main() -> None:
    """
    Standalone meal-reminder loop. Runs independently of the RQ plan queue/worker
    on purpose: plan generation can now take up to 10 minutes, and sharing a queue
    would risk delaying a reminder past its meal-time window while workers are busy
    on plan jobs. Run this as its own process (screen session today, systemd
    service later) alongside — not inside — the plan worker.

    Also runs send_pending_meal_feedback() on a much shorter tick
    (_FEEDBACK_POLL_SECONDS, default 60s) than the meal-reminder check: that
    function is what actually sends the debounced, consolidated WhatsApp
    feedback message for a just-logged meal once services.whatsapp_feedback's
    _FEEDBACK_DEBOUNCE_MINUTES quiet period has elapsed, and a 15-minute tick
    would make every meal wait up to 15 extra minutes on top of the debounce
    window itself for no reason.
    """
    logging.basicConfig(
        format="[%(asctime)s] %(levelname)s %(name)s: %(message)s",
        level=os.getenv("LOG_LEVEL", "INFO"),
    )
    logger.info(
        "Starting meal-reminder service (every %d min, ±%d min window; "
        "pending-feedback poll every %ds)",
        _INTERVAL_MINUTES, _WINDOW_MINUTES, _FEEDBACK_POLL_SECONDS,
    )
    next_reminder_check = 0.0
    while True:
        now = time.monotonic()
        if now >= next_reminder_check:
            try:
                results = send_meal_reminders(window_minutes=_WINDOW_MINUTES)
                if results:
                    logger.info("Meal reminders sent: %s", results)
            except Exception:
                logger.exception("Meal reminders tick failed")
            next_reminder_check = now + _INTERVAL_MINUTES * 60

        try:
            sent = send_pending_meal_feedback()
            if sent:
                logger.info("Pending meal feedback sent: %d message(s)", sent)
        except Exception:
            logger.exception("Pending meal feedback tick failed")

        time.sleep(_FEEDBACK_POLL_SECONDS)


if __name__ == "__main__":
    main()
