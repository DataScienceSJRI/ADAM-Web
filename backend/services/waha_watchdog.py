import logging
import os
import time

import httpx
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("backend.services.waha_watchdog")

_BASE_URL = os.getenv("WAHA_BASE_URL", "").rstrip("/")
_API_KEY = os.getenv("WAHA_API_KEY", "")
_SESSION = os.getenv("WAHA_SESSION", "default")
_RESTART_WAIT_SECONDS = int(os.getenv("WAHA_WATCHDOG_RESTART_WAIT_SECONDS", "15"))

_UNHEALTHY_STATUSES = {"STOPPED", "FAILED"}
_NEEDS_MANUAL_STATUSES = {"SCAN_QR_CODE"}


def _get_session_status() -> dict:
    resp = httpx.get(
        f"{_BASE_URL}/api/sessions/{_SESSION}",
        headers={"X-Api-Key": _API_KEY},
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


def _stop_session() -> None:
    httpx.post(
        f"{_BASE_URL}/api/sessions/{_SESSION}/stop",
        headers={"X-Api-Key": _API_KEY},
        timeout=15,
    ).raise_for_status()


def _start_session() -> None:
    httpx.post(
        f"{_BASE_URL}/api/sessions/{_SESSION}/start",
        headers={"X-Api-Key": _API_KEY},
        timeout=15,
    ).raise_for_status()


def main() -> None:
    logging.basicConfig(
        format="[%(asctime)s] %(levelname)s %(name)s: %(message)s",
        level=os.getenv("LOG_LEVEL", "INFO"),
    )

    if not _BASE_URL:
        logger.error("WAHA_BASE_URL not configured -- skipping check")
        return

    try:
        before = _get_session_status()
    except httpx.HTTPError as exc:
        logger.error("Could not reach WAHA at %s: %s", _BASE_URL, exc)
        return

    status = before.get("status")

    if status == "WORKING":
        logger.info("WAHA session %s healthy (WORKING)", _SESSION)
        return

    if status not in _UNHEALTHY_STATUSES:
        # STARTING, or any status we don't recognize yet -- log and leave it alone
        # rather than guess.
        logger.info("WAHA session %s status=%s -- not auto-recovering this tick", _SESSION, status)
        return

    logger.warning(
        "WAHA session %s unhealthy: status=%s me=%s -- attempting stop/start recovery",
        _SESSION, status, before.get("me"),
    )

    try:
        _stop_session()
        _start_session()
    except httpx.HTTPError as exc:
        logger.error("WAHA session %s restart request failed: %s", _SESSION, exc)
        return

    time.sleep(_RESTART_WAIT_SECONDS)

    try:
        after = _get_session_status()
    except httpx.HTTPError as exc:
        logger.error("WAHA session %s status re-check failed after restart: %s", _SESSION, exc)
        return

    after_status = after.get("status")
    if after_status == "WORKING":
        logger.info("WAHA session %s recovered automatically: %s -> WORKING", _SESSION, status)
    elif after_status in _NEEDS_MANUAL_STATUSES:
        logger.error(
            "WAHA session %s needs manual intervention: %s -> %s (me=%s) -- "
            "requires re-scanning the QR code, auto-restart cannot fix this",
            _SESSION, status, after_status, after.get("me"),
        )
    else:
        logger.error(
            "WAHA session %s still unhealthy after auto-restart: %s -> %s (me=%s)",
            _SESSION, status, after_status, after.get("me"),
        )


if __name__ == "__main__":
    main()
