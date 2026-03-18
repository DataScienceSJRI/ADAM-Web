import os
import logging
from functools import lru_cache

import jwt
from jwt import PyJWKClient
from fastapi import Header, HTTPException
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("backend.auth")


@lru_cache(maxsize=1)
def _jwks_client() -> PyJWKClient:
    supabase_url = os.environ.get("SUPABASE_URL", "")
    if not supabase_url:
        raise RuntimeError("SUPABASE_URL env var is not set")
    return PyJWKClient(f"{supabase_url}/auth/v1/.well-known/jwks.json")


async def get_current_user(authorization: str = Header(...)) -> str:
    """Verify Supabase JWT locally via JWKS and return the authenticated user's email.

    Supabase now signs tokens with ES256 (asymmetric). The public key is fetched
    once from the JWKS endpoint and cached — no network call on subsequent requests.
    """
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    token = authorization[7:]
    try:
        signing_key = _jwks_client().get_signing_key_from_jwt(token)
        payload = jwt.decode(
            token,
            signing_key.key,
            algorithms=["ES256"],
            audience="authenticated",
        )
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token has expired")
    except jwt.InvalidTokenError as exc:
        raise HTTPException(status_code=401, detail=f"Invalid token: {exc}")
    except Exception:
        logger.exception("JWT verification failed")
        raise HTTPException(status_code=401, detail="Could not verify token")

    email: str | None = payload.get("email")
    if not email:
        raise HTTPException(status_code=401, detail="Token has no associated email")
    return email
