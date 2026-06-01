import logging
import os

from rq import Queue, Worker

from core.redis_client import (
    PLAN_JOB_TIMEOUT_SECONDS,
    PLAN_QUEUE_NAME,
    get_redis,
)
from models.schemas import GeneratePlanRequest

logger = logging.getLogger("backend.services.plan_worker")


def run_plan_job(user_id: str, body: dict, profile: dict) -> None:
    from routers.plan import _run_plan_background

    request = GeneratePlanRequest(**body)
    logger.info(
        "Starting plan job for user_id=%s onboarding_id=%s",
        user_id,
        request.onboarding_id,
    )
    _run_plan_background(user_id=user_id, body=request, profile=profile)


def main() -> None:
    logging.basicConfig(
        format="[%(asctime)s] %(levelname)s %(name)s: %(message)s",
        level=os.getenv("LOG_LEVEL", "INFO"),
    )
    redis = get_redis()
    queue = Queue(
        PLAN_QUEUE_NAME,
        connection=redis,
        default_timeout=PLAN_JOB_TIMEOUT_SECONDS,
    )
    worker = Worker([queue], connection=redis)
    worker.work(with_scheduler=True)


if __name__ == "__main__":
    main()
