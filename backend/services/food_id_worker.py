import logging
import os

logger = logging.getLogger("backend.services.food_id_worker")

PROCESSING_SENTINEL = "__processing__"
FAILED_SENTINEL = "__failed__"


def run_food_id_job(review_id: str, image_url: str, vlm_backend: str = "ollama") -> None:
    """RQ job: run the food-ID pipeline and write result back to MealImageReview."""
    import json
    from pathlib import Path

    from dotenv import load_dotenv
    env_path = Path(__file__).parent.parent / ".env"
    if env_path.exists():
        load_dotenv(env_path, override=False)  

    from core.supabase import get_supabase
    from services.food_id import identify_image_from_url_sync

    logger.info("Food ID job starting: review_id=%s backend=%s", review_id, vlm_backend)
    sb = get_supabase()
    try:
        result = identify_image_from_url_sync(image_url, vlm_backend=vlm_backend)
        sb.table("MealImageReview").update(
            {"tracked_foods_by_ai": json.dumps(result)}
        ).eq("id", review_id).execute()
        logger.info("Food ID job done: review_id=%s", review_id)
    except Exception:
        logger.exception("Food ID job failed: review_id=%s", review_id)
        sb.table("MealImageReview").update(
            {"tracked_foods_by_ai": FAILED_SENTINEL}
        ).eq("id", review_id).execute()


def enqueue_food_id_job(
    review_id: str,
    image_url: str,
    vlm_backend: str | None = None,
) -> str:
    """Enqueue a food-ID job and return the RQ job ID."""
    from rq import Queue
    from core.redis_client import FOOD_ID_JOB_TIMEOUT_SECONDS, FOOD_ID_QUEUE_NAME, get_redis

    backend = vlm_backend or os.environ.get("VLM_BACKEND", "ollama")
    redis = get_redis()
    queue = Queue(FOOD_ID_QUEUE_NAME, connection=redis, default_timeout=FOOD_ID_JOB_TIMEOUT_SECONDS)
    job = queue.enqueue(run_food_id_job, review_id, image_url, backend)
    logger.info(
        "Enqueued food ID job %s: review_id=%s backend=%s", job.id, review_id, backend
    )
    return job.id


def run_food_id_job_post(review_id: str, image_url: str, vlm_backend: str = "ollama") -> None:
    """RQ job: run the food-ID pipeline on the post-meal image and write result
    back to MealImageReview.tracked_foods_by_ai_post. Independent of the pre-image
    job — a failure or delay here never touches tracked_foods_by_ai."""
    import json
    from pathlib import Path

    from dotenv import load_dotenv
    env_path = Path(__file__).parent.parent / ".env"
    if env_path.exists():
        load_dotenv(env_path, override=False)

    from core.supabase import get_supabase
    from services.food_id import identify_image_from_url_sync

    logger.info("Food ID job (post) starting: review_id=%s backend=%s", review_id, vlm_backend)
    sb = get_supabase()
    try:
        result = identify_image_from_url_sync(image_url, vlm_backend=vlm_backend)
        sb.table("MealImageReview").update(
            {"tracked_foods_by_ai_post": json.dumps(result)}
        ).eq("id", review_id).execute()
        logger.info("Food ID job (post) done: review_id=%s", review_id)
    except Exception:
        logger.exception("Food ID job (post) failed: review_id=%s", review_id)
        sb.table("MealImageReview").update(
            {"tracked_foods_by_ai_post": FAILED_SENTINEL}
        ).eq("id", review_id).execute()


def enqueue_food_id_job_post(
    review_id: str,
    image_url: str,
    vlm_backend: str | None = None,
) -> str:
    """Enqueue a food-ID job for the post-meal image and return the RQ job ID."""
    from rq import Queue
    from core.redis_client import FOOD_ID_JOB_TIMEOUT_SECONDS, FOOD_ID_QUEUE_NAME, get_redis

    backend = vlm_backend or os.environ.get("VLM_BACKEND", "ollama")
    redis = get_redis()
    queue = Queue(FOOD_ID_QUEUE_NAME, connection=redis, default_timeout=FOOD_ID_JOB_TIMEOUT_SECONDS)
    job = queue.enqueue(run_food_id_job_post, review_id, image_url, backend)
    logger.info(
        "Enqueued food ID job (post) %s: review_id=%s backend=%s", job.id, review_id, backend
    )
    return job.id


def _run_worker() -> None:
    logging.basicConfig(
        format="[%(asctime)s] %(levelname)s %(name)s: %(message)s",
        level=os.getenv("LOG_LEVEL", "INFO"),
    )
    from rq import Queue, Worker
    from core.redis_client import FOOD_ID_JOB_TIMEOUT_SECONDS, FOOD_ID_QUEUE_NAME, get_redis

    redis = get_redis()
    queue = Queue(FOOD_ID_QUEUE_NAME, connection=redis, default_timeout=FOOD_ID_JOB_TIMEOUT_SECONDS)
    worker = Worker([queue], connection=redis)
    logger.info("Food ID worker started on queue '%s'", FOOD_ID_QUEUE_NAME)
    worker.work(with_scheduler=False)


if __name__ == "__main__":
    _run_worker()
