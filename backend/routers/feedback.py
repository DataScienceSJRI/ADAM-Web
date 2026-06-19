import logging
import os
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from core.auth import get_current_user
from core.roles import require_coordinator
from core.supabase import get_supabase

logger = logging.getLogger("backend.routers.feedback")
router = APIRouter(prefix="/feedback", tags=["feedback"])


def _participant_email(user_id: str) -> str:
    """Participants are created with email {participant_id}@adam.participant."""
    return f"{user_id}@adam.participant"


@router.get("/reviews")
def list_reviews(
    user_id: str = Depends(get_current_user),
    role: str = Depends(require_coordinator),
):
    """Return MealImageReview entries grouped by participant."""
    sb = get_supabase()

    q = sb.table("UserRoles").select("user_id, participant_id, display_name").eq("role", "participant")
    if role == "coordinator":
        q = q.eq("coordinator_id", user_id)
    participants = (q.execute().data) or []

    if not participants:
        return []

    # Build lookup map keyed by BOTH participant_id ("P001") and email ("P001@adam.participant")
    # because MealImageReview.user_id is set from get_current_user() which returns JWT email
    participant_map: dict = {}
    lookup_ids: list = []
    for p in participants:
        pid = p["user_id"]  # "P001"
        email = _participant_email(pid)
        participant_map[pid] = p
        participant_map[email] = p
        lookup_ids.extend([pid, email])

    reviews = (
        sb.table("MealImageReview")
        .select("*")
        .in_("user_id", lookup_ids)
        .order("created_at", desc=True)
        .execute()
        .data
    ) or []

    # Enrich with meal_slot from DietRecall
    recall_ids = [r["diet_recall_id"] for r in reviews if r.get("diet_recall_id")]
    if recall_ids:
        recall_data = (
            sb.table("DietRecall").select("ID, meal_slot").in_("ID", recall_ids).execute().data
        ) or []
        meal_slot_map = {r["ID"]: r.get("meal_slot") for r in recall_data}
        for r in reviews:
            r["meal_slot"] = meal_slot_map.get(r.get("diet_recall_id"))

    # Group by canonical participant_id
    grouped: dict = {}
    for r in reviews:
        uid = r["user_id"]
        p = participant_map.get(uid) or participant_map.get(uid.split("@")[0])
        if not p:
            continue
        canonical = p["user_id"]  # "P001"
        if canonical not in grouped:
            grouped[canonical] = {
                "user_id": canonical,
                "participant_id": p.get("participant_id"),
                "display_name": p.get("display_name"),
                "pending_count": 0,
                "reviews": [],
            }
        grouped[canonical]["reviews"].append(r)
        if r.get("review_status") == "pending":
            grouped[canonical]["pending_count"] += 1

    return list(grouped.values())


class ReviewUpdateRequest(BaseModel):
    action: str  # "approve" | "reject" | "analyse" | "identify"
    reviewed_foods_by_human: Optional[str] = None
    vlm_backend: Optional[str] = None  # "openai" | "ollama" — only used with action="identify"


@router.patch("/reviews/{review_id}")
def update_review(
    review_id: str,
    body: ReviewUpdateRequest,
    user_id: str = Depends(get_current_user),
    role: str = Depends(require_coordinator),
):
    """Approve, reject, or trigger AI analysis for a meal image review."""
    sb = get_supabase()

    resp = sb.table("MealImageReview").select("*").eq("id", review_id).limit(1).execute()
    if not resp.data:
        raise HTTPException(status_code=404, detail="Review not found")
    review = resp.data[0]

    if body.action == "analyse":
        from services.ai_review import analyse_meal_images
        analysis = analyse_meal_images(
            pre_url=review.get("pre_image_id"),
            post_url=review.get("post_image_id"),
        )
        update: dict = {"tracked_foods_by_ai": analysis}

    elif body.action == "identify":
        pre_url = review.get("pre_image_id")
        if not pre_url:
            raise HTTPException(status_code=400, detail="No pre-meal image to identify")
        backend = body.vlm_backend or os.environ.get("VLM_BACKEND", "ollama")
        if backend not in ("openai", "ollama"):
            raise HTTPException(status_code=400, detail="vlm_backend must be 'openai' or 'ollama'")
        if backend == "openai":
            # OpenAI is fast (~15 s) — run synchronously so the result returns immediately.
            try:
                import json
                from services.food_id import identify_image_from_url_sync
                result = identify_image_from_url_sync(pre_url, vlm_backend="openai")
                update = {"tracked_foods_by_ai": json.dumps(result)}
            except RuntimeError as exc:
                raise HTTPException(status_code=503, detail=str(exc))
            except Exception:
                logger.exception("Food identification (OpenAI) failed for review %s", review_id)
                raise HTTPException(status_code=500, detail="Food identification failed")
        else:
            # Ollama is slow (~5 min) — enqueue and return immediately with processing sentinel.
            try:
                from services.food_id_worker import PROCESSING_SENTINEL, enqueue_food_id_job
                enqueue_food_id_job(review_id, pre_url, vlm_backend=backend)
                update = {"tracked_foods_by_ai": PROCESSING_SENTINEL}
            except Exception:
                logger.exception("Failed to enqueue food ID job for review %s", review_id)
                raise HTTPException(status_code=500, detail="Failed to queue food identification job")

    elif body.action in ("approve", "reject"):
        update = {
            "review_status": "approved" if body.action == "approve" else "rejected",
            "reviewed_by": user_id,
            "reviewed_at": datetime.now(timezone.utc).isoformat(),
        }
        if body.reviewed_foods_by_human is not None:
            update["reviewed_foods_by_human"] = body.reviewed_foods_by_human

    else:
        raise HTTPException(status_code=400, detail="action must be 'approve', 'reject', 'analyse', or 'identify'")

    updated = sb.table("MealImageReview").update(update).eq("id", review_id).execute()
    if not updated.data:
        raise HTTPException(status_code=500, detail="Update failed")
    return updated.data[0]
