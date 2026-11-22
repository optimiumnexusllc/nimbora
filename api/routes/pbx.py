"""Enterprise PBX (white-labelled telephony platform)."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from api.db import db_client
from api.db.models import UserModel
from api.services.auth.depends import get_user
from api.services.branding import brand
from api.services.pbx import (
    admin,
    conferences,
    forwards,
    groups,
    ivr,
    numbers,
    outbound,
    permissions,
    provisioning,
    recordings,
    softphone,
    teamwork,
    trunks,
)
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
    # Tenant created by the platform on its shared PBX: read-only for the company.
    managed: bool = False


class PlanAccessResponse(BaseModel):
    shared: bool
    dedicated: bool
    shared_available: bool
    seats_limit: int | None
    seats_used: int | None
    plan_name: str | None
    connected: bool
    managed: bool


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
        managed=bool(getattr(connection, "managed", False)),
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
    if existing is not None and existing.managed:
        raise HTTPException(
            status_code=409,
            detail="Ce PBX est géré par la plateforme : ses réglages ne se modifient pas ici.",
        )
    await _call(provisioning.assert_dedicated_allowed(organization_id))
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
    existing = await db_client.get_pbx_connection(_org(user))
    if existing is not None and existing.managed:
        raise HTTPException(
            status_code=409,
            detail="Ce PBX est géré par la plateforme : contactez votre opérateur pour le retirer.",
        )
    if not await db_client.delete_pbx_connection(_org(user)):
        raise HTTPException(status_code=404, detail="Aucun PBX connecté")
    return Response(status_code=204)


@router.get("/plan", response_model=PlanAccessResponse)
async def read_plan_access(user: UserModel = Depends(get_user)):
    """What the plan allows: shared or own PBX, human seats used and included."""
    organization_id = _org(user)
    access = await provisioning.pbx_access(organization_id)
    connection = await db_client.get_pbx_connection(organization_id)
    seats_used = None
    if connection is not None:
        try:
            async with pbx.client_for(await pbx._connection(organization_id)) as client:
                pbx_users = len(await client.users())
            seats_used = await provisioning.seats_in_use(organization_id, pbx_users)
        except PbxError:
            seats_used = None
    return PlanAccessResponse(
        **access.as_dict(),
        seats_used=seats_used,
        connected=connection is not None,
        managed=bool(connection is not None and connection.managed),
    )


@router.post("/provision", response_model=ConnectionResponse)
async def provision(user: UserModel = Depends(get_user)):
    """Create the company's tenant on the platform's shared PBX and connect it."""
    from api.constants import BACKEND_API_ENDPOINT

    try:
        connection = await _call(
            provisioning.provision_organization(
                _org(user), public_base_url=BACKEND_API_ENDPOINT
            )
        )
    except provisioning.ProvisioningUnavailable as error:
        raise HTTPException(
            status_code=404,
            detail="La plateforme ne propose pas de PBX partagé.",
        ) from error
    return _to_response(connection)


class RoutingSimulation(BaseModel):
    caller_number: str | None = Field(default=None, max_length=32)
    language: str | None = Field(default=None, max_length=8)
    skill: str | None = Field(default=None, max_length=60)


@router.get("/routing")
async def read_routing(user: UserModel = Depends(get_user)) -> dict[str, Any]:
    """Intelligent routing policy (VIP, usual advisor, skills, languages)."""
    from api.services.contact_center import smart_routing

    return await smart_routing.read_policy(_org(user))


@router.put("/routing")
async def save_routing(
    request: dict[str, Any], user: UserModel = Depends(get_user)
) -> dict[str, Any]:
    from api.services.contact_center import smart_routing

    try:
        return await smart_routing.save_policy(_org(user), request)
    except (ValueError, TypeError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.post("/routing/simulate")
async def simulate_routing(
    request: RoutingSimulation, user: UserModel = Depends(get_user)
) -> dict[str, Any]:
    """Where a hand-off would go now, and why (nothing is dialled)."""
    from api.services.contact_center import smart_routing

    try:
        decision = await smart_routing.route(
            _org(user),
            caller_number=request.caller_number,
            language=request.language,
            skill=request.skill,
        )
    except smart_routing.NoAgentAvailable as error:
        policy = await smart_routing.read_policy(_org(user))
        smart_routing.log_decision(
            _org(user),
            "simulation",
            reason=f"unavailable/{policy['when_unavailable']}",
            destination=None,
            steps=error.steps,
        )
        return {
            "destination": None,
            "reason": "unavailable",
            "explanation": str(error),
            "steps": error.steps,
            "when_unavailable": policy["when_unavailable"],
        }
    smart_routing.log_decision(
        _org(user),
        "simulation",
        reason=decision.reason,
        destination=decision.destination,
        steps=decision.steps,
    )
    return decision.as_dict()


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


async def _changed(organization_id: int) -> None:
    """Refresh the open supervision consoles after an action from NIMBORA."""
    from api.services.pbx import supervision
    from api.services.supervision.stream import notify

    supervision.invalidate(organization_id)
    await notify(organization_id, "pbx")


class MissedCallPolicy(BaseModel):
    enabled: bool = False
    workflow_id: int | None = None
    delay_minutes: int = Field(default=5, ge=0, le=1440)
    scope: Literal["queues", "all"] = "queues"
    within_hours: bool = True


@router.get("/missed-calls")
async def read_missed_calls(user: UserModel = Depends(get_user)) -> dict[str, Any]:
    """How missed calls are called back by an AI agent, and the latest ones."""
    from api.services.pbx import missed_calls

    connection = await _call(pbx._connection(_org(user)))
    return {
        "policy": missed_calls.read_policy(connection),
        "recent": await missed_calls.recent_callbacks(_org(user)),
    }


@router.put("/missed-calls")
async def save_missed_calls(
    request: MissedCallPolicy, user: UserModel = Depends(get_user)
) -> dict[str, Any]:
    from api.services.pbx import missed_calls

    return {
        "policy": await _call(
            missed_calls.save_policy(_org(user), request.model_dump())
        )
    }


@router.get("/transfer-targets")
async def transfer_targets(user: UserModel = Depends(get_user)) -> list[dict[str, Any]]:
    """PBX queues and extensions an AI agent can hand a caller to."""
    from api.services.pbx import handoff

    return await _call(handoff.transfer_targets(_org(user)))


@router.get("/inventory")
async def read_inventory(user: UserModel = Depends(get_user)) -> dict[str, Any]:
    """Users, queues, agents (with status), numbers and live calls."""
    return await _call(pbx.inventory(_org(user)))


@router.get("/presence")
async def read_presence(user: UserModel = Depends(get_user)) -> dict[str, Any]:
    """Presence of each extension: available, on a call, ringing, do not
    disturb, away or offline."""
    from api.services.pbx.presence import organization_presence

    return await _call(organization_presence(_org(user)))


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
    await _changed(_org(user))
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
    await _changed(_org(user))
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


class SipLineCredentials(BaseModel):
    extension: str | None
    sip_identity: str | None = Field(
        description="Endpoint name: the SIP user a phone registers as"
    )
    sip_username: str | None = Field(description="Authentication user name")
    sip_password: str


class SipPasswordResponse(BaseModel):
    uuid: str
    lines: list[SipLineCredentials] = Field(
        description="Shown once: the PBX keeps the secret, NIMBORA does not store it."
    )


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


@router.post("/extensions/{user_uuid}/sip-password", response_model=SipPasswordResponse)
async def rotate_extension_sip_password(
    user_uuid: str, user: UserModel = Depends(get_user)
):
    """A new SIP secret for the extension's lines, shown once. NIMBORA
    Softphone picks it up by itself; phones configured by hand need it."""
    return await _call(admin.rotate_sip_password(_org(user), user_uuid))


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


# ----------------------------------------------------------- voice menus


class MenuRequest(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    spec: ivr.MenuSpec


class PromptPreviewRequest(BaseModel):
    text: str = Field(min_length=1, max_length=800)
    voice_workflow_id: int | None = None


@router.get("/menus")
async def list_menus(user: UserModel = Depends(get_user)) -> list[dict[str, Any]]:
    """Voice menus designed in the visual editor (draft and published)."""
    return [ivr.serialize(m) for m in await db_client.list_pbx_ivr_menus(_org(user))]


@router.post("/menus", status_code=201)
async def create_menu(
    request: MenuRequest, user: UserModel = Depends(get_user)
) -> dict[str, Any]:
    row = await _call(ivr.create_menu(_org(user), request.name, request.spec))
    return ivr.serialize(row)


@router.put("/menus/{menu_id}")
async def update_menu(
    menu_id: int, request: MenuRequest, user: UserModel = Depends(get_user)
) -> dict[str, Any]:
    row = await _call(ivr.update_menu(_org(user), menu_id, request.name, request.spec))
    return ivr.serialize(row)


@router.post("/menus/{menu_id}/publish")
async def publish_menu(
    menu_id: int, user: UserModel = Depends(get_user)
) -> dict[str, Any]:
    """Speak the prompts with the organization's voice and publish on the PBX."""
    return await _call(ivr.publish_menu(_org(user), menu_id))


