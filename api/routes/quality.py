"""Quality control of human calls: grid, AI evaluation, supervisor review."""

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query

from api.db import db_client
from api.db.models import UserModel
from api.services.auth.depends import get_user
from api.services.quality import service as quality
from api.services.quality.service import QualityError, QualitySettings, ReviewIn

router = APIRouter(prefix="/quality", tags=["quality"])


def _org(user: UserModel) -> int:
    if not user.selected_organization_id:
        raise HTTPException(status_code=400, detail="Aucune organisation sélectionnée")
    return user.selected_organization_id


async def _call(coro):
    try:
        return await coro
    except QualityError as error:
        raise HTTPException(status_code=error.status, detail=str(error)) from error


@router.get("/settings", response_model=QualitySettings)
async def read_quality_settings(user: UserModel = Depends(get_user)):
    """The grid (criteria and weights) and the automatic evaluation."""
    return await quality.get_settings(_org(user))


@router.put("/settings", response_model=QualitySettings)
async def save_quality_settings(
    settings: QualitySettings, user: UserModel = Depends(get_user)
):
    return await quality.save_settings(_org(user), settings)


@router.get("/reviews")
async def list_quality_reviews(
    status: Literal["pending", "evaluated", "reviewed", "failed"] | None = None,
    agent: str | None = Query(default=None, max_length=64),
    days: int = Query(default=30, ge=1, le=365),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    user: UserModel = Depends(get_user),
) -> dict[str, Any]:
    """Evaluated calls, most recent first."""
    from datetime import UTC, datetime, timedelta

    rows, total = await db_client.list_quality_reviews(
        _org(user),
        status=status,
        agent_extension=agent,
        since=datetime.now(UTC) - timedelta(days=days),
        limit=limit,
        offset=offset,
    )
    return {"items": [quality.serialize(r, rec) for r, rec in rows], "total": total}


@router.get("/reviews/{review_id}")
async def read_quality_review(
    review_id: int, user: UserModel = Depends(get_user)
) -> dict[str, Any]:
    """One evaluation, with the grid, both sets of answers and the transcript."""
    return await _call(quality.get_review(_org(user), review_id))


@router.put("/reviews/{review_id}")
async def submit_quality_review(
    review_id: int, review: ReviewIn, user: UserModel = Depends(get_user)
) -> dict[str, Any]:
    """The supervisor's answers: they become the call's score."""
    org = _org(user)
    await _call(quality.submit_review(org, review_id, review, user.id))
    return await _call(quality.get_review(org, review_id))


@router.post("/recordings/{recording_id}/evaluate")
async def evaluate_recording(
    recording_id: int, user: UserModel = Depends(get_user)
) -> dict[str, Any]:
    """Evaluate a recorded call with the AI now (from its transcript)."""
    org = _org(user)
    result = await _call(quality.evaluate(org, recording_id))
    return await _call(quality.get_review(org, result["id"]))


@router.post("/recordings/{recording_id}/review")
async def start_manual_review(
    recording_id: int, user: UserModel = Depends(get_user)
) -> dict[str, Any]:
    """Open an evaluation to fill by hand (no AI, no transcript needed)."""
    org = _org(user)
    result = await _call(quality.start_review(org, recording_id))
    return await _call(quality.get_review(org, result["id"]))


@router.get("/summary")
async def quality_summary(
    days: int = Query(default=30, ge=1, le=365), user: UserModel = Depends(get_user)
) -> dict[str, Any]:
    """Average score per advisor and success rate per criterion."""
    return await quality.summary(_org(user), days)
