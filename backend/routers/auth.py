import logging
import os
import httpx
from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import OAuth2PasswordRequestForm
from core.auth import get_current_user, oauth2_scheme
from core.supabase import get_supabase
from models.schemas import LoginRequest, LoginResponse, RefreshRequest

logger = logging.getLogger("backend.routers.auth")

router = APIRouter(prefix="/auth", tags=["auth"])


def _clean_user_id(email: str | None) -> str:
    """Return the plain participant ID for @adam.participant accounts, full email otherwise.
    Supabase lowercases emails, so p001@adam.participant must be uppercased back to P001."""
    if not email:
        return ""
    if email.endswith("@adam.participant"):
        return email.split("@")[0].upper()
    return email


def _supabase_login(email: str, password: str) -> LoginResponse:
    sb = get_supabase()
    if "@" not in email:
        email = f"{email}@adam.participant"
    try:
        resp = sb.auth.sign_in_with_password({"email": email, "password": password})
    except Exception as exc:
        logger.warning("Login failed for %s: %s", email, exc)
        raise HTTPException(status_code=401, detail=str(exc))

    if not resp.session or not resp.session.access_token:
        raise HTTPException(status_code=401, detail="Authentication failed")

    return LoginResponse(
        access_token=resp.session.access_token,
        refresh_token=resp.session.refresh_token,
        user_id=_clean_user_id(resp.user.email),
    )


@router.post("/login", response_model=LoginResponse)
def login(body: LoginRequest):
    """Sign in with email + password (JSON)."""
    return _supabase_login(body.email, body.password)


@router.post("/token", response_model=LoginResponse)
def token(form: OAuth2PasswordRequestForm = Depends()):
    """OAuth2 password flow endpoint used by Swagger UI Authorize button.
    Enter your email in the 'username' field and your password in 'password'."""
    return _supabase_login(form.username, form.password)


@router.post("/refresh", response_model=LoginResponse)
def refresh(body: RefreshRequest):
    """Exchange a refresh token for a new access token."""
    supabase_url = os.environ.get("SUPABASE_URL", "")
    supabase_key = os.environ.get("SUPABASE_SERVICE_KEY", "") or os.environ.get("SUPABASE_KEY", "")
    try:
        res = httpx.post(
            f"{supabase_url}/auth/v1/token",
            params={"grant_type": "refresh_token"},
            json={"refresh_token": body.refresh_token},
            headers={"apikey": supabase_key, "Content-Type": "application/json"},
            timeout=10,
        )
    except Exception as exc:
        logger.warning("Token refresh request failed: %s", exc)
        raise HTTPException(status_code=503, detail="Auth service unavailable")

    if res.status_code != 200:
        logger.warning("Token refresh rejected: %s %s", res.status_code, res.text[:200])
        raise HTTPException(status_code=401, detail="Invalid or expired refresh token")

    data = res.json()
    access_token = data.get("access_token")
    refresh_token = data.get("refresh_token") or body.refresh_token
    email = (data.get("user") or {}).get("email")

    if not access_token:
        raise HTTPException(status_code=401, detail="Token refresh failed")

    return LoginResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        user_id=_clean_user_id(email),
    )


@router.post("/logout")
def logout(
    token: str = Depends(oauth2_scheme),
    user_id: str = Depends(get_current_user),
):
    """Invalidate the current session server-side (revokes refresh tokens)."""
    try:
        get_supabase().auth.admin.sign_out(token)
    except Exception as exc:
        logger.warning("Logout error for %s: %s", user_id, exc)
    return {"status": "ok"}
