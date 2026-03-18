import os
from functools import lru_cache

import jwt
from fastapi import Header, HTTPException

from dotenv import load_dotenv

load_dotenv()


@lru_cache(maxsize=1)
def _jwt_secret() -> str:
    secret = os.environ.get("SUPABASE_JWT_SECRET", "")
    if not secret:
        raise RuntimeError("SUPABASE_JWT_SECRET env var is not set")
    return secret


async def get_current_user(authorization: str = Header(...)) -> str:
    """Verify Supabase JWT locally and return the authenticated user's email.
    """
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    token = authorization[7:]
    try:
        payload = jwt.decode(
            token,
            _jwt_secret(),
            algorithms=["HS256"],
            audience="authenticated",
        )
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token has expired")
    except jwt.InvalidTokenError as exc:
        raise HTTPException(status_code=401, detail=f"Invalid token: {exc}")

    email: str | None = payload.get("email")
    if not email:
        raise HTTPException(status_code=401, detail="Token has no associated email")
    return email
