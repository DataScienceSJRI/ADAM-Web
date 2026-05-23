import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query

from core.auth import get_current_user
from core.supabase import get_supabase
from models.schemas import RegisterTokenRequest

logger = logging.getLogger("backend.routers.notifications")

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.post("/register-token")
def register_token(body: RegisterTokenRequest, user_id: str = Depends(get_current_user)):
    """Register (or refresh) a OneSignal device token for push notifications."""
    sb = get_supabase()
    sb.table("DeviceTokens").upsert(
        {
            "user_id": user_id,
            "device_token": body.device_token,
            "platform": body.platform,
            "last_active": datetime.now(timezone.utc).isoformat(),
        },
        on_conflict="device_token",
    ).execute()
    return {"status": "ok"}


@router.delete("/device-token")
def delete_token(
    device_token: str = Query(..., description="OneSignal player_id to remove"),
    user_id: str = Depends(get_current_user),
):
    """Remove a device token so the user stops receiving push notifications on that device."""
    sb = get_supabase()
    sb.table("DeviceTokens").delete().eq("device_token", device_token).eq(
        "user_id", user_id
    ).execute()
    return {"status": "ok"}
