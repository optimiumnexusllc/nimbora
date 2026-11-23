"""NIMBORA Softphone: pairing apps with PBX extensions, and what they need.

The app (Windows, macOS, Linux, Android, iOS, or the browser) is paired once
with a one-time activation code shown in the console (also as a QR code and
a ``nimbora-softphone://`` link). Pairing returns a device token; the app
then fetches its configuration with it on every start:

* the extension's SIP account (WebRTC line) — read live from the PBX, never
  stored by the platform;
* the PBX's secure WebSocket address, the SIP domain, STUN/TURN servers;
* the brand (white label), the colleagues' directory, recent calls,
  do-not-disturb and forwarding.

Devices can be revoked one by one, or all at once for an extension (when an
employee leaves, or the extension is deleted).
"""

from __future__ import annotations

import hashlib
import re
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import quote, urlparse

from loguru import logger

from api.services.branding import brand
from api.services.pbx.client import PbxClient, PbxError
from api.services.pbx.service import PbxRouteError, _connection, client_for

ACTIVATION_TTL = timedelta(minutes=15)
# No 0/O, 1/I/L: codes are read aloud and typed on phones.
CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
CODE_LENGTH = 8
TOKEN_PREFIX = "nsp_"
MAX_ATTEMPTS = 10
ATTEMPT_WINDOW_SECONDS = 600
PLATFORMS = {"windows", "macos", "linux", "android", "ios", "web"}
APP_SCHEME = "nimbora-softphone"
VOICEMAIL_CODE = "*98"


class SoftphoneAuthError(Exception):
    """Unknown, revoked or malformed device token / activation code."""


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def normalize_code(code: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", (code or "").upper())


def new_code() -> str:
    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))


def format_code(code: str) -> str:
    return f"{code[:4]}-{code[4:]}"


def new_token() -> str:
    return TOKEN_PREFIX + secrets.token_urlsafe(32)


# ---------------------------------------------------------- SIP account


def _webrtc_capable(endpoint: dict, tenant: dict | None) -> bool:
    templates = {t.get("uuid") for t in endpoint.get("templates") or []}
    labels = {
        str(t.get("label") or "").lower() for t in endpoint.get("templates") or []
    }
    if tenant and tenant.get("webrtc_sip_template_uuid") in templates:
        return True
    if "webrtc" in labels:
        return True
    options = dict(endpoint.get("endpoint_section_options") or [])
    return str(options.get("webrtc", "")).lower() in {"yes", "true", "1"}


async def _repair_line(client: PbxClient, endpoint: dict[str, Any]) -> None:
    """A browser line made before the fix of bug 23 cannot ring: the app that
    reads its account repairs it. Best effort: an older service account
    without the update right only logs it."""
    from api.services.pbx import endpoints

    fixed = endpoints.repair_templates(endpoint)
    if fixed is None:
        return
    try:
        await client.update_endpoint_sip(
            endpoint["uuid"], endpoints.endpoint_body(endpoint, fixed)
        )
        logger.info(
            f"Softphone: browser line {endpoint.get('name')} repaired (webrtc template alone)"
        )
    except PbxError as error:
        logger.warning(
            f"Softphone: browser line {endpoint.get('name')} not repaired: {error}"
        )


async def sip_account(client: PbxClient, connection, user_uuid: str) -> dict[str, Any]:
    """The extension's WebRTC SIP account, read live from the PBX."""
    user = await client.user(user_uuid)
    lines = user.get("lines") or []
    tenant = None
    if connection.tenant_uuid:
        try:
            tenant = await client.tenant(connection.tenant_uuid)
        except PbxError:
            tenant = None
    for line in lines:
        sip = line.get("endpoint_sip") or {}
        if not sip.get("uuid"):
            continue
        endpoint = await client.endpoint_sip(sip["uuid"])
        if not _webrtc_capable(endpoint, tenant):
            continue
        await _repair_line(client, endpoint)
        auth = dict(endpoint.get("auth_section_options") or [])
        if not auth.get("username") or not auth.get("password"):
            continue
        extensions = line.get("extensions") or []
        return {
            # The engine identifies the endpoint by the SIP user of the request
            # (its name, `identify_by = username`); the auth username only
            # answers the challenge. Both differ on NIMBORA-managed lines.
            "sip_identity": endpoint.get("name") or auth["username"],
            "username": auth["username"],
            "password": auth["password"],
            "extension": (extensions[0].get("exten") if extensions else None)
            or user.get("extension"),
            "display_name": " ".join(
                p for p in (user.get("firstname"), user.get("lastname")) if p
            ).strip()
            or auth["username"],
        }
    raise PbxRouteError(
        "Ce poste n'a pas de ligne navigateur (WebRTC) : recréez-le avec une "
        "ligne « navigateur » pour utiliser le softphone.",
        409,
    )


