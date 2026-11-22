"""Leads: prospects qualified by the agents, followed through the pipeline."""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field

from api.db import db_client
from api.db.models import UserModel
from api.services.auth.depends import get_user
from api.services.leads import service as leads
from api.services.leads.service import LeadIn, Stage

router = APIRouter(prefix="/leads", tags=["leads"])


def _org(user: UserModel) -> int:
    if not user.selected_organization_id:
        raise HTTPException(status_code=400, detail="Aucune organisation sélectionnée")
    return user.selected_organization_id


@router.get("")
async def list_leads(
    stage: Stage | None = None,
    q: str | None = Query(default=None, max_length=100),
    user: UserModel = Depends(get_user),
) -> dict[str, Any]:
    """Leads (best score first) and the pipeline: count and budgets per stage."""
    org = _org(user)
    rows = await db_client.list_leads(
        org, stage=stage, search=(q or "").strip() or None
    )
    return {
        "leads": [leads.lead_out(x) for x in rows],
        "pipeline": await leads.pipeline(org),
    }


@router.post("", status_code=201)
async def create_lead(
    spec: LeadIn, user: UserModel = Depends(get_user)
) -> dict[str, Any]:
    return await leads.create_lead(_org(user), spec)


@router.put("/{lead_id}")
async def update_lead(
    lead_id: int, spec: LeadIn, user: UserModel = Depends(get_user)
) -> dict[str, Any]:
    try:
        return await leads.update_lead(_org(user), lead_id, spec)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


class MoveRequest(BaseModel):
    stage: Stage
    lost_reason: str | None = Field(default=None, max_length=255)


@router.post("/{lead_id}/stage")
async def move_lead(
    lead_id: int, move: MoveRequest, user: UserModel = Depends(get_user)
) -> dict[str, Any]:
    """Move a lead in the pipeline (won and lost close it)."""
    try:
        return await leads.move_lead(_org(user), lead_id, move.stage, move.lost_reason)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.delete("/{lead_id}", status_code=204)
async def delete_lead(lead_id: int, user: UserModel = Depends(get_user)) -> None:
    if not await db_client.delete_lead(_org(user), lead_id):
        raise HTTPException(status_code=404, detail="Prospect introuvable")


@router.get("/export.csv")
async def export_leads(user: UserModel = Depends(get_user)) -> Response:
    return Response(
        content="﻿" + await leads.export_csv(_org(user)),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="prospects.csv"'},
    )
