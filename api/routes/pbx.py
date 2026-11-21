"""Enterprise PBX (white-labelled telephony platform)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from api.db import db_client
from api.db.models import UserModel
from api.services.auth.depends import get_user
from api.services.branding import brand
from api.services.pbx import service as pbx
from api.services.pbx.client import PbxAuthError, PbxError, PbxUnavailable

router = APIRouter(prefix="/pbx", tags=["pbx"])
public_router = APIRouter(prefix="/pbx", tags=["pbx"])

MASK = "••••••••"


def _org(user: UserModel) -> int:
    if not user.selected_organization_id:
        raise HTTPException(status_code=400, detail="No organization selected")
    return user.selected_organization_id


def _pbx_http_error(error: PbxError) -> HTTPException:
    if isinstance(error, PbxAuthError):
        return HTTPException(status_code=502, detail=f"PBX : accès refusé ({error})")
    if isinstance(error, PbxUnavailable):
        return HTTPException(status_code=504, detail=str(error))
    status = 404 if error.status == 404 else 502
    return HTTPException(status_code=status, detail=f"PBX : {error}")


class BrandInfo(BaseModel):
    name: str
    pbx_name: str
    sip_user_agent: str


class ConnectionResponse(BaseModel):
    configured: bool
    brand: BrandInfo
    name: str | None = None
    base_url: str | None = None
    username: str | None = None
    password: str | None = None
    tenant_uuid: str | None = None
    verify_tls: bool = True
    ari_configuration_id: int | None = None
    incall_context: str | None = None
    status: str | None = None
    last_error: str | None = None
    engine_version: str | None = None
    last_checked_at: datetime | None = None
    branding_applied_at: datetime | None = None
    events_connected: bool = False


class ConnectionRequest(BaseModel):
    name: str = Field(default="PBX", max_length=128)
    base_url: str = Field(min_length=8, max_length=512)
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(
        default="", max_length=512, description="Leave empty (or masked) to keep."
    )
    tenant_uuid: str | None = Field(default=None, max_length=64)
    verify_tls: bool = True
    ari_configuration_id: int | None = None
    incall_context: str | None = Field(default=None, max_length=128)


class RouteRequest(BaseModel):
    number: str = Field(min_length=2, max_length=32)
    workflow_id: int


class RouteResponse(BaseModel):
    number: str
    incall_id: int
    workflow_id: int
    workflow_name: str
    phone_number_id: int


class AgentActionRequest(BaseModel):
    extension: str | None = None
    context: str | None = None
    reason: str | None = Field(default=None, max_length=80)


def _brand_info() -> BrandInfo:
    b = brand()
    return BrandInfo(name=b.name, pbx_name=b.pbx_name, sip_user_agent=b.sip_user_agent)


def _to_response(connection) -> ConnectionResponse:
    if connection is None:
        return ConnectionResponse(configured=False, brand=_brand_info())
    return ConnectionResponse(
        configured=True,
        brand=_brand_info(),
        name=connection.name,
        base_url=connection.base_url,
        username=connection.username,
        password=MASK,
        tenant_uuid=connection.tenant_uuid,
        verify_tls=connection.verify_tls,
        ari_configuration_id=connection.ari_configuration_id,
        incall_context=connection.incall_context,
        status=connection.status,
        last_error=connection.last_error,
        engine_version=connection.engine_version,
        last_checked_at=connection.last_checked_at,
        branding_applied_at=connection.branding_applied_at,
        events_connected=bool(connection.webhook_subscription_uuid),
    )


@router.get("/connection", response_model=ConnectionResponse)
async def read_connection(user: UserModel = Depends(get_user)):
    return _to_response(await db_client.get_pbx_connection(_org(user)))


@router.put("/connection", response_model=ConnectionResponse)
async def save_connection(
    request: ConnectionRequest, user: UserModel = Depends(get_user)
):
    """Save the PBX connection, then check it (credentials, version, tenant)."""
    organization_id = _org(user)
    try:
        pbx.assert_pbx_url_allowed(request.base_url)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    if request.ari_configuration_id is not None:
        ari = await db_client.get_telephony_configuration_for_org(
            request.ari_configuration_id, organization_id
        )
        if ari is None or ari.provider != "ari":
            raise HTTPException(status_code=404, detail="Configuration ARI introuvable")
    existing = await db_client.get_pbx_connection(organization_id)
    fields: dict[str, Any] = request.model_dump()
    fields["base_url"] = request.base_url.rstrip("/")
    fields["tenant_uuid"] = (request.tenant_uuid or "").strip() or None
    fields["incall_context"] = (request.incall_context or "").strip() or None
    if not request.password or request.password == MASK:
        if existing is None:
            raise HTTPException(status_code=422, detail="Mot de passe requis")
        fields.pop("password")
    if existing is None:
        fields["webhook_token"] = pbx.new_webhook_token()
    await db_client.save_pbx_connection(organization_id, fields)
    connection = await pbx.refresh_status(organization_id)
    return _to_response(connection)


@router.delete("/connection", status_code=204)
async def delete_connection(user: UserModel = Depends(get_user)):
    if not await db_client.delete_pbx_connection(_org(user)):
        raise HTTPException(status_code=404, detail="Aucun PBX connecté")
    return Response(status_code=204)


@router.post("/connection/test", response_model=ConnectionResponse)
async def test_connection(user: UserModel = Depends(get_user)):
    try:
        return _to_response(await pbx.refresh_status(_org(user)))
    except pbx.PbxNotConfigured as error:
        raise HTTPException(status_code=404, detail="Aucun PBX connecté") from error


async def _call(coro):
    try:
        return await coro
    except pbx.PbxNotConfigured as error:
        raise HTTPException(status_code=404, detail="Aucun PBX connecté") from error
    except pbx.PbxRouteError as error:
        raise HTTPException(status_code=error.status, detail=str(error)) from error
    except PbxError as error:
        raise _pbx_http_error(error) from error


@router.get("/inventory")
async def read_inventory(user: UserModel = Depends(get_user)) -> dict[str, Any]:
    """Users, queues, agents (with status), numbers and live calls."""
    return await _call(pbx.inventory(_org(user)))


@router.post("/routes", response_model=RouteResponse)
async def route_number(request: RouteRequest, user: UserModel = Depends(get_user)):
    """Make a PBX number ring an AI agent."""
    return await _call(
        pbx.route_number_to_agent(_org(user), request.number, request.workflow_id)
    )


@router.delete("/routes/{number}", status_code=204)
async def unroute_number(number: str, user: UserModel = Depends(get_user)):
    if not await _call(pbx.unroute_number(_org(user), number)):
        raise HTTPException(
            status_code=404, detail="Ce numéro n'est pas routé vers un agent IA"
        )
    return Response(status_code=204)


@router.post("/branding/apply")
async def apply_branding(user: UserModel = Depends(get_user)) -> dict[str, str]:
    """Apply the platform brand to what the PBX exposes (SIP User-Agent)."""
    return await _call(pbx.apply_branding(_org(user)))


@router.post("/events/connect")
async def connect_events(user: UserModel = Depends(get_user)) -> dict[str, str | None]:
    """Subscribe NIMBORA to the PBX's call events (history of human calls)."""
    from api.constants import BACKEND_API_ENDPOINT

    uuid = await _call(pbx.ensure_webhook(_org(user), BACKEND_API_ENDPOINT))
    return {"subscription_uuid": uuid}


