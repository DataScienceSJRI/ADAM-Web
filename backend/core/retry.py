import logging
import time
from typing import Callable, TypeVar

import httpx
from jwt.exceptions import PyJWKClientConnectionError

logger = logging.getLogger("backend.retry")

T = TypeVar("T")

# ssl.SSLError (incl. SSLEOFError) and socket errors are OSError subclasses;
# httpx.TransportError covers ConnectError/ReadError/PoolTimeout/etc. for the
# httpx-based Supabase client; PyJWKClientConnectionError is PyJWT's own
# wrapper around a failed JWKS fetch (it does not subclass OSError, so it
# needs listing explicitly). All three are transient — the operation itself
# is valid, the connection just dropped or timed out mid-flight.
_TRANSIENT_EXCEPTIONS = (OSError, TimeoutError, httpx.TransportError, PyJWKClientConnectionError)


def call_with_retry(fn: Callable[[], T], *, retries: int = 3, base_delay: float = 1.0, what: str = "operation") -> T:
    """Call fn(), retrying on transient network/SSL errors with exponential backoff
    (base_delay, base_delay*2, ...). Re-raises the last exception once retries
    are exhausted, so callers keep their existing error handling for the final
    failure — this only absorbs single blips, not persistent outages."""
    last_exc: Exception = RuntimeError(f"{what}: no attempts made")
    for attempt in range(1, retries + 1):
        try:
            return fn()
        except _TRANSIENT_EXCEPTIONS as exc:
            last_exc = exc
            if attempt < retries:
                delay = base_delay * (2 ** (attempt - 1))
                logger.warning(
                    "Transient error on %s (attempt %d/%d): %s — retrying in %.1fs",
                    what, attempt, retries, exc, delay,
                )
                time.sleep(delay)
            else:
                logger.warning(
                    "Transient error on %s (attempt %d/%d): %s — giving up",
                    what, attempt, retries, exc,
                )
    raise last_exc
