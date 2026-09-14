from supabase import create_client, Client
import os
from dotenv import load_dotenv

load_dotenv()

# URL and key are read once at import time; a fresh client is created per call
# to avoid HTTP/2 stale-connection errors from long-lived connection pools.
_SUPABASE_URL = os.environ["SUPABASE_URL"]
_SUPABASE_KEY = os.environ["SUPABASE_SERVICE_KEY"]


def get_supabase() -> Client:
    return create_client(_SUPABASE_URL, _SUPABASE_KEY)


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
