import logging
from datetime import date as date_type, timedelta
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from concurrent.futures import ThreadPoolExecutor
from core.auth import get_current_user
from core.roles import require_coordinator
from core.supabase import get_supabase
from models.schemas import (
    DietRecallImageRequest,
    DietRecallLogRequest,
    DietRecallUpdateRequest,
    IdentifiedFood,
    ImageIdentifyResponse,
    MealSlot,
    RecallHistoryItem,
    RecallHistoryResponse,
    RecallImageResponse,
    RecallLogResponse,
)
from services.recall import log_recall, log_recall_image, compute_energy_for_quantity, compute_gl_for_quantity

logger = logging.getLogger("backend.routers.recall")

router = APIRouter(prefix="/recall", tags=["recall"])

_MEAL_SLOT_ORDER = {"breakfast": 0, "lunch": 1, "dinner": 2, "snacks": 3}


def _sort_recall_rows(rows: list) -> list:
    """Newest Date first; within a date, Breakfast -> Lunch -> Dinner -> Snacks.
    PostgREST's .order() can't express a custom (non-alphabetical) column
    order, so this is applied client-side. Python's sort is stable, so sorting
    by meal_slot first and then by Date (reverse) preserves the meal-slot order
    within each date."""
    rows = sorted(rows, key=lambda r: _MEAL_SLOT_ORDER.get(str(r.get("meal_slot", "")).strip().lower(), 99))
    rows.sort(key=lambda r: r.get("Date") or "", reverse=True)
    return rows


@router.post("/log", response_model=RecallLogResponse)
def recall_log(body: DietRecallLogRequest, user_id: str = Depends(get_current_user)):
    """Record whether the user ate as planned for a given meal slot."""
    # recipe_codes (plural) takes priority; fall back to legacy recipe_code
    codes = body.recipe_codes or ([body.recipe_code] if body.recipe_code else None)
    # actual_quantities (plural) takes priority; fall back to legacy actual_quantity
    quantities = body.actual_quantities or ([body.actual_quantity] if body.actual_quantity else None)
    recall_ids = log_recall(
        user_id=user_id,
        plan_id=body.plan_id,
        meal_slot=body.meal_slot,
        did_eat_as_planned=body.did_eat_as_planned,
        date=body.date,
        recipe_codes=codes,
        actual_quantities=quantities,
    )
    return RecallLogResponse(status="ok", recall_ids=recall_ids)


@router.get("", response_model=RecallHistoryResponse)
def get_recall_history(
    date: Optional[str] = Query(None, description="Filter by date YYYY-MM-DD"),
    meal_slot: Optional[MealSlot] = Query(None),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user_id: str = Depends(get_current_user),
):
    """Return the authenticated user's diet recall history: newest date first,
    and within each date, Breakfast -> Lunch -> Dinner -> Snacks."""
    sb = get_supabase()
    query = sb.table("DietRecall").select("*", count="exact").eq("user_id", user_id)
    if date:
        query = query.eq("Date", date)
    if meal_slot:
        query = query.eq("meal_slot", meal_slot.value)
    # Meal-slot ordering isn't expressible via PostgREST's .order(), so fetch a
    # bounded set of matching rows sorted by Date and re-sort/paginate client-side.
    resp = query.order("Date", desc=True).limit(2000).execute()
    sorted_rows = _sort_recall_rows(resp.data or [])

    # A meal-photo upload (POST /recall/image) inserts a DietRecall placeholder
    # with no Food_Name until a coordinator approves the matching MealImageReview
    # Hide it from history entirely until it's confirmed (approved -> Food_Name
    # gets filled in) so callers never have to special-case it: an unreviewed or
    # rejected photo simply doesn't show up as "logged" yet.
    def _is_confirmed(r: dict) -> bool:
        if r.get("Food_Name"):
            return True
        if r.get("did_eat_as_planned"):
            return True
        if r.get("image_url_pre") or r.get("image_url_post"):
            return False
        return True  # e.g. a "skipped" row — no food data, no photo, still a real entry

    sorted_rows = [r for r in sorted_rows if _is_confirmed(r)]
    page = sorted_rows[offset: offset + limit]
    items = [
        RecallHistoryItem(
            id=r.get("ID"),
            date=r.get("Date"),
            meal_slot=r.get("meal_slot"),
            did_eat_as_planned=r.get("did_eat_as_planned"),
            food_name=r.get("Food_Name"),
            food_qty=r.get("Food_Qty"),
            r_desc=r.get("R_desc"),
            energy_kcal=r.get("Energy_Kcal"),
            gl=r.get("GL"),
            notes=r.get("notes"),
        )
        for r in page
    ]
    return RecallHistoryResponse(items=items, total=len(sorted_rows))

