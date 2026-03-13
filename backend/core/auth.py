from fastapi import Depends, HTTPException, Header
from core.supabase import get_supabase


async def get_current_user(authorization: str = Header(...)) -> str:
    """Verify Supabase JWT and return the authenticated user's email."""
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    token = authorization[7:]
    try:
        response = get_supabase().auth.get_user(token)
        email = response.user and response.user.email
        if not email:
            raise HTTPException(status_code=401, detail="Token has no associated email")
        return email
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
