import argparse
import logging
import multiprocessing
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


def _run_worker() -> None:
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


def main() -> None:
    parser = argparse.ArgumentParser(description="ADAM plan worker")
    parser.add_argument(
        "--workers",
        type=int,
        default=int(os.getenv("PLAN_WORKER_COUNT", "1")),
        help="Number of parallel worker processes (default: 1, or PLAN_WORKER_COUNT env var)",
    )
    args = parser.parse_args()

    logging.basicConfig(
        format="[%(asctime)s] %(levelname)s %(name)s: %(message)s",
        level=os.getenv("LOG_LEVEL", "INFO"),
    )

    if args.workers <= 1:
        logger.info("Starting 1 plan worker")
        _run_worker()
    else:
        logger.info("Starting %d plan workers", args.workers)
        processes: list[multiprocessing.Process] = []
        for i in range(args.workers):
            p = multiprocessing.Process(target=_run_worker, name=f"plan-worker-{i + 1}", daemon=True)
            p.start()
            logger.info("Started worker process %d (pid=%d)", i + 1, p.pid)
            processes.append(p)
        try:
            for p in processes:
                p.join()
        except KeyboardInterrupt:
            logger.info("Shutting down workers…")
            for p in processes:
                p.terminate()
            for p in processes:
                p.join()


if __name__ == "__main__":
    main()