@router.put("/{recall_id}")
def update_recall(recall_id: str, body: DietRecallUpdateRequest, user_id: str = Depends(get_current_user)):
    """Update a diet recall entry belonging to the authenticated user."""
    updates = {k: v for k, v in {
        "did_eat_as_planned": body.did_eat_as_planned,
        "Food_Name": body.food_name,
        "Food_Qty": body.food_qty,
        "meal_slot": body.meal_slot.value if body.meal_slot else None,
        "notes": body.notes,
    }.items() if v is not None}

    if not updates:
        raise HTTPException(status_code=400, detail="No fields provided to update.")

    sb = get_supabase()

    if body.food_qty is not None:
        existing = (
            sb.table("DietRecall")
            .select("Food_Name_desc")
            .eq("ID", recall_id)
            .eq("user_id", user_id)
            .maybe_single()
            .execute()
        )
        recipe_code = (existing.data or {}).get("Food_Name_desc")
        energy = compute_energy_for_quantity(recipe_code, body.food_qty)
        if energy is not None:
            updates["Energy_Kcal"] = energy
        gl = compute_gl_for_quantity(recipe_code, body.food_qty)
        if gl is not None:
            updates["GL"] = gl

    resp = sb.table("DietRecall").update(updates).eq("ID", recall_id).eq("user_id", user_id).execute()
    if not resp.data:
        raise HTTPException(status_code=404, detail="Recall entry not found")
    return {"status": "updated", "id": recall_id}


@router.delete("/{recall_id}")
def delete_recall(recall_id: str, user_id: str = Depends(get_current_user)):
    """Delete a diet recall entry belonging to the authenticated user."""
    sb = get_supabase()
    resp = sb.table("DietRecall").delete().eq("ID", recall_id).eq("user_id", user_id).execute()
    if not resp.data:
        raise HTTPException(status_code=404, detail="Recall entry not found")
    return {"status": "deleted", "id": recall_id}


@router.post("/image", response_model=RecallImageResponse)
def recall_image(body: DietRecallImageRequest, user_id: str = Depends(get_current_user)):
    """Upload pre/post meal photo URLs; creates a MealImageReview row (pending)."""
    recall_id, review_id = log_recall_image(
        user_id=user_id,
        plan_id=body.plan_id,
        meal_slot=body.meal_slot,
        image_url_pre=body.image_url_pre,
        image_url_post=body.image_url_post,
    )
    return RecallImageResponse(status="ok", recall_id=recall_id, review_id=review_id)


@router.post("/{recall_id}/identify", response_model=ImageIdentifyResponse)
async def identify_recall_image(recall_id: str, user_id: str = Depends(get_current_user)):
    """Run the food identification pipeline on the pre-meal image for a recall entry.

    Downloads the stored pre-meal image, identifies food items via VLM + ADS recipe
    matching, and returns recipe codes with gram estimates the frontend can use to
    pre-fill the recall form.
    """
    sb = get_supabase()
    row = (
        sb.table("DietRecall")
        .select("ID, user_id, image_url_pre")
        .eq("ID", recall_id)
        .eq("user_id", user_id)
        .maybe_single()
        .execute()
    )
    if not row.data:
        raise HTTPException(status_code=404, detail="Recall entry not found")

    image_url = row.data.get("image_url_pre")
    if not image_url:
        raise HTTPException(status_code=400, detail="No pre-meal image for this recall entry")

    from services.food_id import identify_image_from_url

    try:
        result = await identify_image_from_url(image_url)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception:
        logger.exception("Food identification failed for recall %s", recall_id)
        raise HTTPException(status_code=500, detail="Food identification failed")

    foods: list[IdentifiedFood] = []
    for fr in result.get("foods", []):
        match = fr.get("match", {})
        qty = fr.get("quantity")
        matched = match.get("matched")
        foods.append(
            IdentifiedFood(
                food_id=fr["food_id"],
                description=matched["recipe_name"] if matched else fr["food_id"],
                recipe_code=matched["recipe_code"] if matched else None,
                recipe_name=matched["recipe_name"] if matched else None,
                quantity_g=qty["quantity_g"] if qty else None,
                quantity_g_min=qty["quantity_g_min"] if qty else None,
                quantity_g_max=qty["quantity_g_max"] if qty else None,
                quantity_confidence=qty["quantity_confidence"] if qty else None,
                match_status=match["status"],
                match_confidence=match["match_confidence"],
            )
        )

    return ImageIdentifyResponse(
        analysis_id=result["analysis_id"],
        foods=foods,
        flags=result.get("flags", []),
    )


