"""Client for the enterprise PBX engine (Wazo Platform REST APIs).

The engine is presented to users under the platform brand only; this module is
the one place that speaks its APIs. Every service is reached through the
engine's HTTPS gateway (``https://<host>/api/<service>/<version>``) with a
token from its auth service, scoped to one tenant with the ``Wazo-Tenant``
header.

Contracts follow the engine's published OpenAPI specifications (auth 0.1,
confd 1.1, calld/agentd/webhookd/call-logd/chatd 1.0).
"""

from __future__ import annotations

import asyncio
import hashlib
import time
from dataclasses import dataclass
from typing import Any

import httpx

SERVICES: dict[str, str] = {
    "auth": "/api/auth/0.1",
    "confd": "/api/confd/1.1",
    "calld": "/api/calld/1.0",
    "agentd": "/api/agentd/1.0",
    "webhookd": "/api/webhookd/1.0",
    "call_logd": "/api/call-logd/1.0",
    "chatd": "/api/chatd/1.0",
    "amid": "/api/amid/1.0",
}
TENANT_HEADER = "Wazo-Tenant"
TOKEN_HEADER = "X-Auth-Token"
TOKEN_LIFETIME = 3600
TOKEN_MARGIN = 120


class PbxError(Exception):
    """The PBX answered with an error, or could not be reached."""

    def __init__(self, message: str, *, status: int | None = None):
        super().__init__(message)
        self.status = status


class PbxAuthError(PbxError):
    """Wrong credentials, or a token the PBX no longer accepts."""


class PbxUnavailable(PbxError):
    """Network error, timeout, TLS failure."""


@dataclass(frozen=True)
class PbxSettings:
    base_url: str
    username: str
    password: str
    tenant_uuid: str | None = None
    verify_tls: bool = True

    @property
    def root(self) -> str:
        return self.base_url.rstrip("/")

    def cache_key(self) -> str:
        digest = hashlib.sha256(self.password.encode()).hexdigest()[:16]
        return f"{self.root}|{self.username}|{digest}"


# Tokens are shared by every client of the process for the same account.
_TOKENS: dict[str, tuple[str, float]] = {}
_TOKEN_LOCKS: dict[str, asyncio.Lock] = {}


