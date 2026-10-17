from supabase import create_client, Client
import os
import threading
import time
from dotenv import load_dotenv

load_dotenv()

_SUPABASE_URL = os.environ["SUPABASE_URL"]
_SUPABASE_KEY = os.environ["SUPABASE_SERVICE_KEY"]


def _disable_http2_on_subclients() -> None:
    """supabase-py's postgrest/gotrue/storage3 sub-clients each hardcode
    http2=True for their own internal httpx session, with no option exposed
    through create_client()/ClientOptions to turn it off. That matters here
    because of an unresolved httpx/httpcore bug: when a pooled HTTP/2
    connection is closed by the SERVER while idle, the next request on it
    raises httpx.RemoteProtocolError("... ConnectionTerminated ...") instead
    of transparently reconnecting
    (https://github.com/encode/httpx/issues -- httpcore's HTTP/2 path does
    not retry past this the way its HTTP/1.1 path does).

    PostgREST's Warp HTTP server idle-closes connections after ~30s by
    default (logged on Supabase's side as "Warp server error: Thread killed
    by timeout manager") -- so ANY pooled/reused client that goes idle for
    more than ~30s hits this exact bug on its next call, surfacing as a 500.
    This was true of a long-lived singleton (which is why get_supabase() was
    originally fresh-per-call), and it's equally true of this module's own
    TTL-rotated singleton below for any gap between calls shorter than the
    TTL but longer than ~30s.

    httpx's HTTP/1.1 path doesn't have this bug -- its connection pool
    already proactively expires and transparently replaces idle connections
    (keepalive_expiry defaults to 5s) and reliably detects a server-closed
    connection before reusing it. Forcing http2=False moves onto that
    well-tested path, which is what actually makes a pooled/reused client
    safe here -- the TTL below is just a loose hygiene bound on top of it,
    not the mechanism preventing staleness.

    Patches the one `http2=True` call site in each of the three libraries'
    installed versions (postgrest 0.17.2, gotrue, storage3) rather than
    vendoring them. If a future upgrade changes those internals, this
    silently stops taking effect rather than crashing -- re-verify after
    bumping either package."""
    import httpx

    try:
        from postgrest._sync.client import SyncPostgrestClient
        from postgrest.utils import SyncClient as _PostgrestSyncClient

        def _postgrest_create_session(self, base_url, headers, timeout, verify=True, proxy=None):
            return _PostgrestSyncClient(
                base_url=base_url, headers=headers, timeout=timeout,
                verify=verify, proxy=proxy, follow_redirects=True, http2=False,
            )

        SyncPostgrestClient.create_session = _postgrest_create_session
    except Exception:
        pass

    try:
        from gotrue._sync.gotrue_base_api import SyncGoTrueBaseAPI
        from gotrue.http_clients import SyncClient as _GotrueSyncClient

        _orig_gotrue_init = SyncGoTrueBaseAPI.__init__

        def _gotrue_init(self, *, url, headers, http_client=None, verify=True, proxy=None):
            http_client = http_client or _GotrueSyncClient(
                verify=bool(verify), proxy=proxy, follow_redirects=True, http2=False,
            )
            _orig_gotrue_init(self, url=url, headers=headers, http_client=http_client, verify=verify, proxy=proxy)

        SyncGoTrueBaseAPI.__init__ = _gotrue_init
    except Exception:
        pass

    try:
        from storage3._sync.client import SyncStorageClient
        from storage3.utils import SyncClient as _StorageSyncClient

        def _storage_create_session(self, base_url, headers, timeout, verify=True, proxy=None):
            return _StorageSyncClient(
                base_url=base_url, headers=headers, timeout=timeout,
                proxy=proxy, verify=bool(verify), follow_redirects=True, http2=False,
            )

        SyncStorageClient._create_session = _storage_create_session
    except Exception:
        pass


_disable_http2_on_subclients()

# get_supabase() used to create a brand-new client (and a brand-new TLS
# connection) on EVERY call. With ~90 call sites across the backend plus
# several always-on RQ workers, that meant a fresh connection opened per
# query instead of the normal HTTP/1.1 keep-alive pattern of reusing one,
# which was pushing the Supabase project into "Unhealthy" in the dashboard
# under load. It's now a process-wide singleton. _CLIENT_TTL_SECONDS below
# is just a loose hygiene bound (periodic recycling), not what makes reuse
# safe -- see _disable_http2_on_subclients() for the actual fix for stale
# pooled connections.
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
    stale = None
    with _client_lock:
        now = time.monotonic()
        if _client is None or (now - _client_created_at) >= _CLIENT_TTL_SECONDS:
            stale = _client
            _client = _new_client()
            _client_created_at = now
        current = _client
    if stale is not None:
        _close_client(stale)
    return current


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
