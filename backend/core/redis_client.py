import os
import logging
from redis import Redis

logger = logging.getLogger("backend.core.redis_client")

_redis: Redis | None = None
PLAN_QUEUE_NAME = os.getenv("PLAN_QUEUE_NAME", "meal-plans")
PLAN_JOB_TIMEOUT_SECONDS = int(os.getenv("PLAN_JOB_TIMEOUT_SECONDS", "1200"))


def get_redis() -> Redis:
    global _redis
    try:
        if _redis is None:
            _redis = Redis.from_url(
                os.getenv("REDIS_URL", "redis://localhost:6379/1"),
                decode_responses=False,
                socket_connect_timeout=5,
            )
        _redis.ping()
    except Exception as e:
        logger.error("Redis connection failed: %s", e)
        raise
    return _redis
