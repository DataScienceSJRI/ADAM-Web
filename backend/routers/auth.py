import logging
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
    sb = get_supabase()
    try:
        resp = sb.auth.refresh_session(body.refresh_token)
    except Exception as exc:
        logger.warning("Token refresh failed: %s", exc)
        raise HTTPException(status_code=401, detail="Invalid or expired refresh token")

    if not resp.session or not resp.session.access_token:
        raise HTTPException(status_code=401, detail="Token refresh failed")

    return LoginResponse(
        access_token=resp.session.access_token,
        refresh_token=resp.session.refresh_token,
        user_id=_clean_user_id(resp.user.email),
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
