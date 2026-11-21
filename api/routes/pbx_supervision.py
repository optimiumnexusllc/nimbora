"""Supervision of the enterprise PBX: live queues, listening, statistics."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from api.db.models import UserModel
from api.routes.pbx import _call, _org
from api.services.auth.depends import get_user
from api.services.pbx import supervision

router = APIRouter(prefix="/pbx/supervision", tags=["pbx"])


@router.get("/live")
async def read_live(user: UserModel = Depends(get_user)) -> dict[str, Any]:
    """Queues with waiting callers, agents and conversations right now."""
    return await _call(supervision.live(_org(user)))


class SpyRequest(BaseModel):
    supervisor_user_uuid: str = Field(min_length=1, max_length=64)
    target_user_uuid: str = Field(min_length=1, max_length=64)
    mode: Literal["listen", "whisper", "barge"] = "listen"


@router.post("/spy")
async def spy(
    request: SpyRequest, user: UserModel = Depends(get_user)
) -> dict[str, Any]:
    """Listen to, whisper to or barge into a call: the supervisor's phone rings."""
    return await _call(
        supervision.start_spy(
            _org(user),
            supervisor_user_uuid=request.supervisor_user_uuid,
            target_user_uuid=request.target_user_uuid,
            mode=request.mode,
            requested_by_user_id=user.id,
        )
    )


@router.get("/sessions")
async def list_sessions(user: UserModel = Depends(get_user)) -> dict[str, Any]:
    """Log of listening sessions (who listened to whom, when, how)."""
    return {"sessions": await _call(supervision.list_sessions(_org(user)))}


class SupervisionSettings(BaseModel):
    enabled: bool = False
    modes: list[Literal["listen", "whisper", "barge"]] = Field(
        default_factory=lambda: list(supervision.MODES)
    )
    supervisors: list[str] = Field(default_factory=list, max_length=500)
    protected: list[str] = Field(default_factory=list, max_length=500)
    notice_acknowledged: bool = False
    sla_seconds: int = Field(default=supervision.DEFAULT_SLA_SECONDS, ge=5, le=600)


@router.get("/settings")
async def read_settings(user: UserModel = Depends(get_user)) -> dict[str, Any]:
    from api.services.pbx.service import _connection

    connection = await _call(_connection(_org(user)))
    settings = supervision.read_settings(connection)
    extensions = await _call(supervision.extensions(_org(user)))
    wanted = (user.email or "").strip().lower()
    mine = next(
        (e["uuid"] for e in extensions if wanted and e.pop("email", None) == wanted),
        None,
    )
    for extension in extensions:
        extension.pop("email", None)
    return {**settings, "my_extension": mine, "extensions": extensions}


@router.put("/settings")
async def save_settings(
    request: SupervisionSettings, user: UserModel = Depends(get_user)
) -> dict[str, Any]:
    return await _call(supervision.save_settings(_org(user), request.model_dump()))


@router.get("/statistics")
async def read_statistics(
    period: Literal["today", "yesterday", "7d", "30d"] = Query("today"),
    user: UserModel = Depends(get_user),
) -> dict[str, Any]:
    """Queue and agent statistics (answered rate, wait, service level)."""
    return await _call(supervision.statistics(_org(user), period))


# ------------------------------------------------------------------ alerts


class AlertSettings(BaseModel):
    enabled: bool = False
    max_wait_seconds: int = Field(default=120, ge=10, le=3600)
    max_waiting: int = Field(default=5, ge=1, le=200)
    no_agent: bool = True
    queue_ids: list[int] = Field(default_factory=list, max_length=200)
    webhook_url: str = Field(default="", max_length=500)
    email_tool_uuid: str | None = Field(default=None, max_length=64)
    email_recipients: list[str] = Field(default_factory=list, max_length=20)
    cooldown_minutes: int = Field(default=15, ge=1, le=1440)


async def _email_tools(organization_id: int) -> list[dict[str, Any]]:
    from api.db import db_client

    tools = await db_client.get_tools_for_organization(
        organization_id, category="send_message"
    )
    return [
        {"uuid": str(t.tool_uuid), "name": t.name}
        for t in tools
        if ((t.definition or {}).get("config") or {}).get("channel") == "email"
        and ((t.definition or {}).get("config") or {}).get("provider") == "smtp"
    ]


@router.get("/alerts")
async def read_alerts(user: UserModel = Depends(get_user)) -> dict[str, Any]:
    """Alert rules and channels, the company's e-mail tools, the latest alerts."""
    from api.services.pbx import alerts
    from api.services.pbx.service import _connection

    connection = await _call(_connection(_org(user)))
    return {
        "settings": alerts.read_settings(connection),
        "email_tools": await _email_tools(_org(user)),
        "log": await alerts.recent_log(_org(user)),
    }


@router.put("/alerts")
async def save_alerts(
    request: AlertSettings, user: UserModel = Depends(get_user)
) -> dict[str, Any]:
    from api.services.pbx import alerts

    settings = await _call(alerts.save_settings(_org(user), request.model_dump()))
    supervision.invalidate(_org(user))
    return {"settings": settings}


@router.post("/alerts/test")
async def test_alerts(user: UserModel = Depends(get_user)) -> dict[str, Any]:
    """Send a test message on the configured channels."""
    from api.services.pbx import alerts
    from api.services.pbx.service import _connection

    connection = await _call(_connection(_org(user)))
    settings = alerts.read_settings(connection)
    if not settings["webhook_url"] and not settings["email_recipients"]:
        from fastapi import HTTPException

        raise HTTPException(
            status_code=422,
            detail="Configurez d'abord un webhook ou des destinataires.",
        )
    outcome = await alerts.notify(
        _org(user),
        settings,
        "🔔 Test des alertes de supervision : ce canal recevra les alertes de vos files.",
        {"event": "test"},
    )
    return {"channels": outcome}
