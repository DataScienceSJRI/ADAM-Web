from supabase import create_client, Client
import os
import threading
import time
from dotenv import load_dotenv

load_dotenv()

_SUPABASE_URL = os.environ["SUPABASE_URL"]
_SUPABASE_KEY = os.environ["SUPABASE_SERVICE_KEY"]

# get_supabase() used to create a brand-new client (and a brand-new TLS
# connection) on EVERY call. With ~90 call sites across the backend plus
# several always-on RQ workers, that meant a fresh connection opened per
# query instead of the normal HTTP/2 pattern of multiplexing many requests
# over one, which was pushing the Supabase project into "Unhealthy" in the
# dashboard under load. It's now a process-wide singleton, rebuilt every
# _CLIENT_TTL_SECONDS so any one connection is never pooled for more than
# that long -- the fresh-per-call behaviour was originally added to dodge a
# stale-HTTP/2-connection error from a long-lived (multi-day) client, and
# this bounds that same exposure instead of removing pooling altogether.
_CLIENT_TTL_SECONDS = 600

_client_lock = threading.Lock()
_client: Client | None = None
_client_created_at: float = 0.0


def _new_client() -> Client:
    return create_client(_SUPABASE_URL, _SUPABASE_KEY)


def _close_client(client: Client) -> None:
    """Best-effort close of each sub-client's underlying HTTP session.
    Only called on TTL rotation (every few minutes), never on the hot path."""
    for closer in (
        lambda: client.postgrest.aclose(),
        lambda: client.auth.close(),
        lambda: client.storage.aclose(),
    ):
        try:
            closer()
        except Exception:
            pass


def get_supabase() -> Client:
    """Shared, process-wide Supabase client using the service-role key.

    Do NOT call `.auth.sign_in_with_password` / `.sign_up` / `.set_session`
    on the client this returns. Those mutate the client's Authorization
    header in place (SyncClient._listen_to_auth_events in the `supabase`
    package swaps it from the service-role key to the signed-in user's JWT),
    which would leak one user's session into every other concurrent request
    sharing this client. Use get_isolated_supabase() for any flow that signs
    in as an end user -- see routers/auth.py.
    """
    global _client, _client_created_at
    now = time.monotonic()
    if _client is not None and (now - _client_created_at) < _CLIENT_TTL_SECONDS:
        return _client
    with _client_lock:
        now = time.monotonic()
        if _client is None or (now - _client_created_at) >= _CLIENT_TTL_SECONDS:
            stale = _client
            _client = _new_client()
            _client_created_at = now
            if stale is not None:
                _close_client(stale)
        return _client


def get_isolated_supabase() -> Client:
    """A brand-new, not-shared Supabase client. Use this instead of
    get_supabase() for any flow that calls .auth.sign_in_with_password,
    .sign_up, or .set_session -- those mutate the client's own Authorization
    header, which must never bleed into the shared pooled client above."""
    return _new_client()


# Supabase/PostgREST caps every response at 1000 rows server-side, regardless
# of a client-side .limit(N) for N > 1000 -- confirmed directly in this
# project: with just 6 study participants, one query already had 1149
# matching rows, and a .limit(20000) call was silently returning only the
# first 1000 (in whatever default row order Postgres picks, not date-
# ordered), dropping the newest participant's rows entirely with no error.
# At full study scale (60 subjects) this affects every query fetching more
# than one participant's data across any real time window, not just the one
# that first exposed it. fetch_all_rows() pages with .range() instead of
# ever trusting a single large .limit() to return more than one page.
MAX_PAGE_SIZE = 1000


def fetch_all_rows(build_query) -> list[dict]:
    """Pages through a Supabase query via .range() so results are never
    silently truncated at the 1000-row response cap.

    `build_query` must be a zero-arg callable that returns a FRESH,
    not-yet-executed query builder with every filter (and .order(), if used)
    already applied except .range() -- a supabase-py builder can't be
    re-executed after .execute(), so each page needs its own freshly-built
    one rather than reusing one across iterations."""
    rows: list[dict] = []
    offset = 0
    while True:
        page = build_query().range(offset, offset + MAX_PAGE_SIZE - 1).execute().data or []
        rows.extend(page)
        if len(page) < MAX_PAGE_SIZE:
            break
        offset += MAX_PAGE_SIZE
    return rows
