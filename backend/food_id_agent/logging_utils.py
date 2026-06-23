import logging
import uuid
from contextlib import contextmanager
from pathlib import Path

LOG_DIR = Path("logs")

logger = logging.getLogger("food_id_agent")
logger.setLevel(logging.DEBUG)


def new_run_id() -> str:
    return uuid.uuid4().hex[:12]


@contextmanager
def run_log_file(run_id: str):
    """Attach a per-run FileHandler to the food_id_agent logger for the
    duration of one pipeline run, writing to logs/<run_id>.log. Removed again
    on exit so concurrent runs don't write into each other's file.
    """
    LOG_DIR.mkdir(exist_ok=True)
    path = LOG_DIR / f"{run_id}.log"
    handler = logging.FileHandler(path, encoding="utf-8")
    handler.setLevel(logging.DEBUG)
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s")
    )
    logger.addHandler(handler)
    try:
        yield path
    finally:
        logger.removeHandler(handler)
        handler.close()
