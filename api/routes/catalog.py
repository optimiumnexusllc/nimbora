"""Catalog: what the company sells or rents, searched by its agents."""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field

from api.db import db_client
from api.db.models import UserModel
from api.services.auth.depends import get_user
from api.services.catalog import service as catalog
from api.services.catalog.service import CatalogError, CatalogItemIn

router = APIRouter(prefix="/catalog", tags=["catalog"])

MAX_IMPORT_BYTES = 5 * 1024 * 1024


def _org(user: UserModel) -> int:
    if not user.selected_organization_id:
        raise HTTPException(status_code=400, detail="Aucune organisation sélectionnée")
    return user.selected_organization_id


@router.get("/items")
async def list_items(
    q: str = Query(default="", max_length=200),
    kind: str | None = Query(default=None),
    category: str | None = Query(default=None, max_length=100),
    available_only: bool = False,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    user: UserModel = Depends(get_user),
) -> dict[str, Any]:
    """Items, searched like the agent does (words without accents)."""
    return await catalog.list_items(
        _org(user),
        query=q,
        kind=kind,
        category=category,
        available_only=available_only,
        limit=limit,
        offset=offset,
    )


@router.post("/items", status_code=201)
async def create_item(
    spec: CatalogItemIn, user: UserModel = Depends(get_user)
) -> dict[str, Any]:
    try:
        return await catalog.save_item(_org(user), spec)
    except CatalogError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.put("/items/{item_id}")
async def update_item(
    item_id: int, spec: CatalogItemIn, user: UserModel = Depends(get_user)
) -> dict[str, Any]:
    try:
        return await catalog.save_item(_org(user), spec, item_id)
    except CatalogError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


class StockUpdate(BaseModel):
    stock: int | None = Field(ge=0, description="None: not tracked")
    available: bool | None = None


@router.patch("/items/{item_id}/stock")
async def update_stock(
    item_id: int, update: StockUpdate, user: UserModel = Depends(get_user)
) -> dict[str, Any]:
    """Quick stock change, without touching the rest of the item."""
    fields: dict[str, Any] = {"stock": update.stock}
    if update.available is not None:
        fields["available"] = update.available
    item = await db_client.update_catalog_item(_org(user), item_id, fields)
    if item is None:
        raise HTTPException(status_code=404, detail="Article introuvable")
    return catalog.item_out(item)


@router.delete("/items/{item_id}", status_code=204)
async def delete_item(item_id: int, user: UserModel = Depends(get_user)) -> None:
    if not await db_client.delete_catalog_item(_org(user), item_id):
        raise HTTPException(status_code=404, detail="Article introuvable")


@router.post("/import")
async def import_items(
    file: UploadFile,
    currency: str = Query(default="XOF", pattern=r"^[A-Za-z]{3}$"),
    user: UserModel = Depends(get_user),
) -> dict[str, Any]:
    """CSV (comma or semicolon): nom, reference, type, categorie, description,
    prix, devise, unite, stock, disponible, url, tags; any other column becomes
    a characteristic. Items with a known reference are updated."""
    content = await file.read(MAX_IMPORT_BYTES + 1)
    if len(content) > MAX_IMPORT_BYTES:
        raise HTTPException(status_code=413, detail="Fichier trop lourd (5 Mo au plus)")
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = content.decode("latin-1")
    try:
        return await catalog.import_csv(_org(user), text, currency.upper())
    except CatalogError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.get("/export.csv")
async def export_items(user: UserModel = Depends(get_user)) -> Response:
    content = await catalog.export_csv(_org(user))
    return Response(
        content="﻿" + content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="catalogue.csv"'},
    )


class AgentSearch(BaseModel):
    query: str = Field(default="", max_length=200)
    max_price: float | None = None
    min_price: float | None = None
    category: str | None = None
    available_only: bool = True
    currency: str = Field(default="XOF", pattern=r"^[A-Z]{3}$")


@router.post("/agent-preview")
async def agent_preview(
    search: AgentSearch, user: UserModel = Depends(get_user)
) -> dict[str, Any]:
    """What the agent would get for this search (to test the catalog)."""
    from api.services.actions.common import ActionContext

    ctx = ActionContext(
        organization_id=_org(user), tool_uuid="preview", tool_name="preview"
    )
    return await catalog.handle_catalog(
        ctx,
        {"currency": search.currency, "max_results": 5},
        {"action": "search", **search.model_dump(exclude={"currency"})},
    )
