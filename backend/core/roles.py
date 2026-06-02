from fastapi import Depends, HTTPException
from core.auth import get_current_user
from core.supabase import get_supabase


def get_current_role(user_id: str = Depends(get_current_user)) -> str:
    resp = get_supabase().table("UserRoles").select("role").eq("user_id", user_id).limit(1).execute()
    if not resp.data:
        return "participant"
    return resp.data[0]["role"]


def require_coordinator(role: str = Depends(get_current_role)) -> str:
    if role not in ("coordinator", "admin"):
        raise HTTPException(status_code=403, detail="Coordinator or admin access required")
    return role


def require_admin(role: str = Depends(get_current_role)) -> str:
    if role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return role