@router.delete("/menus/{menu_id}", status_code=204)
async def delete_menu(menu_id: int, user: UserModel = Depends(get_user)):
    await _call(ivr.delete_menu(_org(user), menu_id))
    return Response(status_code=204)


@router.post("/menus/spoken-text")
async def menu_spoken_text(
    spec: ivr.MenuSpec, user: UserModel = Depends(get_user)
) -> dict[str, str]:
    """What callers will hear (the menu text written from the choices)."""
    _org(user)
    return {"greeting": spec.greeting_text.strip(), "menu": spec.spoken_menu()}


@router.post(
    "/prompts/preview",
    response_class=Response,
    responses={200: {"content": {"audio/wav": {}}}},
)
async def preview_prompt(
    request: PromptPreviewRequest, user: UserModel = Depends(get_user)
) -> Response:
    """Listen to a prompt before publishing (telephone quality, 8 kHz)."""
    from api.services.pbx.prompts import synthesize_prompt

    audio = await _call(
        synthesize_prompt(
            _org(user), request.text, voice_workflow_id=request.voice_workflow_id
        )
    )
    return Response(
        content=audio, media_type="audio/wav", headers={"Cache-Control": "no-store"}
    )


# --------------------------------------------------- numbers (DIDs)


class NumberRequest(BaseModel):
    number: str = Field(min_length=2, max_length=32)
    destination: ivr.MenuAction


