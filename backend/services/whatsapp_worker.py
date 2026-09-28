import logging
import os
import time

from services.whatsapp_feedback import check_missed_slots, send_next_day_previews

logger = logging.getLogger("backend.services.whatsapp_worker")

_INTERVAL_MINUTES = int(os.getenv("WHATSAPP_WORKER_INTERVAL_MINUTES", "15"))


def _tick() -> None:
    counts = check_missed_slots()
    if counts:
        logger.info("Missed-slot messages sent: %s", counts)

    # send_next_day_previews() gates itself on _NEXT_DAY_PREVIEW_TIME (7 PM
    # IST) and is idempotent per user/date, so calling it every tick is safe
    # -- it's a no-op until 7 PM, and a no-op again for the rest of the day
    # once it has sent.
    inserted_ids = send_next_day_previews()
    if inserted_ids:
        logger.info("Next-day meal previews sent: %d", len(inserted_ids))


def main() -> None:
    """
    Handles both:
      - missed-slot nudges (every tick, idempotent, safe on any cadence)
      - next-day meal previews (only actually sends once per user per day,
        after 7 PM IST -- see send_next_day_previews()'s own time gate + dedup)
    """
    logging.basicConfig(
        format="[%(asctime)s] %(levelname)s %(name)s: %(message)s",
        level=os.getenv("LOG_LEVEL", "INFO"),
    )
    logger.info(
        "Starting WhatsApp jobs service (missed-slot + next-day preview, every %d min)",
        _INTERVAL_MINUTES,
    )
    while True:
        try:
            _tick()
        except Exception:
            logger.exception("WhatsApp jobs tick failed")
        time.sleep(_INTERVAL_MINUTES * 60)


if __name__ == "__main__":
    main()
