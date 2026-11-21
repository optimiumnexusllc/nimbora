"""Blocked numbers: refused callers and numbers AI agents never call."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field

from api.db import db_client
from api.db.models import UserModel
from api.services.auth.depends import get_user
from api.services.telephony import blocklist

router = APIRouter(prefix="/blocked-numbers", tags=["blocked-numbers"])


def _org(user: UserModel) -> int:
    if not user.selected_organization_id:
        raise HTTPException(status_code=400, detail="No organization selected")
    return user.selected_organization_id


class BlockedNumberRequest(BaseModel):
    number: str = Field(min_length=3, max_length=40)
    direction: Literal["inbound", "outbound", "both"] = "both"
    reason: str = Field(default="", max_length=255)
    expires_at: datetime | None = None


class BlockedNumberResponse(BaseModel):
    id: int
    number: str
    direction: str
    reason: str | None
    source: str
    expires_at: str | None
    hits: int
    last_hit_at: str | None
    created_at: str | None


class BlockedNumberStats(BaseModel):
    total: int
    hits: int
    caller_requests: int


class BlockedNumberList(BaseModel):
    items: list[BlockedNumberResponse]
    total: int
    stats: BlockedNumberStats


class ImportRequest(BaseModel):
    content: str = Field(max_length=500_000)


class ImportResult(BaseModel):
    imported: int
    errors: list[dict[str, Any]]


@router.get("", response_model=BlockedNumberList)
async def list_blocked_numbers(
    search: str | None = Query(default=None, max_length=40),
    user: UserModel = Depends(get_user),
):
    organization_id = _org(user)
    rows = await db_client.list_blocked_numbers(
        organization_id, search=(search or "").strip() or None
    )
    stats = await db_client.blocked_number_stats(organization_id)
    return {
        "items": [blocklist.serialize(r) for r in rows],
        "total": stats["total"],
        "stats": stats,
    }


@router.post("", response_model=BlockedNumberResponse, status_code=201)
async def add_blocked_number(
    request: BlockedNumberRequest, user: UserModel = Depends(get_user)
):
    try:
        row = await blocklist.block(
            _org(user),
            blocklist.BlockRequest(
                number=request.number,
                direction=request.direction,
                reason=request.reason,
                expires_at=request.expires_at,
            ),
            user_id=user.id,
        )
    except blocklist.BlockedNumberError as error:
        raise HTTPException(status_code=error.status, detail=str(error)) from error
    return blocklist.serialize(row)


@router.delete("/{entry_id}", status_code=204)
async def remove_blocked_number(entry_id: int, user: UserModel = Depends(get_user)):
    if not await db_client.delete_blocked_number(_org(user), entry_id):
        raise HTTPException(status_code=404, detail="Numéro introuvable")
    return Response(status_code=204)


@router.post("/import", response_model=ImportResult)
async def import_blocked_numbers(
    request: ImportRequest, user: UserModel = Depends(get_user)
):
    """CSV ``numero;motif;sens`` (sens : entrant, sortant ou les deux)."""
    try:
        return await blocklist.import_numbers(
            _org(user), request.content, user_id=user.id
        )
    except blocklist.BlockedNumberError as error:
        raise HTTPException(status_code=error.status, detail=str(error)) from error
