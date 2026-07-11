import argparse
import logging
import multiprocessing
import os
from datetime import date

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


def run_auto_next_week_job(user_id: str, onboarding_id: str, week_no: int, start_date_iso: str) -> None:
    """
    Fired at 9pm IST on day 6 of the previous week's plan (scheduled by _schedule_next_week_job in
    routers/plan.py). Notifies the user that generation has started, then runs
    the same plan pipeline used for manual generation, anchored to start_date
    so this week continues immediately after the previous one.
    """
    from routers.plan import _run_plan_background
    from services.profile_builder import build_profile
    from services.push import send_push

    logger.info(
        "Auto-generating week %d plan for user_id=%s onboarding_id=%s",
        week_no, user_id, onboarding_id,
    )

    send_push(
        user_id=user_id,
        title="Next week's plan is on its way",
        body="We're generating your meal plan for next week. You'll get a notification when it's ready.",
        data={"type": "plan_auto_generating", "week_no": week_no},
    )

    profile = build_profile(user_id, onboarding_id=onboarding_id)
    if profile is None:
        logger.warning(
            "Auto plan generation skipped: no profile found for user_id=%s onboarding_id=%s",
            user_id, onboarding_id,
        )
        return

    request = GeneratePlanRequest(week_no=week_no, onboarding_id=onboarding_id)
    _run_plan_background(
        user_id=user_id,
        body=request,
        profile=profile,
        start_date=date.fromisoformat(start_date_iso),
    )


def run_day4_checkin_job(user_id: str) -> None:
    """
    Fired at 9am IST on day 4 of a plan. Nudges the user to log their weight and review/update
    their meal preferences.
    """
    from services.push import send_push

    logger.info("Sending day-4 check-in reminder for user_id=%s", user_id)
    send_push(
        user_id=user_id,
        title="Time to check in",
        body="Log your weight and update your meal preferences if anything's changed.",
        data={"type": "day4_checkin"},
    )


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
            p = multiprocessing.Process(target=_run_worker, name=f"plan-worker-{i + 1}")
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