@router.get("/coordinator")
def list_coordinator_participants(
    user_id: str = Depends(get_current_user),
    role: str = Depends(require_coordinator),
):
    """Return all participants with their diet recall compliance summary (coordinator-only)."""
    sb = get_supabase()

    q = sb.table("UserRoles").select("user_id, participant_id, display_name").eq("role", "participant")
    if role == "coordinator":
        q = q.eq("coordinator_id", user_id)
    participants = q.execute().data or []

    if not participants:
        return []

    lookup_ids: list = []
    for p in participants:
        pid = p["user_id"]
        lookup_ids.append(pid)
        lookup_ids.append(f"{pid}@adam.participant")

    since = str(date_type.today() - timedelta(days=90))
    recalls = (
        sb.table("DietRecall")
        .select("ID, user_id, Date, meal_slot, did_eat_as_planned")
        .in_("user_id", lookup_ids)
        .gte("Date", since)
        .limit(5000)
        .execute()
        .data
    ) or []

    # Exclude image-derived rows that haven't been approved by a coordinator
    # yet — a pending/rejected photo shouldn't count as a logged meal.
    recall_ids = [r["ID"] for r in recalls if r.get("ID")]
    if recall_ids:
        review_rows = (
            sb.table("MealImageReview")
            .select("diet_recall_id, review_status")
            .in_("diet_recall_id", recall_ids)
            .execute()
            .data
        ) or []
        hidden_ids = {
            r["diet_recall_id"] for r in review_rows
            if r.get("review_status") != "approved"
        }
        recalls = [r for r in recalls if r["ID"] not in hidden_ids]

    recall_by_user: dict = {}
    for r in recalls:
        uid = r["user_id"]
        canonical = uid.split("@")[0]
        if canonical not in recall_by_user:
            recall_by_user[canonical] = {}
        date_str = (r.get("Date") or r.get("created_at") or "")[:10]
        slot = r.get("meal_slot") or ""
        key = f"{date_str}_{slot}"
        if key not in recall_by_user[canonical]:
            recall_by_user[canonical][key] = {"all_planned": True, "date": date_str}
        if not r.get("did_eat_as_planned"):
            recall_by_user[canonical][key]["all_planned"] = False

    result = []
    for p in participants:
        pid = p["user_id"]
        combos = recall_by_user.get(pid, {})
        total = len(combos)
        as_planned = sum(1 for c in combos.values() if c["all_planned"])
        pct = round(as_planned / total * 100, 1) if total > 0 else None
        dates = sorted({c["date"] for c in combos.values() if c["date"]}, reverse=True)
        result.append({
            "user_id": pid,
            "participant_id": p.get("participant_id"),
            "display_name": p.get("display_name"),
            "total_logged": total,
            "compliance_pct": pct,
            "last_logged_date": dates[0] if dates else None,
        })

    return result


