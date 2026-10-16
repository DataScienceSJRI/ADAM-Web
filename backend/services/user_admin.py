import json
import logging
from datetime import datetime, timezone

logger = logging.getLogger("backend.services.user_admin")

# Every table that stores a participant's data, keyed by the app's own
# user_id string (not Supabase Auth's internal UUID -- see core/auth.py's
# get_current_user, which derives user_id from the JWT email claim).
# Deleted before UserRoles so a failure partway through still leaves the
# participant visible (as disabled) rather than silently orphaning rows.
_USER_ID_COLUMN_TABLES = [
    "OutsideFoodLog",
    "DietRecallBuffer",
    "MealImageReview",
    "DietRecall",
    "MealReactions",
    "user_weight_log",
    "FinalNutrientSummary",
    "FinalSummary",
    "RecommendationsBackup",
    "Recommendation",
    "BE_Onboarding_Sessions",
    "BE_Preference_onboarding",
    "BE_Preference_onboarding_details",
    "BE_Basic_Details",
    "DeviceTokens",
    "WH_Users",
]

# These two use "UID" instead of "user_id" for historical reasons.
_UID_COLUMN_TABLES = ["user_physical_activity_recall", "Recipes_LU"]

# The snapshot (all per-user tables + auth account, as JSON) is uploaded
# here rather than stored in a Postgres jsonb column -- Storage is billed
# and limited separately from database size, which is the resource this
# whole cleanup effort is trying to reduce, not add to.
_BACKUP_BUCKET = "deleted-participants"
_BACKUP_SIGNED_URL_TTL_SECONDS = 30 * 24 * 3600  # 30 days

_bucket_ready = False


def _ensure_bucket(sb) -> None:
    global _bucket_ready
    if _bucket_ready:
        return
    try:
        sb.storage.create_bucket(_BACKUP_BUCKET, options={"public": False})
    except Exception as exc:
        # BucketAlreadyExists is the expected/common case after the first call.
        if "already exists" not in str(exc).lower() and "duplicate" not in str(exc).lower():
            raise
    _bucket_ready = True


def _find_auth_account(sb, user_id: str) -> dict | None:
    try:
        email = f"{user_id.lower()}@adam.participant"
        auth_users = sb.auth.admin.list_users(page=1, per_page=1000)
        match = next((u for u in auth_users if (u.email or "").lower() == email), None)
        return {"id": match.id, "email": match.email, "created_at": str(match.created_at)} if match else None
    except Exception:
        logger.exception("_find_auth_account: could not look up auth account for user_id=%s", user_id)
        return None


def _snapshot_participant(sb, user_id: str) -> dict:
    """Reads (never deletes) every row belonging to user_id across all known
    per-user tables plus the matching Supabase Auth account, for the backup
    uploaded before any delete runs."""
    snapshot: dict = {}

    for table in _USER_ID_COLUMN_TABLES:
        try:
            snapshot[table] = sb.table(table).select("*").eq("user_id", user_id).execute().data or []
        except Exception:
            logger.exception("_snapshot_participant: could not read %s for user_id=%s", table, user_id)
            snapshot[table] = None  # None means "couldn't capture", distinct from "[] = genuinely empty"

    for table in _UID_COLUMN_TABLES:
        try:
            snapshot[table] = sb.table(table).select("*").eq("UID", user_id).execute().data or []
        except Exception:
            logger.exception("_snapshot_participant: could not read %s for user_id=%s", table, user_id)
            snapshot[table] = None

    snapshot["auth_account"] = _find_auth_account(sb, user_id)
    return snapshot


def _write_backup(sb, user_id: str, participant_id: str | None, display_name: str | None, deleted_by: str, snapshot: dict) -> str | None:
    """Uploads the snapshot to Storage, then records a small metadata row
    pointing at it. Returns the storage path on success, None on any
    failure (nothing partial is left behind: if the metadata insert fails
    after a successful upload, the uploaded file is removed again)."""
    _ensure_bucket(sb)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    storage_path = f"{user_id}/{timestamp}.json"
    # jsonb-style round-trip through json.dumps so unexpected pydantic types
    # (Decimal, datetime) from the snapshot don't break serialization.
    payload = json.dumps(snapshot, default=str).encode("utf-8")

    try:
        sb.storage.from_(_BACKUP_BUCKET).upload(storage_path, payload, file_options={"content-type": "application/json"})
    except Exception:
        logger.exception("_write_backup: could not upload snapshot for user_id=%s", user_id)
        return None

    try:
        sb.table("DeletedParticipantsBackup").insert({
            "user_id": user_id,
            "participant_id": participant_id,
            "display_name": display_name,
            "deleted_by": deleted_by,
            "storage_path": storage_path,
        }).execute()
    except Exception:
        logger.exception("_write_backup: could not write metadata row for user_id=%s -- removing orphaned upload", user_id)
        try:
            sb.storage.from_(_BACKUP_BUCKET).remove([storage_path])
        except Exception:
            logger.exception("_write_backup: could not clean up orphaned upload at %s", storage_path)
        return None

    return storage_path