def _transport(connection) -> dict[str, str]:
    settings = connection.softphone_settings or {}
    host = urlparse(connection.base_url).hostname or ""
    return {
        "wss_url": settings.get("wss_url") or f"wss://{host}/api/asterisk/ws",
        "sip_domain": settings.get("sip_domain") or host,
    }


def _ice_servers(device_key: str) -> list[dict[str, Any]]:
    from api.constants import (
        ENABLE_COTURN,
        FORCE_TURN_RELAY,
        TURN_HOST,
        TURN_PORT,
        TURN_SECRET,
    )

    servers: list[dict[str, Any]] = []
    if not FORCE_TURN_RELAY:
        servers.append({"urls": ["stun:stun.l.google.com:19302"]})
    if ENABLE_COTURN and TURN_HOST and TURN_SECRET:
        from api.routes.turn_credentials import generate_turn_credentials

        creds = generate_turn_credentials(f"softphone-{device_key}")
        servers.append(
            {
                "urls": [
                    f"turn:{TURN_HOST}:{TURN_PORT}?transport=udp",
                    f"turn:{TURN_HOST}:{TURN_PORT}?transport=tcp",
                ],
                "username": creds["username"],
                "credential": creds["password"],
            }
        )
    return servers


async def device_config(device, **client_kwargs) -> dict[str, Any]:
    connection = await _connection(device.organization_id)
    async with client_for(connection, **client_kwargs) as client:
        account = await sip_account(client, connection, device.pbx_user_uuid)
    b = brand()
    return {
        "brand": {
            "name": b.name,
            "pbx_name": b.pbx_name,
            "support_email": b.support_email,
        },
        "device": {"id": device.id, "name": device.name, "platform": device.platform},
        "account": {
            "display_name": account["display_name"],
            "extension": account["extension"],
            "sip_identity": account["sip_identity"],
            "username": account["username"],
            "password": account["password"],
            **_transport(connection),
        },
        "ice_servers": _ice_servers(str(device.id)),
        "features": {"voicemail_code": VOICEMAIL_CODE, "transfer": True, "dnd": True},
    }


# ----------------------------------------------------- console (admin)


async def create_activation(
    organization_id: int, user_uuid: str, *, created_by: int | None, **client_kwargs
) -> dict[str, Any]:
    """A one-time code (and QR link) to pair an app with this extension."""
    from api.db import db_client
    from api.utils.common import get_backend_endpoints

    connection = await _connection(organization_id)
    async with client_for(connection, **client_kwargs) as client:
        account = await sip_account(client, connection, user_uuid)  # fails early
    code = new_code()
    expires_at = datetime.now(UTC) + ACTIVATION_TTL
    await db_client.create_softphone_activation(
        organization_id,
        {
            "pbx_user_uuid": user_uuid,
            "code_hash": _hash(code),
            "expires_at": expires_at,
            "created_by_user_id": created_by,
        },
    )
    try:
        server, _ = await get_backend_endpoints()
    except Exception:
        server = ""
    link = (
        f"{APP_SCHEME}://activate?server={quote(server, safe='')}&code={code}"
        if server
        else f"{APP_SCHEME}://activate?code={code}"
    )
    return {
        "code": format_code(code),
        "expires_at": expires_at.isoformat(),
        "server": server,
        "link": link,
        "display_name": account["display_name"],
        "extension": account["extension"],
    }


def serialize_device(device, names: dict[str, str] | None = None) -> dict[str, Any]:
    return {
        "id": device.id,
        "name": device.name,
        "platform": device.platform,
        "app_version": device.app_version,
        "pbx_user_uuid": device.pbx_user_uuid,
        "extension_name": (names or {}).get(device.pbx_user_uuid),
        "last_seen_at": device.last_seen_at.isoformat()
        if device.last_seen_at
        else None,
        "created_at": device.created_at.isoformat() if device.created_at else None,
    }


