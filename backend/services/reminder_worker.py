import logging
import os
import time

from services.reminders import send_meal_reminders

logger = logging.getLogger("backend.services.reminder_worker")

_INTERVAL_MINUTES = int(os.getenv("MEAL_REMINDER_INTERVAL_MINUTES", "15"))
_WINDOW_MINUTES = int(os.getenv("MEAL_REMINDER_WINDOW_MINUTES", "7"))


def main() -> None:
    """
    Standalone meal-reminder loop. Runs independently of the RQ plan queue/worker
    on purpose: plan generation can now take up to 10 minutes, and sharing a queue
    would risk delaying a reminder past its meal-time window while workers are busy
    on plan jobs. Run this as its own process (screen session today, systemd
    service later) alongside — not inside — the plan worker.
    """
    logging.basicConfig(
        format="[%(asctime)s] %(levelname)s %(name)s: %(message)s",
        level=os.getenv("LOG_LEVEL", "INFO"),
    )
    logger.info(
        "Starting meal-reminder service (every %d min, ±%d min window)",
        _INTERVAL_MINUTES, _WINDOW_MINUTES,
    )
    while True:
        try:
            results = send_meal_reminders(window_minutes=_WINDOW_MINUTES)
            if results:
                logger.info("Meal reminders sent: %s", results)
        except Exception:
            logger.exception("Meal reminders tick failed")
        time.sleep(_INTERVAL_MINUTES * 60)


if __name__ == "__main__":
    main()