@router.get("/coordinator/{participant_id}")
def get_participant_recall_logs(
    participant_id: str,
    user_id: str = Depends(get_current_user),
    role: str = Depends(require_coordinator),
):
    """Return DietRecall and Recommendation data for a specific participant (coordinator-only)."""
    sb = get_supabase()

    q = (
        sb.table("UserRoles")
        .select("user_id, participant_id, display_name")
        .eq("user_id", participant_id)
        .eq("role", "participant")
    )
    if role == "coordinator":
        q = q.eq("coordinator_id", user_id)
    rows = q.execute().data or []
    if not rows:
        raise HTTPException(status_code=404, detail="Participant not found or no access")
    participant = rows[0]

    email = f"{participant_id}@adam.participant"
    user_filter = [participant_id, email]

    def fetch_logs():
        rows = (
            sb.table("DietRecall")
            .select("*")
            .in_("user_id", user_filter)
            .order("Date", desc=True)
            .limit(500)
            .execute()
            .data
        ) or []

        # Image-derived rows stay invisible in the log view until the
        # coordinator has explicitly approved them (pending/rejected reviews
        # are hidden — only reviewed via the Image Review queue).
        recall_ids = [r["ID"] for r in rows if r.get("ID")]
        if recall_ids:
            review_rows = (
                sb.table("MealImageReview")
                .select("diet_recall_id, review_status")
                .in_("diet_recall_id", recall_ids)
                .execute()
                .data
            ) or []
            hidden_ids = {
                r["diet_recall_id"] for r in review_rows
                if r.get("review_status") != "approved"
            }
            rows = [r for r in rows if r["ID"] not in hidden_ids]

        return _sort_recall_rows(rows)

    def fetch_plan():
        return (
            sb.table("Recommendation")
            .select("Pkey, Date, Timings, Food_Name, Food_Name_desc, Food_Qty, R_desc, Energy_kcal, user_id")
            .in_("user_id", user_filter)
            .order("Date", desc=True)
            .limit(500)
            .execute()
            .data
        ) or []

    with ThreadPoolExecutor(max_workers=2) as ex:
        logs_future = ex.submit(fetch_logs)
        plan_future = ex.submit(fetch_plan)
        logs = logs_future.result()
        plan_rows = plan_future.result()

    dates_set: set = set()
    for r in logs:
        d = (r.get("Date") or "")[:10]
        if d:
            dates_set.add(d)
    for r in plan_rows:
        d = (r.get("Date") or "")[:10]
        if d:
            dates_set.add(d)

    return {
        "participant": {
            "user_id": participant["user_id"],
            "participant_id": participant.get("participant_id"),
            "display_name": participant.get("display_name"),
        },
        "dates": sorted(dates_set, reverse=True),
        "plan": plan_rows,
        "logs": logs,
    }


@router.patch("/coordinator/{recall_id}")
def coordinator_update_recall(
    recall_id: str,
    body: DietRecallUpdateRequest,
    user_id: str = Depends(get_current_user),
    role: str = Depends(require_coordinator),
):
    """Coordinator edits a diet recall entry."""
    updates = {k: v for k, v in {
        "did_eat_as_planned": body.did_eat_as_planned,
        "Food_Name": body.food_name,
        "Food_Qty": body.food_qty,
        "meal_slot": body.meal_slot.value if body.meal_slot else None,
        "notes": body.notes,
    }.items() if v is not None}

    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update.")

    sb = get_supabase()

    if body.food_qty is not None:
        existing = (
            sb.table("DietRecall").select("Food_Name_desc").eq("ID", recall_id).maybe_single().execute()
        )
        recipe_code = (existing.data or {}).get("Food_Name_desc")
        energy = compute_energy_for_quantity(recipe_code, body.food_qty)
        if energy is not None:
            updates["Energy_Kcal"] = energy
        gl = compute_gl_for_quantity(recipe_code, body.food_qty)
        if gl is not None:
            updates["GL"] = gl

    resp = sb.table("DietRecall").update(updates).eq("ID", recall_id).execute()
    if not resp.data:
        raise HTTPException(status_code=404, detail="Recall entry not found")
    return resp.data[0]


@router.delete("/coordinator/{recall_id}", status_code=204)
def coordinator_delete_recall(
    recall_id: str,
    user_id: str = Depends(get_current_user),
    role: str = Depends(require_coordinator),
):
    """Coordinator deletes a diet recall entry."""
    sb = get_supabase()
    resp = sb.table("DietRecall").delete().eq("ID", recall_id).execute()
    if not resp.data:
        raise HTTPException(status_code=404, detail="Recall entry not found")