async def list_devices(organization_id: int, **client_kwargs) -> list[dict[str, Any]]:
    from api.db import db_client

    devices = await db_client.list_softphone_devices(organization_id)
    names: dict[str, str] = {}
    if devices:
        try:
            connection = await _connection(organization_id)
            async with client_for(connection, **client_kwargs) as client:
                for user in await client.users():
                    names[user.get("uuid")] = " ".join(
                        p for p in (user.get("firstname"), user.get("lastname")) if p
                    ).strip() + (
                        f" ({user['extension']})" if user.get("extension") else ""
                    )
        except PbxError:
            logger.opt(exception=True).warning("Extension names unavailable")
    return [serialize_device(d, names) for d in devices]


# ------------------------------------------------------ app (device)


async def _too_many_attempts(client_key: str) -> bool:
    from api.services.supervision.live_calls import get_redis

    try:
        redis = await get_redis()
        key = f"nimbora:softphone:activation:{client_key}"
        attempts = await redis.incr(key)
        if attempts == 1:
            await redis.expire(key, ATTEMPT_WINDOW_SECONDS)
        return attempts > MAX_ATTEMPTS
    except Exception:
        logger.opt(exception=True).warning("Activation throttle unavailable")
        return False


async def activate(
    code: str,
    *,
    device_name: str,
    platform: str,
    app_version: str | None,
    client_key: str,
    **client_kwargs,
) -> dict[str, Any]:
    """Pair an app: one-time code → long-lived device token + configuration."""
    from api.db import db_client

    if await _too_many_attempts(client_key):
        raise SoftphoneAuthError("Trop d'essais : réessayez dans 10 minutes.")
    normalized = normalize_code(code)
    if len(normalized) != CODE_LENGTH:
        raise SoftphoneAuthError("Code d'activation invalide ou expiré")
    activation = await db_client.consume_softphone_activation(_hash(normalized))
    if activation is None:
        raise SoftphoneAuthError("Code d'activation invalide ou expiré")
    token = new_token()
    device = await db_client.create_softphone_device(
        activation.organization_id,
        {
            "pbx_user_uuid": activation.pbx_user_uuid,
            "name": (device_name or "Softphone").strip()[:128] or "Softphone",
            "platform": platform if platform in PLATFORMS else "web",
            "app_version": (app_version or None) and app_version[:32],
            "token_hash": _hash(token),
        },
    )
    return {"token": token, "config": await device_config(device, **client_kwargs)}


async def device_for_token(token: str | None):
    from api.db import db_client

    if not token or not token.startswith(TOKEN_PREFIX):
        raise SoftphoneAuthError("Appareil non reconnu")
    device = await db_client.get_softphone_device_by_token(_hash(token))
    if device is None:
        raise SoftphoneAuthError("Appareil non reconnu ou révoqué")
    return device


async def touch(device, app_version: str | None = None) -> None:
    from api.db import db_client

    fields = {"app_version": app_version[:32]} if app_version else {}
    await db_client.touch_softphone_device(device.organization_id, device.id, fields)


async def directory(device, query: str = "", **client_kwargs) -> dict[str, Any]:
    """The unified directory of an employee: colleagues with their presence,
    groups and queues of the PBX, and the company's customers (customer
    memory, when it is on). ``query`` narrows the customers (name or number);
    colleagues and services are filtered by the app."""
    from api.services.pbx.presence import presence_of, team_presence

    connection = await _connection(device.organization_id)
    async with client_for(connection, **client_kwargs) as client:
        users = await client.users()
        try:
            groups = await client.groups()
        except PbxError:
            groups = []
        try:
            queues = await client.queues()
        except PbxError:
            queues = []
        presence, live = await team_presence(client)
    people = [
        {
            "name": " ".join(
                p for p in (u.get("firstname"), u.get("lastname")) if p
            ).strip()
            or u.get("email")
            or u.get("extension"),
            "extension": u.get("extension"),
            "me": u.get("uuid") == device.pbx_user_uuid,
            "presence": presence_of(presence, u.get("uuid"), live),
        }
        for u in users
        if u.get("extension")
    ]
    services = [
        {
            "name": g.get("label") or g.get("name"),
            "extension": e.get("exten"),
            "kind": "group",
        }
        for g in groups
        for e in (g.get("extensions") or [])[:1]
    ] + [
        {
            "name": q.get("label") or q.get("name"),
            "extension": e.get("exten"),
            "kind": "queue",
        }
        for q in queues
        for e in (q.get("extensions") or [])[:1]
    ]
    return {
        "people": sorted(people, key=lambda p: (p["name"] or "").lower()),
        "services": services,
        "customers": await directory_customers(device.organization_id, query),
        "presence_live": live,
    }


