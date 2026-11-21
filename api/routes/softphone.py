"""NIMBORA Softphone API, used by the apps (Windows, macOS, Linux, Android,
iOS, browser). Authenticated by the device token obtained at pairing."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Header, HTTPException, Request, Response
from pydantic import BaseModel, Field

from api.services.pbx import softphone
from api.services.pbx.client import PbxError
from api.services.pbx.service import PbxNotConfigured, PbxRouteError

router = APIRouter(prefix="/softphone", tags=["softphone"])


class ActivateRequest(BaseModel):
    code: str = Field(min_length=4, max_length=20)
    device_name: str = Field(default="Softphone", max_length=128)
    platform: Literal["windows", "macos", "linux", "android", "ios", "web"] = "web"
    app_version: str | None = Field(default=None, max_length=32)


class StatusRequest(BaseModel):
    dnd: bool = False
    forward_enabled: bool = False
    forward_to: str = Field(default="", max_length=40)


def _token(authorization: str | None) -> str | None:
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return None


async def _device(authorization: str | None, app_version: str | None = None):
    try:
        device = await softphone.device_for_token(_token(authorization))
    except softphone.SoftphoneAuthError as error:
        raise HTTPException(status_code=401, detail=str(error)) from error
    await softphone.touch(device, app_version)
    return device


async def _call(coro):
    try:
        return await coro
    except PbxNotConfigured as error:
        raise HTTPException(status_code=404, detail="Aucun PBX connecté") from error
    except PbxRouteError as error:
        raise HTTPException(status_code=error.status, detail=str(error)) from error
    except PbxError as error:
        raise HTTPException(status_code=502, detail=f"PBX : {error}") from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.post("/activate")
async def activate(request: ActivateRequest, http: Request) -> dict[str, Any]:
    """Pair an app with the one-time code shown in the console."""
    client_key = http.client.host if http.client else "unknown"
    try:
        return await _call(
            softphone.activate(
                request.code,
                device_name=request.device_name,
                platform=request.platform,
                app_version=request.app_version,
                client_key=client_key,
            )
        )
    except softphone.SoftphoneAuthError as error:
        raise HTTPException(status_code=401, detail=str(error)) from error


@router.get("/config")
async def config(
    authorization: str | None = Header(default=None),
    x_app_version: str | None = Header(default=None),
) -> dict[str, Any]:
    """SIP account (read live from the PBX), transport, ICE servers, brand."""
    device = await _device(authorization, x_app_version)
    return await _call(softphone.device_config(device))


@router.get("/directory")
async def directory(authorization: str | None = Header(default=None)) -> dict[str, Any]:
    device = await _device(authorization)
    return await _call(softphone.directory(device))


@router.get("/history")
async def history(
    limit: int = 50, authorization: str | None = Header(default=None)
) -> list[dict[str, Any]]:
    device = await _device(authorization)
    return await _call(softphone.history(device, limit=limit))


@router.get("/status")
async def read_status(
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    device = await _device(authorization)
    return await _call(softphone.read_status(device))


@router.put("/status")
async def save_status(
    request: StatusRequest, authorization: str | None = Header(default=None)
) -> dict[str, Any]:
    """Do-not-disturb and "forward all my calls"."""
    device = await _device(authorization)
    return await _call(
        softphone.save_status(
            device,
            dnd=request.dnd,
            forward_enabled=request.forward_enabled,
            forward_to=request.forward_to,
        )
    )


@router.delete("/device", status_code=204)
async def sign_out(authorization: str | None = Header(default=None)):
    """Unpair this app (its token stops working at once)."""
    from api.db import db_client

    device = await _device(authorization)
    await db_client.revoke_softphone_device(device.organization_id, device.id)
    return Response(status_code=204)
