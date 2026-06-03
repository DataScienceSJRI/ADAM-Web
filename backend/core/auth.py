import os
import logging
from functools import lru_cache

import jwt
from jwt import PyJWKClient
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("backend.auth")

_CREDENTIALS_EXCEPTION = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Could not validate credentials",
    headers={"WWW-Authenticate": "Bearer"},
)

_root_path = os.environ.get("ROOT_PATH", "")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl=f"{_root_path}/api/v1/auth/token")


@lru_cache(maxsize=1)
def _jwks_client() -> PyJWKClient:
    supabase_url = os.environ.get("SUPABASE_URL", "")
    if not supabase_url:
        raise RuntimeError("SUPABASE_URL env var is not set")
    return PyJWKClient(f"{supabase_url}/auth/v1/.well-known/jwks.json")


def get_current_user(token: str = Depends(oauth2_scheme)) -> str:
    """Verify Supabase JWT locally via JWKS and return the authenticated user's email."""
    try:
        signing_key = _jwks_client().get_signing_key_from_jwt(token)
        payload = jwt.decode(
            token,
            signing_key.key,
            algorithms=["ES256"],
            audience="authenticated",
        )
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except jwt.InvalidTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token: {exc}",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except Exception:
        logger.exception("JWT verification failed")
        raise _CREDENTIALS_EXCEPTION

    email: str | None = payload.get("email")
    if not email:
        raise _CREDENTIALS_EXCEPTION
    # Participant accounts use P001@adam.participant (Supabase lowercases emails,
    # so it arrives as p001@adam.participant). Strip the domain and uppercase so
    # the result always matches the stored user_id ("P001").
    if email.endswith("@adam.participant"):
        return email.split("@")[0].upper()
    return email