async def directory_customers(
    organization_id: int, query: str = "", limit: int = 30
) -> list[dict[str, Any]] | None:
    """Customers from customer memory, most recent first. None when the
    company does not remember its callers."""
    from api.db import db_client
    from api.services.customer_memory.service import is_memory_enabled

    if not await is_memory_enabled(organization_id):
        return None
    profiles, _ = await db_client.search_customer_profiles(
        organization_id, query=query.strip()[:64] or None, limit=limit
    )
    return [
        {
            "id": profile.id,
            "name": profile.name,
            "number": profile.phone,
            "vip": "vip" in [str(t).lower() for t in profile.tags or []],
            "advisor": ((profile.attributes or {}).get("usual_advisor") or {}).get(
                "name"
            ),
            "calls": profile.total_calls or 0,
            "last_seen_at": profile.last_seen_at.isoformat()
            if profile.last_seen_at
            else None,
        }
        for profile in profiles
    ]


async def save_presence(
    device, state: str, status: str = "", **client_kwargs
) -> dict[str, str]:
    """The employee's own presence: available, away or offline."""
    from api.services.pbx.presence import set_my_presence

    connection = await _connection(device.organization_id)
    async with client_for(connection, **client_kwargs) as client:
        return await set_my_presence(client, device.pbx_user_uuid, state, status)


async def history(device, limit: int = 50, **client_kwargs) -> list[dict[str, Any]]:
    """The extension's recent calls (from the PBX's call log)."""
    connection = await _connection(device.organization_id)
    async with client_for(connection, **client_kwargs) as client:
        user = await client.user(device.pbx_user_uuid)
        items = await client.user_cdr(
            device.pbx_user_uuid, limit=max(1, min(limit, 100))
        )
    mine = {str(user.get("extension") or "")}
    for line in user.get("lines") or []:
        for extension in line.get("extensions") or []:
            mine.add(str(extension.get("exten") or ""))
    calls = []
    for cdr in items:
        source = str(cdr.get("source_extension") or "")
        outgoing = source in mine or cdr.get("source_user_uuid") == device.pbx_user_uuid
        other_number = (
            cdr.get("destination_extension") or cdr.get("requested_extension")
            if outgoing
            else cdr.get("source_extension")
        )
        other_name = cdr.get("destination_name") if outgoing else cdr.get("source_name")
        calls.append(
            {
                "id": cdr.get("id"),
                "start": cdr.get("start"),
                "direction": "outgoing" if outgoing else "incoming",
                "answered": bool(cdr.get("answered")),
                "duration": int(float(cdr.get("duration") or 0)),
                "number": other_number,
                "name": other_name or None,
            }
        )
    return calls


async def read_status(device, **client_kwargs) -> dict[str, Any]:
    from api.services.pbx.forwards import read_user_settings

    user_id = await _user_id(device, **client_kwargs)
    settings = await read_user_settings(
        device.organization_id, user_id, **client_kwargs
    )
    return {
        "dnd": settings["dnd"],
        "forward": settings["forwards"]["unconditional"],
    }


async def save_status(
    device, *, dnd: bool, forward_enabled: bool, forward_to: str, **client_kwargs
) -> dict[str, Any]:
    """Do-not-disturb and "forward all my calls" from the app."""
    from api.services.pbx.forwards import (
        Forward,
        UserCallSettings,
        read_user_settings,
        save_user_settings,
    )

    user_id = await _user_id(device, **client_kwargs)
    current = await read_user_settings(device.organization_id, user_id, **client_kwargs)
    forwards = current["forwards"]
    settings_model = UserCallSettings(
        unconditional=Forward(enabled=forward_enabled, destination=forward_to),
        busy=Forward(**forwards["busy"]),
        noanswer=Forward(**forwards["noanswer"]),
        dnd=dnd,
        unanswered_mode="keep",
    )
    await save_user_settings(
        device.organization_id, user_id, settings_model, **client_kwargs
    )
    return await read_status(device, **client_kwargs)


async def _user_id(device, **client_kwargs) -> int:
    connection = await _connection(device.organization_id)
    async with client_for(connection, **client_kwargs) as client:
        user = await client.user(device.pbx_user_uuid)
    if user.get("id") is None:
        raise PbxRouteError("Poste introuvable", 404)
    return int(user["id"])
