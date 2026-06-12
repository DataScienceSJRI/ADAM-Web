import logging
import uuid
from datetime import date as date_type

from core.supabase import get_supabase
from models.schemas import IntensityLevel

logger = logging.getLogger("backend.services.activity")


def log_activity(
    user_id: str,
    pa_name: str,
    duration_min: int,
    intensity: IntensityLevel,
    date: str | None = None,
) -> str:
    """Insert an activity log row. Returns the new row ID."""
    activity_id = str(uuid.uuid4())
    get_supabase().table("user_physical_activity_recall").insert(
        {
            "ID": activity_id,
            "UID": user_id,
            "PA_Name": pa_name,
            "Duration": duration_min,
            "Date": date or str(date_type.today()),
            "intensity": intensity.value,
        }
    ).execute()
    return activity_id