@router.post("/calls/{call_id}/hangup", status_code=204)
async def hangup_call(call_id: str, user: UserModel = Depends(get_user)):
    async def run():
        connection = await pbx._connection(_org(user))
        async with pbx.client_for(connection) as client:
            await client.hangup(call_id)

    await _call(run())
    return Response(status_code=204)


@router.post("/agents/{agent_number}/{action}", status_code=204)
async def agent_action(
    agent_number: str,
    action: Literal["login", "logoff", "pause", "unpause"],
    request: AgentActionRequest | None = None,
    user: UserModel = Depends(get_user),
):
    body: dict[str, Any] = {}
    request = request or AgentActionRequest()
    if action == "login":
        if not request.extension or not request.context:
            raise HTTPException(
                status_code=422,
                detail="Poste et contexte requis pour connecter un agent",
            )
        body = {"extension": request.extension, "context": request.context}
    elif action == "pause" and request.reason:
        body = {"reason": request.reason}

    async def run():
        connection = await pbx._connection(_org(user))
        async with pbx.client_for(connection) as client:
            await client.agent_action(agent_number, action, body)

    await _call(run())
    return Response(status_code=204)


@router.get("/call-logs")
async def call_logs(
    limit: int = 50, user: UserModel = Depends(get_user)
) -> list[dict[str, Any]]:
    async def run():
        connection = await pbx._connection(_org(user))
        async with pbx.client_for(connection) as client:
            rows = await client.cdr(limit=max(1, min(limit, 200)))
        return [
            {
                "id": r.get("id"),
                "start": r.get("start"),
                "answered": r.get("answered"),
                "duration": r.get("duration"),
                "direction": r.get("call_direction"),
                "source_name": r.get("source_name"),
                "source": r.get("source_extension"),
                "destination_name": r.get("destination_name"),
                "destination": r.get("destination_extension"),
            }
            for r in rows
        ]

    return await _call(run())


class PasswordResetRequest(BaseModel):
    host: str = Field(min_length=1, max_length=255)
    user_uuid: str = Field(min_length=8, max_length=64)
    token: str = Field(min_length=8, max_length=128)
    password: str = Field(min_length=8, max_length=128)


@public_router.post("/password-reset", status_code=204)
async def reset_password(request: PasswordResetRequest):
    """Public: the white-label page behind the PBX's password-reset e-mail."""
    try:
        await pbx.reset_user_password(
            request.host, request.user_uuid, request.token, request.password
        )
    except pbx.PbxNotConfigured as error:
        raise HTTPException(status_code=404, detail="Lien invalide") from error
    except PbxAuthError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except PbxError as error:
        raise _pbx_http_error(error) from error
    return Response(status_code=204)


@public_router.post("/events/{token}", status_code=204, include_in_schema=False)
async def receive_event(token: str, request: Request, event: str | None = None):
    """Webhook from the PBX. The unguessable token identifies the organization."""
    connection = await db_client.get_pbx_connection_by_webhook_token(token)
    if connection is None:
        raise HTTPException(status_code=404)
    try:
        payload = await request.json()
    except ValueError:
        payload = None
    await pbx.handle_event(connection, event, payload)
    return Response(status_code=204)
