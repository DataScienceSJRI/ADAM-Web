import json
import logging
from datetime import datetime, timedelta, timezone

from core.redis_client import get_redis_fast

logger = logging.getLogger("backend.services.plan_retry_sweep")

# Confirmed real on A002_NASIR: next_plan_at came and went over a week ago
# with no successful plan and no error status either -- the scheduled RQ job
# itself never ran (lost on a worker restart, or similar), so nothing was
# ever left to retry. A per-job "schedule a retry on failure" callback can't
# catch that case, since it depends on the ORIGINAL job surviving long enough
# to schedule its own retry. This sweep instead re-derives "needs attention"
# purely from BE_Onboarding_Sessions' stored plan_status/next_plan_at on each
# tick, independent of whether any particular RQ job is still alive.
_RETRY_MAX_ATTEMPTS = 3
_RETRY_COOLDOWN = timedelta(hours=1)
_RETRY_KEY_TTL_SECONDS = 7 * 24 * 3600  # bookkeeping auto-expires so it never leaks forever
_RETRY_REDIS_PREFIX = "plan_auto_retry:"


def _is_failed_status(status: str | None) -> bool:
    if not status:
        return False
    # Mirrors frontend/.../meal-plans-client.tsx's isFailedStatus: "No
    # solution" is the old generic fallback message, "No feasible" is
    # services/lp_optimizer.py's actual Infeasible message.
    return bool(status.startswith("error") or "No solution" in status or "No feasible" in status)


def _retry_key(onboarding_id: str) -> str:
    return f"{_RETRY_REDIS_PREFIX}{onboarding_id}"


def reset_auto_retry(onboarding_id: str | None) -> None:
    """Call this right after a plan generation succeeds, so a past failure
    streak doesn't count against a later, unrelated failure for the same
    onboarding session."""
    if not onboarding_id:
        return
    try:
        get_redis_fast().delete(_retry_key(onboarding_id))
    except Exception:
        logger.exception("Could not reset auto-retry bookkeeping for onboarding_id=%s", onboarding_id)


def _trigger_retry(user_id: str, onboarding_id: str) -> None:
    from models.schemas import GeneratePlanRequest
    from routers.plan import generate_plan

    body = GeneratePlanRequest(onboarding_id=onboarding_id, target_user_id=user_id)
    generate_plan(body=body, user_id=user_id)


def sweep_failed_plans() -> int:
    """Periodic safety net (called from reminder_worker.py's poll loop):
    finds onboarding sessions whose last plan generation attempt failed (or
    whose scheduled next attempt never actually ran) and retries them
    automatically -- up to _RETRY_MAX_ATTEMPTS, no sooner than
    _RETRY_COOLDOWN apart per onboarding session. Returns how many retries
    were triggered this tick."""
    from core.supabase import get_supabase, fetch_all_rows

    sb = get_supabase()
    redis = get_redis_fast()
    now = datetime.now(timezone.utc)

    # Scoped to real pilot participants (participant_id starting "A", same
    # convention routers/users.py and the dashboard already use to separate
    # them from P-prefixed/test accounts) and currently-active ones only.
    # Dozens of old P-accounts are sitting in a failed state with no
    # next_plan_at at all (abandoned test runs, not anything actually
    # waiting on a fix) -- auto-retrying all of those on the very first tick
    # would queue a thundering herd of ~10-20min CBC solves and could delay
    # real participants' own scheduled/retried jobs behind them.
    active_real_participants = fetch_all_rows(lambda: (
        sb.table("UserRoles").select("user_id")
        .eq("role", "participant").eq("is_active", True).ilike("participant_id", "A%")
    ))
    eligible_user_ids = {r["user_id"] for r in active_real_participants if r.get("user_id")}
    if not eligible_user_ids:
        return 0

    sessions = fetch_all_rows(lambda: (
        sb.table("BE_Onboarding_Sessions")
        .select("onboarding_id,user_id,plan_status,next_plan_at,updated_at")
        .in_("user_id", list(eligible_user_ids))
    ))
    # A user_id should only ever have one onboarding_id in practice (same
    # assumption routers/users.py's session_map already makes) -- keep the
    # most recently updated row per user just in case more than one exists.
    by_user: dict[str, dict] = {}
    for s in sessions:
        uid = s.get("user_id")
        if not uid:
            continue
        existing = by_user.get(uid)
        if existing is None or (s.get("updated_at") or "") > (existing.get("updated_at") or ""):
            by_user[uid] = s

    triggered = 0
    for uid, s in by_user.items():
        status = s.get("plan_status")
        onboarding_id = s.get("onboarding_id")
        if not onboarding_id or not _is_failed_status(status):
            continue

        next_plan_at = s.get("next_plan_at")
        if next_plan_at:
            try:
                if datetime.fromisoformat(next_plan_at) > now:
                    continue  # a real success happened more recently than this error -- not actually stuck
            except ValueError:
                pass

        key = _retry_key(onboarding_id)
        try:
            raw = redis.get(key)
        except Exception:
            logger.exception("Redis unavailable for auto-retry sweep -- skipping onboarding_id=%s", onboarding_id)
            continue
        state = json.loads(raw) if raw else {"count": 0, "last_attempt": None}

        if state["count"] >= _RETRY_MAX_ATTEMPTS:
            continue  # exhausted -- leave for a human to retry manually

        if state["last_attempt"]:
            last = datetime.fromisoformat(state["last_attempt"])
            if now - last < _RETRY_COOLDOWN:
                continue  # too soon since the last attempt

        state["count"] += 1
        state["last_attempt"] = now.isoformat()
        try:
            redis.set(key, json.dumps(state), ex=_RETRY_KEY_TTL_SECONDS)
        except Exception:
            logger.exception("Could not persist auto-retry bookkeeping for onboarding_id=%s", onboarding_id)
            continue

        logger.warning(
            "Auto-retrying failed plan for user_id=%s onboarding_id=%s (attempt %d/%d, last status=%r)",
            uid, onboarding_id, state["count"], _RETRY_MAX_ATTEMPTS, status,
        )
        try:
            _trigger_retry(uid, onboarding_id)
            triggered += 1
        except Exception:
            logger.exception("Auto-retry trigger failed for user_id=%s onboarding_id=%s", uid, onboarding_id)

    return triggered