def get_backup_signed_url(sb, storage_path: str) -> str | None:
    try:
        result = sb.storage.from_(_BACKUP_BUCKET).create_signed_url(storage_path, _BACKUP_SIGNED_URL_TTL_SECONDS)
        return result.get("signedURL")
    except Exception:
        logger.exception("get_backup_signed_url: could not sign URL for %s", storage_path)
        return None


def delete_participant_data(
    sb, user_id: str, *, participant_id: str | None = None, display_name: str | None = None,
    deleted_by: str = "unknown", backup: bool = True,
) -> tuple[dict[str, int], str | None]:
    """Permanently deletes every row belonging to user_id, finishing with
    the UserRoles row itself. Irreversible from the app's point of view.
    Caller is responsible for checking the participant is already disabled
    and the caller is authorized (see routers/users.py's delete_participant).

    backup=True (the default -- use for real participants, participant_id
    starting "A") snapshots everything to the "deleted-participants" Storage
    bucket BEFORE deleting, and aborts with nothing deleted if that snapshot
    can't be saved. backup=False (test/P-accounts -- their data has no
    retention value, see conversation 2026-10-16) skips snapshotting
    entirely and deletes straight away; the Supabase Auth account is still
    looked up and removed either way.

    Returns (counts, backup_signed_url). counts is {table_name: rows_deleted},
    with -1 for any table a delete failed on (logged, not raised, so one bad
    table doesn't abort the rest). With backup=True, if the backup couldn't
    be saved at all, counts is {} and backup_signed_url is None -- nothing
    was deleted. With backup=False, backup_signed_url is always None."""
    storage_path: str | None = None
    auth_account_id: str | None = None

    if backup:
        snapshot = _snapshot_participant(sb, user_id)
        storage_path = _write_backup(sb, user_id, participant_id, display_name, deleted_by, snapshot)
        if storage_path is None:
            # Nothing below has run yet, so nothing has been deleted.
            # Deleting data we failed to back up would defeat the whole
            # point of backing it up first.
            return {}, None
        auth_account_id = (snapshot.get("auth_account") or {}).get("id")
    else:
        auth_account_id = (_find_auth_account(sb, user_id) or {}).get("id")

    counts: dict[str, int] = {}

    for table in _USER_ID_COLUMN_TABLES:
        try:
            resp = sb.table(table).delete().eq("user_id", user_id).execute()
            counts[table] = len(resp.data or [])
        except Exception:
            logger.exception("delete_participant_data: could not delete from %s for user_id=%s", table, user_id)
            counts[table] = -1

    for table in _UID_COLUMN_TABLES:
        try:
            resp = sb.table(table).delete().eq("UID", user_id).execute()
            counts[table] = len(resp.data or [])
        except Exception:
            logger.exception("delete_participant_data: could not delete from %s for user_id=%s", table, user_id)
            counts[table] = -1

    # Best-effort: also remove the Supabase Auth account, so the now-deleted
    # participant's credentials can't log in to an empty account.
    try:
        if auth_account_id:
            sb.auth.admin.delete_user(auth_account_id)
            counts["auth_account"] = 1
        else:
            counts["auth_account"] = 0
    except Exception:
        logger.exception("delete_participant_data: could not delete auth account for user_id=%s", user_id)
        counts["auth_account"] = -1

    try:
        resp = sb.table("UserRoles").delete().eq("user_id", user_id).execute()
        counts["UserRoles"] = len(resp.data or [])
    except Exception:
        logger.exception("delete_participant_data: could not delete UserRoles row for user_id=%s", user_id)
        counts["UserRoles"] = -1

    backup_url = get_backup_signed_url(sb, storage_path) if storage_path else None
    return counts, backup_url