@router.put("/numbers")
async def set_number_destination(
    request: NumberRequest, user: UserModel = Depends(get_user)
) -> dict[str, Any]:
    """Where a public number rings (created on the PBX if new)."""
    return await _call(
        numbers.set_number_destination(_org(user), request.number, request.destination)
    )


@router.delete("/numbers/{number}", status_code=204)
async def remove_number(number: str, user: UserModel = Depends(get_user)):
    if not await _call(numbers.remove_number(_org(user), number)):
        raise HTTPException(status_code=404, detail="Numéro inconnu du PBX")
    return Response(status_code=204)


# ------------------------------------------ operator lines & routes


class TrunkRequest(BaseModel):
    label: str = Field(min_length=1, max_length=128)
    host: str = Field(min_length=1, max_length=253)
    port: int = Field(default=5060, ge=1, le=65535)
    transport: Literal["udp", "tcp", "tls"] = "udp"
    username: str = Field(default="", max_length=64)
    password: str = Field(default="", max_length=128)
    registration: bool = Field(
        default=True, description="Register with the operator (login/password)."
    )
    caller_id_format: Literal["+E164", "E164", "national"] = "+E164"


class DialRuleModel(BaseModel):
    pattern: str = Field(min_length=1, max_length=40)
    strip_digits: int = Field(default=0, ge=0, le=20)
    prefix: str = Field(default="", max_length=20)
    external_prefix: str = Field(default="", max_length=20)
    caller_id: str = Field(default="", max_length=24)


