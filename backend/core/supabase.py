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
