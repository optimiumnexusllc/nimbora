"""GDPR: privacy policy, right to be forgotten, right of access, register."""

from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.db import db_client
from api.db.models import UserModel
from api.services.auth.depends import get_user
from api.services.privacy.redaction import ALL_CATEGORIES, redact_text
from api.services.privacy.service import (
    PrivacySettings,
    erase_subject,
    export_subject,
    get_privacy_settings,
    save_privacy_settings,
)

router = APIRouter(prefix="/privacy", tags=["privacy"])


def _org(user: UserModel) -> int:
    if not user.selected_organization_id:
        raise HTTPException(status_code=400, detail="No organization selected")
    return user.selected_organization_id


class PrivacySettingsResponse(PrivacySettings):
    available_categories: list[str] = Field(
        default_factory=lambda: list(ALL_CATEGORIES)
    )


@router.get("/settings", response_model=PrivacySettingsResponse)
async def read_settings(user: UserModel = Depends(get_user)):
    settings = await get_privacy_settings(_org(user))
    return PrivacySettingsResponse(**settings.model_dump())


@router.put("/settings", response_model=PrivacySettingsResponse)
async def update_settings(
    request: PrivacySettings, user: UserModel = Depends(get_user)
):
    settings = await save_privacy_settings(_org(user), request)
    return PrivacySettingsResponse(**settings.model_dump())


class RedactionPreviewRequest(BaseModel):
    text: str = Field(max_length=5000)
    categories: list[str] | None = None


class RedactionPreviewResponse(BaseModel):
    text: str
    counts: dict[str, int]


@router.post("/preview", response_model=RedactionPreviewResponse)
async def preview_redaction(
    request: RedactionPreviewRequest, user: UserModel = Depends(get_user)
):
    """Try the masking rules on a sample sentence."""
    _org(user)
    categories = [
        c for c in (request.categories or ALL_CATEGORIES) if c in ALL_CATEGORIES
    ]
    result = redact_text(request.text, categories)
    return RedactionPreviewResponse(text=result.text, counts=result.counts)


class SubjectRequest(BaseModel):
    phone: str = Field(min_length=6, max_length=40)


class PrivacyRequestResponse(BaseModel):
    id: int
    kind: Literal["erasure", "export"]
    subject_hint: str
    status: str
    counts: dict[str, Any]
    error: str | None
    requested_by: int | None
    created_at: datetime | None
    completed_at: datetime | None


def _request_response(row) -> PrivacyRequestResponse:
    return PrivacyRequestResponse.model_validate(row, from_attributes=True)


@router.post("/erasure", response_model=PrivacyRequestResponse)
async def erase(request: SubjectRequest, user: UserModel = Depends(get_user)):
    """Right to be forgotten: erase everything tied to this phone number.

    Deletes recordings and transcripts, scrubs call records (kept anonymized
    for billing), deletes the customer profile, handoff cards and callbacks.
    """
    organization_id = _org(user)
    try:
        row = await erase_subject(organization_id, request.phone, requested_by=user.id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _request_response(row)


@router.post("/export")
async def export(request: SubjectRequest, user: UserModel = Depends(get_user)) -> dict:
    """Right of access: what the organization holds about this phone number."""
    organization_id = _org(user)
    try:
        return await export_subject(
            organization_id, request.phone, requested_by=user.id
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/requests", response_model=list[PrivacyRequestResponse])
async def list_requests(user: UserModel = Depends(get_user)):
    rows = await db_client.list_privacy_requests(_org(user))
    return [_request_response(r) for r in rows]
