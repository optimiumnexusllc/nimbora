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
from api.services.pbx import admin
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


# ------------------------------------------------------- administration


class ExtensionRequest(BaseModel):
    firstname: str = Field(min_length=1, max_length=64)
    lastname: str = Field(default="", max_length=64)
    extension: str = Field(min_length=2, max_length=10)
    email: str | None = Field(default=None, max_length=254)
    line: Literal["sip", "webrtc"] = "sip"
    voicemail: bool = True
    agent: bool = False


class ExtensionCredentials(BaseModel):
    login: str
    login_password: str
    sip_username: str
    sip_password: str
    voicemail_pin: str | None


class ExtensionResponse(BaseModel):
    uuid: str
    name: str
    extension: str
    context: str
    line: str
    agent_id: int | None
    credentials: ExtensionCredentials = Field(
        description="Shown once: the PBX keeps them, NIMBORA does not store them."
    )


class ImportRequest(BaseModel):
    content: str = Field(max_length=500_000, description="CSV, comma or semicolon")


class ImportRow(BaseModel):
    line: int
    firstname: str
    lastname: str
    extension: str
    email: str | None
    type: str
    voicemail: bool
    agent: bool
    errors: list[str]


class ImportResult(BaseModel):
    created: list[ExtensionResponse]
    failed: list[ImportRow]
    credentials_csv: str


class LoginRequest(BaseModel):
    login: str = Field(min_length=2, max_length=254)


class QueueRequest(BaseModel):
    label: str = Field(min_length=1, max_length=128)
    extension: str = Field(min_length=2, max_length=10)
    strategy: str = "leastrecent"
    ring_seconds: int = Field(default=20, ge=5, le=120)
    agent_ids: list[int] = Field(default_factory=list, max_length=200)
    overflow_workflow_id: int | None = None
    overflow_after_seconds: int = Field(default=60, ge=10, le=3600)


class OverflowRequest(BaseModel):
    workflow_id: int | None = Field(description="None removes the overflow")
    after_seconds: int = Field(default=60, ge=10, le=3600)


class ScheduleRequest(BaseModel):
    incall_ids: list[int] = Field(min_length=1, max_length=100)
    closed: Literal["ai_agent", "voicemail", "hangup"] = "ai_agent"
    workflow_id: int | None = None
    voicemail_id: int | None = None


@router.post("/extensions", response_model=ExtensionResponse)
async def create_extension(
    request: ExtensionRequest, user: UserModel = Depends(get_user)
):
    """User + line + extension + SIP account + voicemail + login (+ agent)."""
    return await _call(
        admin.create_extension(_org(user), admin.NewExtension(**request.model_dump()))
    )


@router.delete("/extensions/{user_uuid}", status_code=204)
async def delete_extension(user_uuid: str, user: UserModel = Depends(get_user)):
    await _call(admin.delete_extension(_org(user), user_uuid))
    return Response(status_code=204)


@router.post("/extensions/password-reset", status_code=204)
async def extension_password_reset(
    request: LoginRequest, user: UserModel = Depends(get_user)
):
    """E-mail the user a white-label reset link."""
    await _call(admin.send_password_reset(_org(user), request.login))
    return Response(status_code=204)


@router.post("/extensions/import/preview", response_model=list[ImportRow])
async def preview_import(request: ImportRequest, user: UserModel = Depends(get_user)):
    return await _call(admin.preview_import(_org(user), request.content))


@router.post("/extensions/import", response_model=ImportResult)
async def run_import(request: ImportRequest, user: UserModel = Depends(get_user)):
    result = await _call(admin.run_import(_org(user), request.content))
    return {**result, "credentials_csv": admin.credentials_csv(result["created"])}


@router.get("/strategies")
async def strategies(user: UserModel = Depends(get_user)) -> dict[str, str]:
    return admin.STRATEGIES


@router.post("/queues")
async def create_queue(
    request: QueueRequest, user: UserModel = Depends(get_user)
) -> dict[str, Any]:
    return await _call(
        admin.create_queue(_org(user), admin.NewQueue(**request.model_dump()))
    )


@router.delete("/queues/{queue_id}", status_code=204)
async def delete_queue(queue_id: int, user: UserModel = Depends(get_user)):
    await _call(admin.delete_queue(_org(user), queue_id))
    return Response(status_code=204)


@router.put("/queues/{queue_id}/overflow")
async def queue_overflow(
    queue_id: int, request: OverflowRequest, user: UserModel = Depends(get_user)
) -> dict[str, Any]:
    """Too long a wait, nobody answering or logged in → this AI agent."""
    return await _call(
        admin.set_queue_overflow(
            _org(user), queue_id, request.workflow_id, request.after_seconds
        )
    )


@router.put("/queues/{queue_id}/members/{agent_id}", status_code=204)
async def add_queue_member(
    queue_id: int, agent_id: int, user: UserModel = Depends(get_user)
):
    await _call(admin.set_queue_member(_org(user), queue_id, agent_id, True))
    return Response(status_code=204)


@router.delete("/queues/{queue_id}/members/{agent_id}", status_code=204)
async def remove_queue_member(
    queue_id: int, agent_id: int, user: UserModel = Depends(get_user)
):
    await _call(admin.set_queue_member(_org(user), queue_id, agent_id, False))
    return Response(status_code=204)


@router.get("/voicemails")
async def list_voicemails(user: UserModel = Depends(get_user)) -> list[dict[str, Any]]:
    async def run():
        connection = await pbx._connection(_org(user))
        async with pbx.client_for(connection) as client:
            return [
                {"id": v.get("id"), "name": v.get("name"), "number": v.get("number")}
                for v in await client.voicemails()
            ]

    return await _call(run())


@router.put("/schedule")
async def sync_schedule(
    request: ScheduleRequest, user: UserModel = Depends(get_user)
) -> dict[str, Any]:
    """Apply the opening hours of 'Mon entreprise' to PBX numbers."""
    return await _call(
        admin.sync_opening_hours(
            _org(user),
            request.incall_ids,
            request.closed,
            request.workflow_id,
            request.voicemail_id,
        )
    )


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
