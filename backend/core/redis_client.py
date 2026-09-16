import os
import logging
from redis import Redis

logger = logging.getLogger("backend.core.redis_client")

_redis: Redis | None = None
_redis_fast: Redis | None = None

PLAN_QUEUE_NAME = os.getenv("PLAN_QUEUE_NAME", "meal-plans")
PLAN_JOB_TIMEOUT_SECONDS = int(os.getenv("PLAN_JOB_TIMEOUT_SECONDS", "3600"))

FOOD_ID_QUEUE_NAME = os.getenv("FOOD_ID_QUEUE_NAME", "food-id")
FOOD_ID_JOB_TIMEOUT_SECONDS = int(os.getenv("FOOD_ID_JOB_TIMEOUT_SECONDS", "3600"))  # 1 hour

# Bounds a request-path Redis command's read/write, not just its initial
# connect. Kept well under typical HTTP client/proxy timeouts so a stuck
# Redis fails the request fast instead of holding a uvicorn worker slot open
# for minutes (see the Sept 2026 incident: HELLO/RESP negotiation trouble
# against an old Redis build left FastAPI requests stuck open 45s-2min).
REDIS_FAST_SOCKET_TIMEOUT_SECONDS = float(os.getenv("REDIS_FAST_SOCKET_TIMEOUT_SECONDS", "5"))


def _make_client(**overrides) -> Redis:
    return Redis.from_url(
        os.getenv("REDIS_URL", "redis://localhost:6379/1"),
        decode_responses=False,
        socket_connect_timeout=5,
        # Force RESP2 explicitly -- avoids the client sending a HELLO
        # handshake, which the Redis 4.0.9 instance on the shared host
        # doesn't understand ("unknown command 'HELLO'").
        protocol=2,
        **overrides,
    )


def get_redis() -> Redis:
    """Long-lived client for RQ workers. Deliberately has NO socket_timeout:
    a worker's BLPOP wait for the next job can legitimately block for its
    whole poll interval, and a short read timeout would misfire mid-wait and
    look like a dead Redis every few seconds."""
    global _redis
    try:
        if _redis is None:
            _redis = _make_client()
        _redis.ping()
    except Exception as e:
        logger.error("Redis connection failed: %s", e)
        # Drop the broken client so the next call rebuilds the connection
        # instead of retrying the same wedged socket forever.
        _redis = None
        raise
    return _redis


def get_redis_fast() -> Redis:
    """Short-timeout client for request-path Redis calls (enqueueing/
    cancelling jobs from a FastAPI handler). These are quick, non-blocking
    commands, so a bad Redis connection should fail within
    REDIS_FAST_SOCKET_TIMEOUT_SECONDS rather than hanging the HTTP request."""
    global _redis_fast
    try:
        if _redis_fast is None:
            _redis_fast = _make_client(socket_timeout=REDIS_FAST_SOCKET_TIMEOUT_SECONDS)
        _redis_fast.ping()
    except Exception as e:
        logger.error("Redis connection failed: %s", e)
        _redis_fast = None
        raise
    return _redis_fast
