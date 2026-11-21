"""In-memory PBX engine (Wazo Platform REST contracts) for tests.

Shapes follow the published OpenAPI specifications: token under
``data.token``, lists as ``{"items": [...], "total": n}``, agentd statuses as a
bare list, confd errors as a JSON list of messages, tenant in ``Wazo-Tenant``.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import httpx

TENANT = "8f9a3b2c-0000-4000-8000-000000000001"


class FakePbx:
    def __init__(self, *, username="nimbora", password="secret", version="26.09"):
        self.username = username
        self.password = password
        self.version = version
        self.tokens: set[str] = set()
        self.token_requests = 0
        self.requests: list[tuple[str, str, dict]] = []
        self.down: set[str] = set()  # services answering 503
        self.contexts = [
            {"id": 1, "name": "from-extern", "type": "incall", "tenant_uuid": TENANT},
            {"id": 2, "name": "default", "type": "internal", "tenant_uuid": TENANT},
        ]
        self.extensions: list[dict] = [
            {"id": 10, "exten": "1001", "context": "default"},
            {"id": 11, "exten": "+22527000000", "context": "from-extern"},
        ]
        self.incalls: list[dict] = [
            {
                "id": 5,
                "description": "Standard",
                "destination": {"type": "queue", "queue_id": 1},
                "extensions": [
                    {"id": 11, "exten": "+22527000000", "context": "from-extern"}
                ],
            }
        ]
        self.users = [
            {
                "uuid": "u-1",
                "firstname": "Koffi",
                "lastname": "Yao",
                "extension": "1001",
                "email": "koffi@ivoire-immo.ci",
                "enabled": True,
            },
            {
                "uuid": "u-2",
                "firstname": "Aya",
                "lastname": "Diallo",
                "extension": "1002",
                "email": None,
                "enabled": True,
            },
        ]
        self.queues = [
            {
                "id": 1,
                "name": "ventes",
                "label": "Ventes",
                "extensions": [{"exten": "3001"}],
                "members": {"agents": [{"id": 7}], "users": []},
            },
        ]
        self.agents = [
            {"id": 7, "number": "1001", "firstname": "Koffi", "lastname": "Yao"}
        ]
        self.statuses = [
            {
                "id": 7,
                "number": "1001",
                "logged": True,
                "paused": True,
                "paused_reason": "pause déjeuner",
                "extension": "1001",
                "context": "default",
            }
        ]
        self.calls = [
            {
                "call_id": "1700000000.1",
                "caller_id_number": "+2250700112233",
                "caller_id_name": "Awa",
                "peer_caller_id_number": "1001",
                "peer_caller_id_name": "Koffi Yao",
                "status": "Up",
                "direction": "inbound",
                "answer_time": "2026-11-21T09:00:00+00:00",
                "on_hold": False,
            },
        ]
        self.cdr = [
            {
                "id": 900,
                "start": "2026-11-21T08:00:00+00:00",
                "answered": True,
                "duration": 185.0,
                "call_direction": "inbound",
                "source_extension": "+2250700112233",
                "source_name": "Awa",
                "destination_extension": "1001",
                "destination_name": "Koffi Yao",
            },
        ]
        self.subscriptions: dict[str, dict] = {}
        self.pjsip = {"user_agent": "Wazo", "keep_alive_interval": "30"}
        self.agent_actions: list[tuple[str, str, dict]] = []
        self.hung_up: list[str] = []
        self.password_resets: list[tuple[str, str]] = []
        self._next = 100

    # ------------------------------------------------------------------

    def _id(self) -> int:
        self._next += 1
        return self._next

    @property
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def revoke_tokens(self) -> None:
        self.tokens.clear()

    def handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        method = request.method
        body = json.loads(request.content) if request.content else None
        self.requests.append((method, path, dict(request.headers)))
        service = path.split("/")[2] if path.startswith("/api/") else ""
        if service in self.down:
            return httpx.Response(503, json={"message": "Service unavailable"})

        if path == "/api/auth/0.1/token" and method == "POST":
            import base64

            expected = base64.b64encode(
                f"{self.username}:{self.password}".encode()
            ).decode()
            if request.headers.get("authorization") != f"Basic {expected}":
                return httpx.Response(
                    401, json={"reason": ["Authentication Failed"], "status_code": 401}
                )
            self.token_requests += 1
            token = str(uuid.uuid4())
            self.tokens.add(token)
            return httpx.Response(
                200,
                json={
                    "data": {
                        "token": token,
                        "expires_at": "x",
                        "metadata": {"tenant_uuid": TENANT},
                    }
                },
            )

        if path == "/api/auth/0.1/users/password/reset" and method == "POST":
            if request.headers.get("x-auth-token") != "email-token-123":
                return httpx.Response(401, json={"reason": ["Unauthorized"]})
            self.password_resets.append(
                (request.url.params.get("user_uuid"), body["password"])
            )
            return httpx.Response(204)

        if request.headers.get("x-auth-token") not in self.tokens:
            return httpx.Response(
                401, json={"reason": ["Unauthorized"], "status_code": 401}
            )

        # ----- auth
        if path == f"/api/auth/0.1/tenants/{TENANT}" and method == "GET":
            return httpx.Response(200, json={"uuid": TENANT, "name": "Ivoire Immo"})
        if path.startswith("/api/auth/0.1/tenants/") and method == "GET":
            return httpx.Response(
                404, json={"message": "No such tenant", "error_id": "unknown-tenant"}
            )

        prefix = "/api/confd/1.1"
        if path == f"{prefix}/infos":
            return httpx.Response(
                200, json={"uuid": "engine-uuid", "wazo_version": self.version}
            )
        if (
            path.startswith(prefix)
            and path != f"{prefix}/infos"
            and "asterisk" not in path
        ):
            if request.headers.get("wazo-tenant") != TENANT:
                return httpx.Response(401, json={"message": "Unauthorized tenant"})
        if path == f"{prefix}/users":
            return httpx.Response(
                200, json={"items": self.users, "total": len(self.users)}
            )
        if path == f"{prefix}/queues":
            return httpx.Response(
                200, json={"items": self.queues, "total": len(self.queues)}
            )
        if path == f"{prefix}/agents":
            return httpx.Response(
                200, json={"items": self.agents, "total": len(self.agents)}
            )
        if path == f"{prefix}/contexts":
            return httpx.Response(
                200, json={"items": self.contexts, "total": len(self.contexts)}
            )
        if path == f"{prefix}/incalls" and method == "GET":
            return httpx.Response(
                200, json={"items": self.incalls, "total": len(self.incalls)}
            )
        if path == f"{prefix}/incalls" and method == "POST":
            if not body or "destination" not in body:
                return httpx.Response(
                    400,
                    json=[
                        "Input Error - field 'destination': Missing data for required field."
                    ],
                )
            incall = {
                "id": self._id(),
                "description": body.get("description"),
                "destination": body["destination"],
                "extensions": [],
            }
            self.incalls.append(incall)
            return httpx.Response(201, json=incall)
        if (
            path.startswith(f"{prefix}/incalls/")
            and "/extensions/" in path
            and method == "PUT"
        ):
            incall_id, extension_id = int(path.split("/")[5]), int(path.split("/")[7])
            incall = next((i for i in self.incalls if i["id"] == incall_id), None)
            extension = next(
                (e for e in self.extensions if e["id"] == extension_id), None
            )
            if not incall or not extension:
                return httpx.Response(404, json=["Resource Not Found"])
            incall["extensions"].append(extension)
            return httpx.Response(204)
        if path.startswith(f"{prefix}/incalls/") and method == "DELETE":
            incall_id = int(path.split("/")[-1])
            before = len(self.incalls)
            self.incalls = [i for i in self.incalls if i["id"] != incall_id]
            return httpx.Response(
                204 if len(self.incalls) < before else 404,
                json=None if len(self.incalls) < before else ["Resource Not Found"],
            )
        if path == f"{prefix}/extensions" and method == "GET":
            exten, context = (
                request.url.params.get("exten"),
                request.url.params.get("context"),
            )
            items = [
                e
                for e in self.extensions
                if (not exten or e["exten"] == exten)
                and (not context or e["context"] == context)
            ]
            return httpx.Response(200, json={"items": items, "total": len(items)})
        if path == f"{prefix}/extensions" and method == "POST":
            if any(
                e["exten"] == body["exten"] and e["context"] == body["context"]
                for e in self.extensions
            ):
                return httpx.Response(
                    400, json=["Resource Error - Extension already exists"]
                )
            extension = {
                "id": self._id(),
                "exten": body["exten"],
                "context": body["context"],
            }
            self.extensions.append(extension)
            return httpx.Response(201, json=extension)
        if path.startswith(f"{prefix}/extensions/") and method == "DELETE":
            extension_id = int(path.split("/")[-1])
            self.extensions = [e for e in self.extensions if e["id"] != extension_id]
            return httpx.Response(204)
        if path == f"{prefix}/asterisk/pjsip/global" and method == "GET":
            return httpx.Response(200, json={"options": dict(self.pjsip)})
        if path == f"{prefix}/asterisk/pjsip/global" and method == "PUT":
            self.pjsip = dict(body["options"])
            return httpx.Response(204)

        if path == "/api/calld/1.0/calls":
            return httpx.Response(200, json={"items": self.calls})
        if path.startswith("/api/calld/1.0/calls/") and method == "DELETE":
            call_id = path.split("/")[-1]
            if not any(c["call_id"] == call_id for c in self.calls):
                return httpx.Response(
                    404, json={"message": "No such call", "error_id": "no-such-call"}
                )
            self.hung_up.append(call_id)
            return httpx.Response(204)
        if path == "/api/agentd/1.0/agents":
            return httpx.Response(200, json=self.statuses)
        if path.startswith("/api/agentd/1.0/agents/by-number/") and method == "POST":
            parts = path.split("/")
            self.agent_actions.append((parts[-2], parts[-1], body or {}))
            return httpx.Response(204)
        if path == "/api/call-logd/1.0/cdr":
            return httpx.Response(
                200,
                json={
                    "items": self.cdr,
                    "total": len(self.cdr),
                    "filtered": len(self.cdr),
                },
            )
        if path == "/api/webhookd/1.0/subscriptions" and method == "POST":
            sub = {"uuid": str(uuid.uuid4()), **body}
            self.subscriptions[sub["uuid"]] = sub
            return httpx.Response(200, json=sub)
        if path.startswith("/api/webhookd/1.0/subscriptions/") and method == "DELETE":
            sub_uuid = path.split("/")[-1]
            if self.subscriptions.pop(sub_uuid, None) is None:
                return httpx.Response(404, json={"message": "No such subscription"})
            return httpx.Response(204)
        return httpx.Response(404, json={"message": f"no fake for {method} {path}"})


def install(monkeypatch, fake: FakePbx) -> None:
    """Route every PBX client of the service through the fake."""
    from api.services.pbx import client as client_module
    from api.services.pbx import service

    real = client_module.PbxClient
    client_module._TOKENS.clear()

    def factory(settings, **kwargs):
        kwargs.setdefault("transport", fake.transport)
        return real(settings, **kwargs)

    monkeypatch.setattr(service, "PbxClient", factory)
    monkeypatch.setattr(service, "assert_pbx_url_allowed", lambda url: None)


def as_dict(value: Any) -> Any:
    return value