class OutboundRouteRequest(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    trunk_ids: list[int] = Field(min_length=1, max_length=10)
    rules: list[DialRuleModel] = Field(min_length=1, max_length=20)
    internal_caller_id: bool = False
    ring_seconds: int = Field(default=60, ge=10, le=300)


class DialTestRequest(BaseModel):
    dialled: str = Field(min_length=1, max_length=40)
    rules: list[DialRuleModel] = Field(min_length=1, max_length=20)


@router.get("/trunks")
async def list_trunks(user: UserModel = Depends(get_user)) -> dict[str, Any]:
    """Operator lines with their registration state and live calls."""
    return await _call(trunks.list_trunks(_org(user)))


@router.post("/trunks", status_code=201)
async def create_trunk(
    request: TrunkRequest, user: UserModel = Depends(get_user)
) -> dict[str, Any]:
    return await _call(
        trunks.create_trunk(
            _org(user),
            trunks.NewTrunk(
                **request.model_dump(exclude={"registration"}),
                register=request.registration,
            ),
        )
    )


@router.delete("/trunks/{trunk_id}", status_code=204)
async def delete_trunk(trunk_id: int, user: UserModel = Depends(get_user)):
    await _call(trunks.delete_trunk(_org(user), trunk_id))
    return Response(status_code=204)


@router.get("/outbound-routes")
async def list_outbound_routes(
    user: UserModel = Depends(get_user),
) -> dict[str, Any]:
    routes = await _call(trunks.list_outbound_routes(_org(user)))
    return {"routes": routes, "presets": trunks.PATTERN_PRESETS}


@router.post("/outbound-routes", status_code=201)
async def create_outbound_route(
    request: OutboundRouteRequest, user: UserModel = Depends(get_user)
) -> dict[str, Any]:
    spec = trunks.NewOutboundRoute(
        name=request.name,
        trunk_ids=request.trunk_ids,
        rules=[trunks.DialRule(**r.model_dump()) for r in request.rules],
        internal_caller_id=request.internal_caller_id,
        ring_seconds=request.ring_seconds,
    )
    return await _call(trunks.create_outbound_route(_org(user), spec))


@router.delete("/outbound-routes/{outcall_id}", status_code=204)
async def delete_outbound_route(outcall_id: int, user: UserModel = Depends(get_user)):
    await _call(trunks.delete_outbound_route(_org(user), outcall_id))
    return Response(status_code=204)


@router.post("/outbound-routes/test")
async def test_dial(
    request: DialTestRequest, user: UserModel = Depends(get_user)
) -> dict[str, Any]:
    """Which rule a dialled number matches, and what the operator receives."""
    _org(user)
    for index, model in enumerate(request.rules):
        rule = trunks.DialRule(**model.model_dump())
        try:
            rule.validate()
        except pbx.PbxRouteError as error:
            raise HTTPException(status_code=error.status, detail=str(error)) from error
        if trunks.pattern_matches(rule.pattern, request.dialled):
            return {
                "matched": True,
                "rule_index": index,
                "sent": trunks.dialled_number(rule, request.dialled),
                "caller_id": rule.caller_id or None,
            }
    return {"matched": False, "rule_index": None, "sent": None, "caller_id": None}


# ------------------------------------------- AI calls through the PBX


class AiOutboundRequest(BaseModel):
    mode: Literal["routes", "trunk"]
    trunk_id: int | None = None
    number_format: Literal["as_is", "international_00", "national"] = "as_is"
    country_code: str = Field(default="", max_length=4)
    national_prefix: str = Field(default="", max_length=3)
    caller_id: str | None = Field(default=None, max_length=24)


@router.get("/ai-outbound")
async def read_ai_outbound(user: UserModel = Depends(get_user)) -> dict[str, Any]:
    """How AI agents' outgoing calls leave the PBX."""
    return await _call(outbound.read_settings(_org(user)))


@router.put("/ai-outbound")
async def save_ai_outbound(
    request: AiOutboundRequest, user: UserModel = Depends(get_user)
) -> dict[str, Any]:
    return await _call(outbound.configure(_org(user), **request.model_dump()))


# ---------------------------------------------------- call restrictions


class RestrictionRequest(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    mode: Literal["allow", "deny"] = "deny"
    patterns: list[str] = Field(min_length=1, max_length=50)
    user_ids: list[int] = Field(default_factory=list, max_length=500)
    pin: str = Field(default="", max_length=40)
    description: str = Field(default="", max_length=255)


class RestrictionUsersRequest(BaseModel):
    user_ids: list[int] = Field(default_factory=list, max_length=500)


@router.get("/restrictions")
async def list_restrictions(user: UserModel = Depends(get_user)) -> dict[str, Any]:
    return {
        "restrictions": await _call(permissions.list_restrictions(_org(user))),
        "presets": permissions.PRESETS,
    }


@router.post("/restrictions", status_code=201)
async def create_restriction(
    request: RestrictionRequest, user: UserModel = Depends(get_user)
) -> dict[str, Any]:
    return await _call(
        permissions.create_restriction(
            _org(user), permissions.NewRestriction(**request.model_dump())
        )
    )


@router.put("/restrictions/{permission_id}/users")
async def set_restriction_users(
    permission_id: int,
    request: RestrictionUsersRequest,
    user: UserModel = Depends(get_user),
) -> dict[str, Any]:
    return await _call(
        permissions.set_restriction_users(_org(user), permission_id, request.user_ids)
    )


@router.delete("/restrictions/{permission_id}", status_code=204)
async def delete_restriction(permission_id: int, user: UserModel = Depends(get_user)):
    await _call(permissions.delete_restriction(_org(user), permission_id))
    return Response(status_code=204)


# ------------------------------------------------------ call groups


class GroupRequest(BaseModel):
    label: str = Field(min_length=1, max_length=128)
    extension: str = Field(min_length=2, max_length=10)
    strategy: str = "all"
    ring_seconds: int = Field(default=20, ge=5, le=120)
    user_uuids: list[str] = Field(default_factory=list, max_length=200)
    fallback: ivr.MenuAction | None = None


class GroupMembersRequest(BaseModel):
    user_uuids: list[str] = Field(default_factory=list, max_length=200)


class FallbackRequest(BaseModel):
    fallback: ivr.MenuAction | None = None


@router.get("/groups")
async def list_groups(user: UserModel = Depends(get_user)) -> dict[str, Any]:
    return {
        "groups": await _call(groups.list_groups(_org(user))),
        "strategies": groups.RING_STRATEGIES,
    }


@router.post("/groups", status_code=201)
async def create_group(
    request: GroupRequest, user: UserModel = Depends(get_user)
) -> dict[str, Any]:
    return await _call(
        groups.create_group(
            _org(user),
            groups.NewGroup(
                **request.model_dump(exclude={"fallback"}), fallback=request.fallback
            ),
        )
    )


@router.put("/groups/{group_uuid}/members", status_code=204)
async def set_group_members(
    group_uuid: str, request: GroupMembersRequest, user: UserModel = Depends(get_user)
):
    await _call(groups.set_group_members(_org(user), group_uuid, request.user_uuids))
    return Response(status_code=204)


@router.put("/groups/{group_uuid}/fallback", status_code=204)
async def set_group_fallback(
    group_uuid: str, request: FallbackRequest, user: UserModel = Depends(get_user)
):
    """Nobody answers in the group → this destination (AI agent included)."""
    await _call(groups.set_group_fallback(_org(user), group_uuid, request.fallback))
    return Response(status_code=204)


@router.delete("/groups/{group_uuid}", status_code=204)
async def delete_group(group_uuid: str, user: UserModel = Depends(get_user)):
    await _call(groups.delete_group(_org(user), group_uuid))
    return Response(status_code=204)


# ------------------------------------- forwards, do-not-disturb, no answer


@router.get("/extensions/{user_id}/call-settings")
async def read_call_settings(
    user_id: int, user: UserModel = Depends(get_user)
) -> dict[str, Any]:
    return await _call(forwards.read_user_settings(_org(user), user_id))


@router.put("/extensions/{user_id}/call-settings")
async def save_call_settings(
    user_id: int,
    request: forwards.UserCallSettings,
    user: UserModel = Depends(get_user),
) -> dict[str, Any]:
    """Forwards, do-not-disturb, and where unanswered calls go."""
    return await _call(forwards.save_user_settings(_org(user), user_id, request))


# --------------------------------------------- pickup, parking, intercom


class PickupGroupRequest(BaseModel):
    name: str = Field(max_length=128)
    members: list[str] = Field(
        description="Extensions (user uuids) that pick up each other's calls"
    )


@router.get("/pickup-groups")
async def list_pickup_groups(
    user: UserModel = Depends(get_user),
) -> list[dict[str, Any]]:
    """Call pickup groups: members pick up a call ringing on a colleague's phone with *8."""
    return await _call(teamwork.list_pickup_groups(_org(user)))


@router.post("/pickup-groups", status_code=201)
async def create_pickup_group(
    request: PickupGroupRequest, user: UserModel = Depends(get_user)
) -> dict[str, Any]:
    return await _call(
        teamwork.create_pickup_group(
            _org(user), teamwork.NewPickupGroup(**request.model_dump())
        )
    )


@router.delete("/pickup-groups/{group_id}", status_code=204)
async def delete_pickup_group(group_id: int, user: UserModel = Depends(get_user)):
    await _call(teamwork.delete_pickup_group(_org(user), group_id))


class ParkingLotRequest(BaseModel):
    name: str = Field(default="", max_length=128)
    extension: str = Field(description="Number calls are transferred to, to park them")
    slots_start: str
    slots_end: str
    timeout: int = Field(
        default=45, description="Seconds before a parked call rings back"
    )


@router.get("/parking-lots")
async def list_parking_lots(
    user: UserModel = Depends(get_user),
) -> list[dict[str, Any]]:
    return await _call(teamwork.list_parking_lots(_org(user)))


@router.post("/parking-lots", status_code=201)
async def create_parking_lot(
    request: ParkingLotRequest, user: UserModel = Depends(get_user)
) -> dict[str, Any]:
    return await _call(
        teamwork.create_parking_lot(
            _org(user), teamwork.NewParkingLot(**request.model_dump())
        )
    )


@router.get("/parked-calls")
async def list_parked_calls(
    user: UserModel = Depends(get_user),
) -> list[dict[str, Any]]:
    """Calls waiting in the company's parking lots, with the slot to dial."""
    return await _call(teamwork.organization_parked_calls(_org(user)))


@router.delete("/parking-lots/{lot_id}", status_code=204)
async def delete_parking_lot(lot_id: int, user: UserModel = Depends(get_user)):
    await _call(teamwork.delete_parking_lot(_org(user), lot_id))


class PagingRequest(BaseModel):
    name: str = Field(max_length=128)
    number: str = Field(description="Dialled after *11")
    members: list[str] = Field(
        description="Extensions (user uuids) whose phones answer by themselves"
    )
    callers: list[str] = Field(
        default_factory=list, description="Who may call it; empty = everyone"
    )
    duplex: bool = Field(
        default=True, description="Both ways (intercom) or one way (announcement)"
    )


@router.get("/pagings")
async def list_pagings(user: UserModel = Depends(get_user)) -> list[dict[str, Any]]:
    """Intercoms and announcements: *11 + number rings phones that answer by themselves."""
    return await _call(teamwork.list_pagings(_org(user)))


@router.post("/pagings", status_code=201)
async def create_paging(
    request: PagingRequest, user: UserModel = Depends(get_user)
) -> dict[str, Any]:
    return await _call(
        teamwork.create_paging(_org(user), teamwork.NewPaging(**request.model_dump()))
    )


@router.delete("/pagings/{paging_id}", status_code=204)
async def delete_paging(paging_id: int, user: UserModel = Depends(get_user)):
    await _call(teamwork.delete_paging(_org(user), paging_id))


class OutboundHoursRequest(BaseModel):
    opening_hours_only: bool = Field(
        description="Outgoing calls only during the opening hours of « Mon entreprise »"
    )


@router.put("/outbound-routes/{outcall_id}/hours")
async def set_outbound_route_hours(
    outcall_id: int, request: OutboundHoursRequest, user: UserModel = Depends(get_user)
) -> dict[str, Any]:
    """Outside the opening hours, outgoing calls through this route are refused."""
    return await _call(
        teamwork.set_outbound_route_hours(
            _org(user), outcall_id, request.opening_hours_only
        )
    )


# ------------------------------------------------------ conferences


class ConferenceRequest(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    extension: str = Field(min_length=2, max_length=10)
    pin: str = Field(default="", max_length=12)
    admin_pin: str = Field(default="", max_length=12)
    max_users: int = Field(default=0, ge=0, le=500)
    record: bool = False
    announce_join_leave: bool = True
    announce_user_count: bool = True


@router.get("/conferences")
async def list_conferences(user: UserModel = Depends(get_user)) -> dict[str, Any]:
    """Rooms with the people in them right now."""
    return await _call(conferences.list_conferences(_org(user)))


@router.post("/conferences", status_code=201)
async def create_conference(
    request: ConferenceRequest, user: UserModel = Depends(get_user)
) -> dict[str, Any]:
    return await _call(
        conferences.create_conference(
            _org(user), conferences.NewConference(**request.model_dump())
        )
    )


@router.delete("/conferences/{conference_id}", status_code=204)
async def delete_conference(conference_id: int, user: UserModel = Depends(get_user)):
    await _call(conferences.delete_conference(_org(user), conference_id))
    return Response(status_code=204)


@router.post(
    "/conferences/{conference_id}/participants/{participant_id}/{action}",
    status_code=204,
)
async def conference_participant_action(
    conference_id: int,
    participant_id: str,
    action: Literal["mute", "unmute", "kick"],
    user: UserModel = Depends(get_user),
):
    await _call(
        conferences.participant_action(
            _org(user), conference_id, participant_id, action
        )
    )
    return Response(status_code=204)


# ------------------------------------------------- human call recordings


@router.get("/recordings")
async def list_recordings(
    search: str | None = None,
    limit: int = 50,
    offset: int = 0,
    user: UserModel = Depends(get_user),
) -> dict[str, Any]:
    """Human calls recorded on the PBX and kept by the platform."""
    organization_id = _org(user)
    connection = await db_client.get_pbx_connection(organization_id)
    if connection is None:
        raise HTTPException(status_code=404, detail="Aucun PBX connecté")
    rows, total = await db_client.list_pbx_recordings(
        organization_id,
        search=(search or "").strip()[:64] or None,
        limit=max(1, min(limit, 200)),
        offset=max(0, offset),
    )
    return {
        "items": [recordings.serialize(r) for r in rows],
        "total": total,
        "policy": recordings.policy_of(connection).model_dump(),
        "synced_at": connection.recordings_synced_at,
    }


@router.put("/recordings/policy")
async def save_recording_policy(
    request: recordings.RecordingPolicy, user: UserModel = Depends(get_user)
) -> dict[str, Any]:
    """What is recorded on the extensions, and what the platform keeps."""
    return await _call(recordings.save_policy(_org(user), request))


@router.post("/recordings/sync")
async def sync_recordings(user: UserModel = Depends(get_user)) -> dict[str, int]:
    return await _call(recordings.sync_recordings(_org(user)))


@router.get("/recordings/{recording_id}/audio")
async def recording_audio(
    recording_id: int, user: UserModel = Depends(get_user)
) -> dict[str, str]:
    """A short-lived link to listen to the recording."""
    return {"url": await _call(recordings.audio_url(_org(user), recording_id))}


@router.delete("/recordings/{recording_id}", status_code=204)
async def delete_recording(recording_id: int, user: UserModel = Depends(get_user)):
    if not await recordings.delete_recording(_org(user), recording_id):
        raise HTTPException(status_code=404, detail="Enregistrement introuvable")
    return Response(status_code=204)


# ------------------------------------------------------ NIMBORA Softphone


class SoftphoneSettingsRequest(BaseModel):
    wss_url: str = Field(default="", max_length=512)
    sip_domain: str = Field(default="", max_length=253)


@router.post("/extensions/{user_uuid}/softphone", status_code=201)
async def create_softphone_activation(
    user_uuid: str, user: UserModel = Depends(get_user)
) -> dict[str, Any]:
    """A one-time code (and QR link) to pair NIMBORA Softphone with this extension."""
    return await _call(
        softphone.create_activation(_org(user), user_uuid, created_by=user.id)
    )


@router.get("/softphone/devices")
async def list_softphone_devices(
    user: UserModel = Depends(get_user),
) -> list[dict[str, Any]]:
    return await _call(softphone.list_devices(_org(user)))


@router.delete("/softphone/devices/{device_id}", status_code=204)
async def revoke_softphone_device(device_id: int, user: UserModel = Depends(get_user)):
    if not await db_client.revoke_softphone_device(_org(user), device_id):
        raise HTTPException(status_code=404, detail="Appareil introuvable")
    return Response(status_code=204)


@router.get("/softphone/settings")
async def read_softphone_settings(
    user: UserModel = Depends(get_user),
) -> dict[str, Any]:
    connection = await db_client.get_pbx_connection(_org(user))
    if connection is None:
        raise HTTPException(status_code=404, detail="Aucun PBX connecté")
    return {
        **softphone._transport(connection),
        "overrides": connection.softphone_settings or {},
    }


@router.put("/softphone/settings")
async def save_softphone_settings(
    request: SoftphoneSettingsRequest, user: UserModel = Depends(get_user)
) -> dict[str, Any]:
    """Where apps reach the PBX (when it is not the default address)."""
    wss = request.wss_url.strip()
    if wss and not wss.startswith("wss://"):
        raise HTTPException(
            status_code=422, detail="L'adresse doit commencer par wss://"
        )
    domain = request.sip_domain.strip().lower()
    if domain and not re.fullmatch(r"[a-z0-9.-]{1,253}", domain):
        raise HTTPException(status_code=422, detail="Domaine SIP invalide")
    organization_id = _org(user)
    if await db_client.get_pbx_connection(organization_id) is None:
        raise HTTPException(status_code=404, detail="Aucun PBX connecté")
    connection = await db_client.save_pbx_connection(
        organization_id,
        {
            "softphone_settings": {
                k: v for k, v in {"wss_url": wss, "sip_domain": domain}.items() if v
            }
        },
    )
    return {
        **softphone._transport(connection),
        "overrides": connection.softphone_settings,
    }


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