def _error_message(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return response.text[:200] or f"HTTP {response.status_code}"
    if isinstance(body, dict):
        message = body.get("message") or body.get("reason") or body.get("error")
        if isinstance(message, list):
            message = "; ".join(str(m) for m in message)
        details = body.get("details")
        if message and details:
            return f"{message} ({details})"[:400]
        if message:
            return str(message)[:400]
    return str(body)[:400]


class PbxClient:
    def __init__(
        self,
        settings: PbxSettings,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float = 10.0,
    ):
        self.settings = settings
        self._http = httpx.AsyncClient(
            base_url=settings.root,
            verify=settings.verify_tls,
            timeout=timeout,
            transport=transport,
            headers={"Accept": "application/json"},
        )

    async def __aenter__(self) -> "PbxClient":
        return self

    async def __aexit__(self, *exc) -> None:
        await self.close()

    async def close(self) -> None:
        await self._http.aclose()

    # ------------------------------------------------------------ token

    async def _new_token(self) -> tuple[str, float]:
        try:
            response = await self._http.post(
                f"{SERVICES['auth']}/token",
                auth=(self.settings.username, self.settings.password),
                json={"expiration": TOKEN_LIFETIME},
            )
        except httpx.HTTPError as error:
            raise PbxUnavailable(
                f"PBX injoignable : {error.__class__.__name__}"
            ) from error
        if response.status_code in (401, 403):
            raise PbxAuthError(
                "Identifiants du PBX refusés", status=response.status_code
            )
        if response.status_code >= 400:
            raise PbxError(_error_message(response), status=response.status_code)
        data = (response.json() or {}).get("data") or {}
        token = data.get("token")
        if not token:
            raise PbxError("Réponse d'authentification du PBX sans jeton")
        return token, time.monotonic() + TOKEN_LIFETIME - TOKEN_MARGIN

    async def token(self, *, refresh: bool = False) -> str:
        key = self.settings.cache_key()
        lock = _TOKEN_LOCKS.setdefault(key, asyncio.Lock())
        async with lock:
            cached = _TOKENS.get(key)
            if cached and not refresh and cached[1] > time.monotonic():
                return cached[0]
            _TOKENS[key] = await self._new_token()
            return _TOKENS[key][0]

    # ---------------------------------------------------------- request

    async def request(
        self,
        service: str,
        method: str,
        path: str,
        *,
        json: Any = None,
        params: dict[str, Any] | None = None,
        tenant: bool = True,
        content: bytes | None = None,
        content_type: str | None = None,
        raw: bool = False,
    ) -> Any:
        url = f"{SERVICES[service]}{path}"
        for attempt in (0, 1):
            headers = {TOKEN_HEADER: await self.token(refresh=attempt == 1)}
            if tenant and self.settings.tenant_uuid:
                headers[TENANT_HEADER] = self.settings.tenant_uuid
            if content_type:
                headers["Content-Type"] = content_type
            try:
                response = await self._http.request(
                    method,
                    url,
                    json=json if content is None else None,
                    content=content,
                    params=params,
                    headers=headers,
                )
            except httpx.HTTPError as error:
                raise PbxUnavailable(
                    f"PBX injoignable : {error.__class__.__name__}"
                ) from error
            if response.status_code == 401 and attempt == 0:
                continue  # token expired or revoked: one fresh try
            if response.status_code in (401, 403):
                raise PbxAuthError(
                    _error_message(response), status=response.status_code
                )
            if response.status_code >= 400:
                raise PbxError(_error_message(response), status=response.status_code)
            if raw:
                return response.content
            if response.status_code == 204 or not response.content:
                return None
            return response.json()
        raise PbxAuthError("Jeton du PBX refusé")  # pragma: no cover

    async def _items(self, service: str, path: str, **params) -> list[dict]:
        body = await self.request(service, "GET", path, params=params or None)
        if isinstance(body, dict):
            return list(body.get("items") or [])
        return list(body or [])

    # ------------------------------------------------------------- auth

    async def reset_password_with_email_token(
        self, user_uuid: str, email_token: str, password: str
    ) -> None:
        """Set a PBX user's password with the token from the reset e-mail."""
        try:
            response = await self._http.post(
                f"{SERVICES['auth']}/users/password/reset",
                params={"user_uuid": user_uuid},
                headers={TOKEN_HEADER: email_token},
                json={"password": password},
            )
        except httpx.HTTPError as error:
            raise PbxUnavailable(
                f"PBX injoignable : {error.__class__.__name__}"
            ) from error
        if response.status_code in (401, 403, 404):
            raise PbxAuthError(
                "Lien expiré ou déjà utilisé", status=response.status_code
            )
        if response.status_code >= 400:
            raise PbxError(_error_message(response), status=response.status_code)

    async def check_tenant(self, tenant_uuid: str) -> dict:
        return await self.request("auth", "GET", f"/tenants/{tenant_uuid}")

    async def create_tenant(self, name: str, slug: str | None = None) -> dict:
        body: dict[str, Any] = {"name": name}
        if slug:
            body["slug"] = slug
        return await self.request("auth", "POST", "/tenants", json=body)

    # --- operator provisioning (shared PBX: one tenant per company).
    # Used only with the operator's provisioning account, never with a
    # company's service account (see services/pbx/provisioning).

    async def tenants(self, search: str) -> list[dict]:
        return await self._items("auth", "/tenants", search=search)

    async def delete_tenant(self, tenant_uuid: str) -> None:
        await self.request("auth", "DELETE", f"/tenants/{tenant_uuid}")

    async def policies(self, search: str) -> list[dict]:
        return await self._items("auth", "/policies", search=search)

    async def create_policy(self, body: dict) -> dict:
        return await self.request("auth", "POST", "/policies", json=body)

    async def auth_users(self, search: str) -> list[dict]:
        return await self._items("auth", "/users", search=search)

    async def create_auth_user(self, body: dict) -> dict:
        return await self.request("auth", "POST", "/users", json=body)

    async def delete_auth_user(self, user_uuid: str) -> None:
        await self.request("auth", "DELETE", f"/users/{user_uuid}")

    async def set_auth_user_policy(self, user_uuid: str, policy_uuid: str) -> None:
        await self.request(
            "auth", "PUT", f"/users/{user_uuid}/policies/{policy_uuid}"
        )

    async def create_context(self, body: dict) -> dict:
        return await self.request("confd", "POST", "/contexts", json=body)

    async def update_context(self, context_id: int, body: dict) -> None:
        await self.request("confd", "PUT", f"/contexts/{context_id}", json=body)

    async def set_context_includes(self, context_id: int, included: list[int]) -> None:
        await self.request(
            "confd",
            "PUT",
            f"/contexts/{context_id}/contexts",
            json={"contexts": [{"id": i} for i in included]},
        )

    # ------------------------------------------------------------ confd

    async def infos(self) -> dict:
        return await self.request("confd", "GET", "/infos", tenant=False)

    async def users(self, limit: int = 500) -> list[dict]:
        return await self._items("confd", "/users", limit=limit, view="summary")

    async def queues(self) -> list[dict]:
        return await self._items("confd", "/queues", limit=500)

    async def agents(self) -> list[dict]:
        return await self._items("confd", "/agents", limit=500)

    async def incalls(self) -> list[dict]:
        return await self._items("confd", "/incalls", limit=500)

    async def contexts(self, context_type: str | None = None) -> list[dict]:
        # The API has no type filter: filter here.
        items = await self._items("confd", "/contexts", limit=500)
        if context_type:
            items = [c for c in items if c.get("type") == context_type]
        return items

    async def extensions(
        self, *, exten: str | None = None, context: str | None = None
    ) -> list[dict]:
        params: dict[str, Any] = {"limit": 500}
        if exten:
            params["exten"] = exten
        if context:
            params["context"] = context
        return await self._items("confd", "/extensions", **params)

    async def create_extension(self, exten: str, context: str) -> dict:
        return await self.request(
            "confd", "POST", "/extensions", json={"exten": exten, "context": context}
        )

    async def delete_extension(self, extension_id: int) -> None:
        await self.request("confd", "DELETE", f"/extensions/{extension_id}")

    async def create_incall(self, destination: dict, description: str) -> dict:
        return await self.request(
            "confd",
            "POST",
            "/incalls",
            json={"destination": destination, "description": description},
        )

    async def delete_incall(self, incall_id: int) -> None:
        await self.request("confd", "DELETE", f"/incalls/{incall_id}")

    async def associate_incall_extension(
        self, incall_id: int, extension_id: int
    ) -> None:
        await self.request(
            "confd", "PUT", f"/incalls/{incall_id}/extensions/{extension_id}"
        )

    async def pjsip_global(self) -> dict[str, str]:
        body = await self.request(
            "confd", "GET", "/asterisk/pjsip/global", tenant=False
        )
        return dict((body or {}).get("options") or {})

    async def set_pjsip_global(self, options: dict[str, str]) -> None:
        await self.request(
            "confd",
            "PUT",
            "/asterisk/pjsip/global",
            json={"options": options},
            tenant=False,
        )

    # ------------------------------------------------- administration

    async def sip_templates(self) -> list[dict]:
        return await self._items("confd", "/endpoints/sip/templates", limit=500)

    async def create_user(self, body: dict) -> dict:
        """One call creates the user with its lines, extensions, SIP account,
        voicemail and login (the PBX rolls back everything on error)."""
        return await self.request("confd", "POST", "/users", json=body)

    async def delete_user(self, user_uuid: str) -> None:
        # recursive: its lines, extensions, voicemail and login go too.
        await self.request(
            "confd", "DELETE", f"/users/{user_uuid}", params={"recursive": "true"}
        )

    async def create_agent(self, number: str, firstname: str, lastname: str) -> dict:
        return await self.request(
            "confd",
            "POST",
            "/agents",
            json={"number": number, "firstname": firstname, "lastname": lastname},
        )

    async def delete_agent(self, agent_id: int) -> None:
        await self.request("confd", "DELETE", f"/agents/{agent_id}")

    async def associate_user_agent(self, user_uuid: str, agent_id: int) -> None:
        await self.request("confd", "PUT", f"/users/{user_uuid}/agents/{agent_id}")

    async def create_queue(self, body: dict) -> dict:
        return await self.request("confd", "POST", "/queues", json=body)

    async def queue(self, queue_id: int) -> dict:
        return await self.request("confd", "GET", f"/queues/{queue_id}")

    async def update_queue(self, queue_id: int, body: dict) -> None:
        await self.request("confd", "PUT", f"/queues/{queue_id}", json=body)

    async def delete_queue(self, queue_id: int) -> None:
        await self.request("confd", "DELETE", f"/queues/{queue_id}")

    async def associate_queue_extension(self, queue_id: int, extension_id: int) -> None:
        await self.request(
            "confd", "PUT", f"/queues/{queue_id}/extensions/{extension_id}"
        )

    async def set_queue_member(
        self, queue_id: int, agent_id: int, penalty: int = 0
    ) -> None:
        await self.request(
            "confd",
            "PUT",
            f"/queues/{queue_id}/members/agents/{agent_id}",
            json={"penalty": penalty, "priority": 0},
        )

    async def remove_queue_member(self, queue_id: int, agent_id: int) -> None:
        await self.request(
            "confd", "DELETE", f"/queues/{queue_id}/members/agents/{agent_id}"
        )

    async def set_queue_fallbacks(self, queue_id: int, fallbacks: dict) -> None:
        await self.request(
            "confd", "PUT", f"/queues/{queue_id}/fallbacks", json=fallbacks
        )

    async def voicemails(self) -> list[dict]:
        return await self._items("confd", "/voicemails", limit=500)

    async def schedules(self) -> list[dict]:
        return await self._items("confd", "/schedules", limit=500)

    async def create_schedule(self, body: dict) -> dict:
        return await self.request("confd", "POST", "/schedules", json=body)

    async def update_schedule(self, schedule_id: int, body: dict) -> None:
        await self.request("confd", "PUT", f"/schedules/{schedule_id}", json=body)

    async def delete_schedule(self, schedule_id: int) -> None:
        await self.request("confd", "DELETE", f"/schedules/{schedule_id}")

    async def incall(self, incall_id: int) -> dict:
        return await self.request("confd", "GET", f"/incalls/{incall_id}")

    async def associate_incall_schedule(self, incall_id: int, schedule_id: int) -> None:
        await self.request(
            "confd", "PUT", f"/incalls/{incall_id}/schedules/{schedule_id}"
        )

    async def dissociate_incall_schedule(
        self, incall_id: int, schedule_id: int
    ) -> None:
        await self.request(
            "confd", "DELETE", f"/incalls/{incall_id}/schedules/{schedule_id}"
        )

    async def update_incall(self, incall_id: int, body: dict) -> None:
        await self.request("confd", "PUT", f"/incalls/{incall_id}", json=body)

    # -------------------------------------------- voice menus & sounds

    async def ivrs(self) -> list[dict]:
        return await self._items("confd", "/ivr", limit=500)

    async def ivr(self, ivr_id: int) -> dict:
        return await self.request("confd", "GET", f"/ivr/{ivr_id}")

    async def create_ivr(self, body: dict) -> dict:
        return await self.request("confd", "POST", "/ivr", json=body)

    async def update_ivr(self, ivr_id: int, body: dict) -> None:
        await self.request("confd", "PUT", f"/ivr/{ivr_id}", json=body)

    async def delete_ivr(self, ivr_id: int) -> None:
        await self.request("confd", "DELETE", f"/ivr/{ivr_id}")

    async def sound_categories(self) -> list[dict]:
        return await self._items("confd", "/sounds", limit=500)

    async def create_sound_category(self, name: str) -> dict:
        return await self.request("confd", "POST", "/sounds", json={"name": name})

    async def sound_category(self, name: str, **params) -> dict:
        return await self.request(
            "confd", "GET", f"/sounds/{name}", params=params or None
        )

    async def upload_sound(
        self, category: str, filename: str, audio: bytes, *, sound_format: str
    ) -> None:
        await self.request(
            "confd",
            "PUT",
            f"/sounds/{category}/files/{filename}",
            params={"format": sound_format},
            content=audio,
            content_type="application/octet-stream",
        )

    async def delete_sound(self, category: str, filename: str) -> None:
        await self.request("confd", "DELETE", f"/sounds/{category}/files/{filename}")

    # ------------------------------------------ operator lines (trunks)

    async def tenant(self, tenant_uuid: str) -> dict:
        """The PBX's view of the tenant (its generated SIP templates)."""
        return await self.request("confd", "GET", f"/tenants/{tenant_uuid}")

    async def sip_transports(self) -> list[dict]:
        return await self._items("confd", "/sip/transports", limit=50)

    async def create_endpoint_sip(self, body: dict) -> dict:
        return await self.request("confd", "POST", "/endpoints/sip", json=body)

    async def delete_endpoint_sip(self, sip_uuid: str) -> None:
        await self.request("confd", "DELETE", f"/endpoints/sip/{sip_uuid}")

    async def trunks(self) -> list[dict]:
        return await self._items("confd", "/trunks", limit=500)

    async def trunk(self, trunk_id: int) -> dict:
        return await self.request("confd", "GET", f"/trunks/{trunk_id}")

    async def create_trunk(self, body: dict) -> dict:
        return await self.request("confd", "POST", "/trunks", json=body)

    async def delete_trunk(self, trunk_id: int) -> None:
        await self.request("confd", "DELETE", f"/trunks/{trunk_id}")

    async def associate_trunk_endpoint_sip(self, trunk_id: int, sip_uuid: str) -> None:
        await self.request(
            "confd", "PUT", f"/trunks/{trunk_id}/endpoints/sip/{sip_uuid}"
        )

    async def trunk_statuses(self) -> list[dict]:
        """Registration state and live call count of every trunk."""
        return await self._items("calld", "/trunks")

    async def outcalls(self) -> list[dict]:
        return await self._items("confd", "/outcalls", limit=500)

    async def create_outcall(self, body: dict) -> dict:
        return await self.request("confd", "POST", "/outcalls", json=body)

    async def delete_outcall(self, outcall_id: int) -> None:
        await self.request("confd", "DELETE", f"/outcalls/{outcall_id}")

    async def set_outcall_trunks(self, outcall_id: int, trunk_ids: list[int]) -> None:
        """Ordered: the first trunk is tried first, the next ones on failure."""
        await self.request(
            "confd",
            "PUT",
            f"/outcalls/{outcall_id}/trunks",
            json={"trunks": [{"id": t} for t in trunk_ids]},
        )

    async def associate_outcall_extension(
        self, outcall_id: int, extension_id: int, dial_pattern: dict
    ) -> None:
        await self.request(
            "confd",
            "PUT",
            f"/outcalls/{outcall_id}/extensions/{extension_id}",
            json=dial_pattern,
        )

    # ------------------------------------------------ call restrictions

    async def call_permissions(self) -> list[dict]:
        return await self._items("confd", "/callpermissions", limit=500)

    async def call_permission(self, permission_id: int) -> dict:
        return await self.request("confd", "GET", f"/callpermissions/{permission_id}")

    async def create_call_permission(self, body: dict) -> dict:
        return await self.request("confd", "POST", "/callpermissions", json=body)

    async def delete_call_permission(self, permission_id: int) -> None:
        await self.request("confd", "DELETE", f"/callpermissions/{permission_id}")

    async def associate_user_call_permission(
        self, user_id: int, permission_id: int
    ) -> None:
        await self.request(
            "confd", "PUT", f"/users/{user_id}/callpermissions/{permission_id}"
        )

    async def dissociate_user_call_permission(
        self, user_id: int, permission_id: int
    ) -> None:
        await self.request(
            "confd", "DELETE", f"/users/{user_id}/callpermissions/{permission_id}"
        )

    # ------------------------------------------------------ call groups

    async def groups(self) -> list[dict]:
        return await self._items("confd", "/groups", limit=500)

    async def group(self, group_uuid: str) -> dict:
        return await self.request("confd", "GET", f"/groups/{group_uuid}")

    async def create_group(self, body: dict) -> dict:
        return await self.request("confd", "POST", "/groups", json=body)

    async def update_group(self, group_uuid: str, body: dict) -> None:
        await self.request("confd", "PUT", f"/groups/{group_uuid}", json=body)

    async def delete_group(self, group_uuid: str) -> None:
        await self.request("confd", "DELETE", f"/groups/{group_uuid}")

    async def set_group_users(self, group_uuid: str, users: list[dict]) -> None:
        """``users``: ``[{"uuid": …, "priority": n}]`` — replaces the members."""
        await self.request(
            "confd",
            "PUT",
            f"/groups/{group_uuid}/members/users",
            json={"users": users},
        )

    async def associate_group_extension(
        self, group_uuid: str, extension_id: int
    ) -> None:
        await self.request(
            "confd", "PUT", f"/groups/{group_uuid}/extensions/{extension_id}"
        )

    async def set_group_fallbacks(self, group_uuid: str, fallbacks: dict) -> None:
        await self.request(
            "confd", "PUT", f"/groups/{group_uuid}/fallbacks", json=fallbacks
        )

    # ------------------------------------------ forwards, DND, fallbacks

    async def user_forwards(self, user_id: int | str) -> dict:
        return await self.request("confd", "GET", f"/users/{user_id}/forwards")

    async def set_user_forwards(self, user_id: int | str, forwards: dict) -> None:
        await self.request("confd", "PUT", f"/users/{user_id}/forwards", json=forwards)

    async def user_services(self, user_id: int | str) -> dict:
        return await self.request("confd", "GET", f"/users/{user_id}/services")

    async def set_user_services(self, user_id: int | str, services: dict) -> None:
        await self.request("confd", "PUT", f"/users/{user_id}/services", json=services)

    async def user_fallbacks(self, user_id: int | str) -> dict:
        return await self.request("confd", "GET", f"/users/{user_id}/fallbacks")

    async def set_user_fallbacks(self, user_id: int | str, fallbacks: dict) -> None:
        await self.request(
            "confd", "PUT", f"/users/{user_id}/fallbacks", json=fallbacks
        )

    # ------------------------------------------------------ conferences

    async def conferences(self) -> list[dict]:
        return await self._items("confd", "/conferences", limit=500)

    async def create_conference(self, body: dict) -> dict:
        return await self.request("confd", "POST", "/conferences", json=body)

    async def delete_conference(self, conference_id: int) -> None:
        await self.request("confd", "DELETE", f"/conferences/{conference_id}")

    async def associate_conference_extension(
        self, conference_id: int, extension_id: int
    ) -> None:
        await self.request(
            "confd",
            "PUT",
            f"/conferences/{conference_id}/extensions/{extension_id}",
        )

    async def conference_participants(self, conference_id: int) -> list[dict]:
        return await self._items("calld", f"/conferences/{conference_id}/participants")

    async def kick_participant(self, conference_id: int, participant_id: str) -> None:
        await self.request(
            "calld",
            "DELETE",
            f"/conferences/{conference_id}/participants/{participant_id}",
        )

    async def mute_participant(
        self, conference_id: int, participant_id: str, muted: bool
    ) -> None:
        action = "mute" if muted else "unmute"
        await self.request(
            "calld",
            "PUT",
            f"/conferences/{conference_id}/participants/{participant_id}/{action}",
        )

    # ------------------------------------------------- call recordings

    async def user(self, user_uuid: str) -> dict:
        return await self.request("confd", "GET", f"/users/{user_uuid}")

    async def update_user(self, user_uuid: str, body: dict) -> None:
        """Partial update: only the fields given change."""
        await self.request("confd", "PUT", f"/users/{user_uuid}", json=body)

    async def recorded_cdr(
        self, limit: int = 100, since: str | None = None
    ) -> list[dict]:
        params: dict[str, Any] = {
            "recorded": "true",
            "limit": limit,
            "order": "start",
            "direction": "desc",
        }
        if since:
            params["from"] = since
        return await self._items("call_logd", "/cdr", **params)

    async def cdr_since(self, since: str, *, limit: int = 500, offset: int = 0) -> list[dict]:
        """Call logs started from ``since`` (ISO 8601), oldest first."""
        return await self._items(
            "call_logd",
            "/cdr",
            **{"from": since, "order": "start", "direction": "asc", "limit": limit, "offset": offset},
        )

    async def recording_media(self, cdr_id: int, recording_uuid: str) -> bytes:
        return await self.request(
            "call_logd",
            "GET",
            f"/cdr/{cdr_id}/recordings/{recording_uuid}/media",
            raw=True,
        )

    async def delete_recording_media(self, cdr_id: int, recording_uuid: str) -> None:
        await self.request(
            "call_logd", "DELETE", f"/cdr/{cdr_id}/recordings/{recording_uuid}/media"
        )

    # --------------------------------------------------------- softphone

    async def endpoint_sip(self, sip_uuid: str) -> dict:
        """A SIP account, with its authentication options (secret included)."""
        return await self.request("confd", "GET", f"/endpoints/sip/{sip_uuid}")

    async def user_cdr(self, user_uuid: str, limit: int = 50) -> list[dict]:
        return await self._items(
            "call_logd",
            "/cdr",
            user_uuid=user_uuid,
            limit=limit,
            order="start",
            direction="desc",
        )

    async def send_password_reset_email(self, login: str) -> None:
        """Ask the PBX to e-mail a reset link (white-label template)."""
        try:
            response = await self._http.get(
                f"{SERVICES['auth']}/users/password/reset", params={"login": login}
            )
        except httpx.HTTPError as error:
            raise PbxUnavailable(
                f"PBX injoignable : {error.__class__.__name__}"
            ) from error
        if response.status_code >= 400:
            raise PbxError(_error_message(response), status=response.status_code)

    # ------------------------------------------------- calls and agents

    async def calls(self) -> list[dict]:
        return await self._items("calld", "/calls")

    async def hangup(self, call_id: str) -> None:
        await self.request("calld", "DELETE", f"/calls/{call_id}")

    async def agent_statuses(self) -> list[dict]:
        body = await self.request("agentd", "GET", "/agents")
        return list(body or [])

    async def agent_action(
        self, agent_number: str, action: str, body: dict | None = None
    ) -> None:
        if action not in {"login", "logoff", "pause", "unpause"}:
            raise ValueError(action)
        await self.request(
            "agentd",
            "POST",
            f"/agents/by-number/{agent_number}/{action}",
            json=body or {},
        )

    async def originate(
        self,
        user_uuid: str,
        *,
        context: str,
        extension: str,
        variables: dict[str, str] | None = None,
        line_id: int | None = None,
    ) -> dict:
        """Ring a user's phone; once answered, it continues in the dialplan."""
        source: dict[str, Any] = {"user": user_uuid}
        if line_id is not None:
            source["line_id"] = line_id
        return await self.request(
            "calld",
            "POST",
            "/calls",
            json={
                "source": source,
                "destination": {
                    "context": context,
                    "extension": extension,
                    "priority": 1,
                },
                "variables": variables or {},
            },
        )

    async def queue_status(self, queue_name: str) -> list[dict]:
        """Asterisk's live view of one queue (AMI QueueStatus).

        The answer is the AMI event list: QueueParams, then a QueueMember per
        member and a QueueEntry per waiting caller. The AMI is not tenant
        aware, so the queue is always named explicitly.
        """
        body = await self.request(
            "amid", "POST", "/action/QueueStatus", json={"Queue": queue_name}
        )
        return [m for m in body or [] if isinstance(m, dict)]

    async def queue_statistics(self, **params) -> list[dict]:
        return await self._items("call_logd", "/queues/statistics", **params)

    async def agent_statistics(self, **params) -> list[dict]:
        return await self._items("call_logd", "/agents/statistics", **params)

    async def cdr(self, limit: int = 50) -> list[dict]:
        return await self._items(
            "call_logd", "/cdr", limit=limit, order="start", direction="desc"
        )

    # --------------------------------------------------------- webhooks

    async def subscriptions(self) -> list[dict]:
        return await self._items("webhookd", "/subscriptions")

    async def create_subscription(self, body: dict) -> dict:
        return await self.request("webhookd", "POST", "/subscriptions", json=body)

    async def delete_subscription(self, uuid: str) -> None:
        await self.request("webhookd", "DELETE", f"/subscriptions/{uuid}")


# Exact ACL each call above needs (from the engine's OpenAPI "Required ACL").
# deploy/pbx/integration-policy.json grants these to the service account; a
# test keeps both in sync.
REQUIRED_ACL: dict[str, str] = {
    "check_tenant": "auth.tenants.{tenant_uuid}.read",
    "infos": "confd.infos.read",
    "users": "confd.users.read",
    "queues": "confd.queues.read",
    "agents": "confd.agents.read",
    "contexts": "confd.contexts.read",
    "incalls": "confd.incalls.read",
    "create_incall": "confd.incalls.create",
    "delete_incall": "confd.incalls.{incall_id}.delete",
    "associate_incall_extension": "confd.incalls.{incall_id}.extensions.{extension_id}.update",
    "extensions": "confd.extensions.read",
    "create_extension": "confd.extensions.create",
    "delete_extension": "confd.extensions.{extension_id}.delete",
    "pjsip_global": "confd.asterisk.pjsip.global.read",
    "set_pjsip_global": "confd.asterisk.pjsip.global.update",
    "calls": "calld.calls.read",
    "hangup": "calld.calls.{call_id}.delete",
    "agent_statuses": "agentd.agents.read",
    "agent_login": "agentd.agents.by-number.{agent_number}.login.create",
    "agent_logoff": "agentd.agents.by-number.{agent_number}.logoff.create",
    "agent_pause": "agentd.agents.by-number.{agent_number}.pause.create",
    "agent_unpause": "agentd.agents.by-number.{agent_number}.unpause.create",
    "create_subscription": "webhookd.subscriptions.create",
    "delete_subscription": "webhookd.subscriptions.{subscription_uuid}.delete",
    "cdr": "call-logd.cdr.read",
    # supervision
    "originate": "calld.calls.create",
    "queue_status": "amid.action.QueueStatus.create",
    "queue_statistics": "call-logd.queues.statistics.read",
    "agent_statistics": "call-logd.agents.statistics.read",
    # administration
    "sip_templates": "confd.endpoints.sip.templates.read",
    "create_user": "confd.users.create",
    "delete_user": "confd.users.{user_id}.delete",
    "create_agent": "confd.agents.create",
    "delete_agent": "confd.agents.{agent_id}.delete",
    "associate_user_agent": "confd.users.{user_id}.agents.{agent_id}.update",
    "create_queue": "confd.queues.create",
    "queue": "confd.queues.{queue_id}.read",
    "update_queue": "confd.queues.{queue_id}.update",
    "delete_queue": "confd.queues.{queue_id}.delete",
    "associate_queue_extension": "confd.queues.{queue_id}.extensions.{extension_id}.update",
    "set_queue_member": "confd.queues.{queue_id}.members.agents.{agent_id}.update",
    "remove_queue_member": "confd.queues.{queue_id}.members.agents.{agent_id}.delete",
    "set_queue_fallbacks": "confd.queues.{queue_id}.fallbacks.update",
    "voicemails": "confd.voicemails.read",
    "schedules": "confd.schedules.read",
    "create_schedule": "confd.schedules.create",
    "update_schedule": "confd.schedules.{schedule_id}.update",
    "delete_schedule": "confd.schedules.{schedule_id}.delete",
    "incall": "confd.incalls.{incall_id}.read",
    "associate_incall_schedule": "confd.incalls.{incall_id}.schedules.{schedule_id}.update",
    "dissociate_incall_schedule": "confd.incalls.{incall_id}.schedules.{schedule_id}.delete",
    "update_incall": "confd.incalls.{incall_id}.update",
    # voice menus & sounds
    "ivrs": "confd.ivr.read",
    "ivr": "confd.ivr.{ivr_id}.read",
    "create_ivr": "confd.ivr.create",
    "update_ivr": "confd.ivr.{ivr_id}.update",
    "delete_ivr": "confd.ivr.{ivr_id}.delete",
    "sound_categories": "confd.sounds.read",
    "create_sound_category": "confd.sounds.create",
    "sound_category": "confd.sounds.{sound_category}.read",
    "upload_sound": "confd.sounds.{sound_category}.files.{sound_filename}.update",
    "delete_sound": "confd.sounds.{sound_category}.files.{sound_filename}.delete",
    # operator lines (trunks) and outbound routes
    "tenant": "confd.tenants.{tenant_uuid}.read",
    "sip_transports": "confd.sip.transports.read",
    "create_endpoint_sip": "confd.endpoints.sip.create",
    "delete_endpoint_sip": "confd.endpoints.sip.{sip_uuid}.delete",
    "trunks": "confd.trunks.read",
    "trunk": "confd.trunks.{trunk_id}.read",
    "create_trunk": "confd.trunks.create",
    "delete_trunk": "confd.trunks.{trunk_id}.delete",
    "associate_trunk_endpoint_sip": "confd.trunks.{trunk_id}.endpoints.sip.{sip_uuid}.update",
    "trunk_statuses": "calld.trunks.read",
    "outcalls": "confd.outcalls.read",
    "create_outcall": "confd.outcalls.create",
    "delete_outcall": "confd.outcalls.{outcall_id}.delete",
    "set_outcall_trunks": "confd.outcalls.{outcall_id}.trunks.update",
    "associate_outcall_extension": "confd.outcalls.{outcall_id}.extensions.{extension_id}.update",
    # call restrictions
    "call_permissions": "confd.callpermissions.read",
    "call_permission": "confd.callpermissions.{callpermission_id}.read",
    "create_call_permission": "confd.callpermissions.create",
    "delete_call_permission": "confd.callpermissions.{callpermission_id}.delete",
    "associate_user_call_permission": "confd.users.{user_id}.callpermissions.{call_permission_id}.update",
    "dissociate_user_call_permission": "confd.users.{user_id}.callpermissions.{call_permission_id}.delete",
    # call groups
    "groups": "confd.groups.read",
    "group": "confd.groups.{group_uuid}.read",
    "create_group": "confd.groups.create",
    "update_group": "confd.groups.{group_uuid}.update",
    "delete_group": "confd.groups.{group_uuid}.delete",
    "set_group_users": "confd.groups.{group_uuid}.members.users.update",
    "associate_group_extension": "confd.groups.{group_uuid}.extensions.{extension_id}.update",
    "set_group_fallbacks": "confd.groups.{group_uuid}.fallbacks.update",
    # forwards, do-not-disturb, no-answer destinations
    "user_forwards": "confd.users.{user_id}.forwards.read",
    "set_user_forwards": "confd.users.{user_id}.forwards.update",
    "user_services": "confd.users.{user_id}.services.read",
    "set_user_services": "confd.users.{user_id}.services.update",
    "user_fallbacks": "confd.users.{user_id}.fallbacks.read",
    "set_user_fallbacks": "confd.users.{user_id}.fallbacks.update",
    # conferences
    "conferences": "confd.conferences.read",
    "create_conference": "confd.conferences.create",
    "delete_conference": "confd.conferences.{conference_id}.delete",
    "associate_conference_extension": "confd.conferences.{conference_id}.extensions.{extension_id}.update",
    "conference_participants": "calld.conferences.{conference_id}.participants.read",
    "kick_participant": "calld.conferences.{conference_id}.participants.{participant_id}.delete",
    "mute_participant_mute": "calld.conferences.{conference_id}.participants.{participant_id}.mute.update",
    "mute_participant_unmute": "calld.conferences.{conference_id}.participants.{participant_id}.unmute.update",
    # call recordings
    "user": "confd.users.{user_id}.read",
    "update_user": "confd.users.{user_id}.update",
    "recorded_cdr": "call-logd.cdr.read",
    "recording_media": "call-logd.cdr.{cdr_id}.recordings.{recording_uuid}.media.read",
    "delete_recording_media": "call-logd.cdr.{cdr_id}.recordings.{recording_uuid}.media.delete",
    # NIMBORA Softphone
    "endpoint_sip": "confd.endpoints.sip.{sip_uuid}.read",
    "user_cdr": "call-logd.cdr.read",
    # human minutes billing (catch-up of missed call-log webhooks)
    "cdr_since": "call-logd.cdr.read",
}


# What the operator's provisioning account needs on top of REQUIRED_ACL to
# create a company's tenant, its dialplan contexts and its service account on
# a shared PBX. The engine only lets an account hand out a policy whose ACLs it
# holds itself, so the provisioning policy is REQUIRED_ACL + these (see
# deploy/pbx/provisioning-policy.json; a test keeps them in sync).
PROVISIONING_ACL: dict[str, str] = {
    "tenants": "auth.tenants.read",
    "create_tenant": "auth.tenants.create",
    "delete_tenant": "auth.tenants.{tenant_uuid}.delete",
    "policies": "auth.policies.read",
    "create_policy": "auth.policies.create",
    "auth_users": "auth.users.read",
    "create_auth_user": "auth.users.create",
    "delete_auth_user": "auth.users.{user_uuid}.delete",
    "set_auth_user_policy": "auth.users.{user_uuid}.policies.{policy_uuid}.create",
    "create_context": "confd.contexts.create",
    "set_context_includes": "confd.contexts.{context_id}.contexts.update",
}
