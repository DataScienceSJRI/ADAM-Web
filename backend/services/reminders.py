import logging
from datetime import datetime, timezone, timedelta

from core.supabase import get_supabase
from services.push import send_bulk_push
from services.whatsapp_notify import send_whatsapp

logger = logging.getLogger("backend.services.reminders")

# Times stored in DB are IST (UTC+5:30); we compare against current IST time
_IST = timezone(timedelta(hours=5, minutes=30))

# Default meal times (HH, MM) used when a user has no preference set
_DEFAULTS: dict[str, tuple[int, int]] = {
    "breakfast": (8, 30),
    "lunch": (13, 0),
    "dinner": (19, 30),
}

_SLOT_LABELS = {
    "breakfast": "Breakfast",
    "lunch": "Lunch",
    "dinner": "Dinner",
}


def _time_to_minutes(time_str: str, default: tuple[int, int]) -> int:
    try:
        parts = time_str.split(":")
        return int(parts[0]) * 60 + int(parts[1])
    except Exception:
        return default[0] * 60 + default[1]


def send_meal_reminders(window_minutes: int = 7) -> dict[str, int]:
    """Send meal-logging reminders to users whose preferred meal time falls within
    ±window_minutes of now (IST). Falls back to default times (Breakfast 08:30,
    Lunch 13:00, Dinner 19:30 IST) for users with no preference set.
    Returns {slot: recipient_count} for slots that had at least one recipient.
    """
    sb = get_supabase()

    tokens_resp = sb.table("DeviceTokens").select("user_id, device_token").execute()
    user_tokens: dict[str, list[str]] = {}
    for row in (tokens_resp.data or []):
        uid = row.get("user_id")
        token = row.get("device_token")
        if uid and token:
            user_tokens.setdefault(uid, []).append(token)

    whatsapp_resp = (
        sb.table("WH_Users").select("user_id").not_.is_("activated_at", "null").execute()
    )
    whatsapp_user_ids = {row["user_id"] for row in (whatsapp_resp.data or []) if row.get("user_id")}

    all_user_ids = list(set(user_tokens.keys()) | whatsapp_user_ids)
    if not all_user_ids:
        return {}

    prefs_resp = (
        sb.table("BE_Preference_onboarding_details")
        .select("user_id, breakfast_time, lunch_time, dinner_time")
        .in_("user_id", all_user_ids)
        .execute()
    )
    user_prefs: dict[str, dict] = {r["user_id"]: r for r in (prefs_resp.data or [])}

    now_ist = datetime.now(_IST)
    now_minutes = now_ist.hour * 60 + now_ist.minute

    slot_player_ids: dict[str, list[str]] = {"breakfast": [], "lunch": [], "dinner": []}
    slot_user_ids: dict[str, list[str]] = {"breakfast": [], "lunch": [], "dinner": []}
    for uid in all_user_ids:
        prefs = user_prefs.get(uid, {})
        for slot, default in _DEFAULTS.items():
            raw_time = prefs.get(f"{slot}_time") or ""
            meal_minutes = _time_to_minutes(raw_time, default) if raw_time else (default[0] * 60 + default[1])
            if abs(now_minutes - meal_minutes) <= window_minutes:
                if uid in user_tokens:
                    slot_player_ids[slot].extend(user_tokens[uid])
                if uid in whatsapp_user_ids:
                    slot_user_ids[slot].append(uid)

    results: dict[str, int] = {}
    for slot, player_ids in slot_player_ids.items():
        if not player_ids:
            continue
        label = _SLOT_LABELS[slot]
        count = send_bulk_push(
            player_ids=player_ids,
            title=f"Reminder: Log your {label}",
            body="Keeping an accurate diet log helps the study team track your progress.",
            data={"type": "meal_reminder", "meal_slot": slot},
        )
        results[slot] = count
        logger.info("Meal reminder sent: slot=%s recipients=%d", slot, count)

    for slot, uids in slot_user_ids.items():
        if not uids:
            continue
        label = _SLOT_LABELS[slot]
        sent = 0
        for uid in uids:
            if send_whatsapp(
                uid,
                f"Reminder: Log your {label}",
                "Keeping an accurate diet log helps the study team track your progress.",
            ):
                sent += 1
        logger.info("WhatsApp meal reminder sent: slot=%s recipients=%d", slot, sent)

    return results
