"""In-memory PBX engine (Wazo Platform REST contracts) for tests.

Shapes follow the published OpenAPI specifications: token under
``data.token``, lists as ``{"items": [...], "total": n}``, agentd statuses as a
bare list, confd errors as a JSON list of messages, tenant in ``Wazo-Tenant``.
"""

from __future__ import annotations

import json
import re
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
        self.forbidden: set[str] = set()  # services refusing the account's ACL (403)
        self.contexts = [
            {"id": 1, "name": "from-extern", "type": "incall", "tenant_uuid": TENANT},
            {"id": 2, "name": "default", "type": "internal", "tenant_uuid": TENANT},
            {"id": 3, "name": "to-extern", "type": "outcall", "tenant_uuid": TENANT},
        ]
        self.extensions: list[dict] = [
            {"id": 10, "exten": "1001", "context": "default"},
            # DIDs are digits only on the engine (no "+"), see numbers._exten.
            {"id": 11, "exten": "22527000000", "context": "from-extern"},
        ]
        self.incalls: list[dict] = [
            {
                "id": 5,
                "description": "Standard",
                "destination": {"type": "queue", "queue_id": 1},
                "extensions": [
                    {"id": 11, "exten": "22527000000", "context": "from-extern"}
                ],
            }
        ]
        self.auth_tenants: list[dict] = []
        self.auth_policies: list[dict] = []
        self.auth_users: list[dict] = []
        self.users = [
            {
                "id": 1,
                "uuid": "u-1",
                "firstname": "Koffi",
                "lastname": "Yao",
                "extension": "1001",
                "email": "koffi@ivoire-immo.ci",
                "enabled": True,
            },
            {
                "id": 2,
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
                "extensions": [{"exten": "3001", "context": "default"}],
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
        # chatd presence, as the engine reports it (u-1 is on the call below).
        self.presences = [
            {
                "uuid": "u-1",
                "state": "available",
                "status": "",
                "line_state": "talking",
                "do_not_disturb": False,
                "connected": True,
                "mobile": False,
            },
            {
                "uuid": "u-2",
                "state": "available",
                "status": "",
                "line_state": "available",
                "do_not_disturb": False,
                "connected": True,
                "mobile": False,
            },
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
                "creation_time": "2026-11-21T08:59:50+00:00",
                "on_hold": False,
                "user_uuid": "u-1",
                "line_id": 1,
                "talking_to": {"1700000000.2": "+2250700112233"},
            },
        ]
        # AMI view of queues (wazo-amid QueueStatus): waiting callers.
        self.queue_entries: dict[str, list[dict]] = {
            "ventes": [
                {
                    "Position": "1",
                    "CallerIDNum": "+2250102030405",
                    "CallerIDName": "Ibrahim Touré",
                    "Wait": "42",
                    "Channel": "PJSIP/operateur-00000012",
                }
            ]
        }
        self.queue_params: dict[str, dict] = {
            "ventes": {"Completed": "14", "Abandoned": "2", "ServiceLevel": "20"}
        }
        self.originated: list[dict] = []
        self.queue_stats: list[dict] = [
            {
                "queue_id": 1,
                "queue_name": "ventes",
                "tenant_uuid": TENANT,
                "received": 40,
                "answered": 34,
                "abandoned": 4,
                "closed": 1,
                "not_answered": 1,
                "saturated": 0,
                "blocked": 0,
                "average_waiting_time": 27,
                "answered_rate": 87.18,
                "quality_of_service": 76.47,
            }
        ]
        self.agent_stats: list[dict] = [
            {
                "agent_id": 7,
                "agent_number": "1001",
                "tenant_uuid": TENANT,
                "answered": 21,
                "conversation_time": 4380,
                "login_time": 25200,
                "pause_time": 1800,
                "wrapup_time": 630,
            }
        ]
        self.stat_requests: list[dict] = []
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
        # True: global Asterisk settings answer 401 to a non-master token,
        # like the real engine does for a company's service account.
        self.asterisk_master_only = False
        # True: wazo-amid answers 401 to every token but a master-tenant one
        # (required_master_tenant on each /action), like the real engine.
        self.amid_master_only = False
        # (username, password) of the platform operator, a master-tenant account.
        self.operator_credentials: tuple[str, str] | None = None
        self.master_tokens: set[str] = set()
        self.agent_actions: list[tuple[str, str, dict]] = []
        self.hung_up: list[str] = []
        self.password_resets: list[tuple[str, str]] = []
        self.reset_emails: list[str] = []
        self.templates = [
            {"uuid": "tpl-global", "label": "global"},
            {"uuid": "tpl-webrtc", "label": "webrtc"},
        ]
        self.created_users: list[dict] = []
        self.voicemails = [
            {"id": 1, "name": "Accueil", "number": "1000", "context": "default"}
        ]
        self.schedules: list[dict] = []
        self.fallbacks: dict[int, dict] = {}
        self.fail_agent_creation = False
        # voice menus & sounds
        self.ivrs: list[dict] = []
        self.sound_categories: dict[str, dict[str, bytes]] = {}
        # operator lines & outbound routes
        self.tenant_templates = {
            "uuid": TENANT,
            "global_sip_template_uuid": "tpl-global",
            "webrtc_sip_template_uuid": "tpl-webrtc",
            "registration_trunk_sip_template_uuid": "tpl-trunk",
        }
        self.transports = [
            {
                "uuid": "tr-udp",
                "name": "transport-udp",
                "options": [["protocol", "udp"]],
            },
            {
                "uuid": "tr-tls",
                "name": "transport-tls",
                "options": [["protocol", "tls"]],
            },
        ]
        # SIP accounts of the seeded extensions: Koffi has a browser (WebRTC)
        # line, Aya a classic SIP desk phone.
        self.endpoints_sip: dict[str, dict] = {}  # trunks
        self.endpoint_updates: list[str] = []
        self.user_endpoints: dict[str, dict] = {
            "sip-u1": {
                "uuid": "sip-u1",
                "name": "koffi1001",
                "templates": [
                    {"uuid": "tpl-webrtc", "label": "webrtc"},
                    {"uuid": "tpl-global", "label": "global"},
                ],
                "auth_section_options": [
                    ["username", "koffi1001"],
                    ["password", "Sip-Secret-1001"],
                ],
            },
            "sip-u2": {
                "uuid": "sip-u2",
                "name": "aya1002",
                "templates": [{"uuid": "tpl-global", "label": "global"}],
                "auth_section_options": [
                    ["username", "aya1002"],
                    ["password", "Sip-Secret-1002"],
                ],
            },
        }
        self.users[0]["lines"] = [
            {
                "id": 1,
                "endpoint_sip": {"uuid": "sip-u1"},
                "extensions": [{"exten": "1001", "context": "default"}],
            }
        ]
        self.users[1]["lines"] = [
            {
                "id": 2,
                "endpoint_sip": {"uuid": "sip-u2"},
                "extensions": [{"exten": "1002", "context": "default"}],
            }
        ]
        self.trunks: list[dict] = []
        self.trunk_status: dict[int, dict] = {}
        self.outcalls: list[dict] = []
        self.fail_trunk_association = False
        self.call_permissions: list[dict] = []
        self.groups: list[dict] = []
        self.user_forwards: dict[int, dict] = {}
        self.user_services: dict[int, dict] = {}
        self.user_fallbacks: dict[int, dict] = {}
        self.conferences: list[dict] = []
        self.callpickups: list[dict] = []
        self.parkinglots: list[dict] = []
        self.pagings: list[dict] = []
        self.parked: list[dict] = []  # calld parked calls, keyed by lot_id
        self.participants: dict[int, list[dict]] = {}
        self.participant_actions: list[tuple[int, str, str]] = []
        self.user_settings: dict[str, dict] = {}
        self.recording_media: dict[str, bytes] = {}
        self.deleted_media: list[str] = []
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
        body = (
            json.loads(request.content)
            if request.content
            and request.headers.get("content-type") != "application/octet-stream"
            else None
        )
        self.requests.append((method, path, dict(request.headers)))
        service = path.split("/")[2] if path.startswith("/api/") else ""
        if service in self.down:
            return httpx.Response(503, json={"message": "Service unavailable"})
        if service in self.forbidden:
            return httpx.Response(403, json={"message": "Unauthorized ACL"})

        if path == "/api/auth/0.1/token" and method == "POST":
            import base64

            expected = base64.b64encode(
                f"{self.username}:{self.password}".encode()
            ).decode()
            operator = (
                "Basic "
                + base64.b64encode(
                    ":".join(self.operator_credentials).encode()
                ).decode()
                if self.operator_credentials
                else None
            )
            given = request.headers.get("authorization")
            if given != f"Basic {expected}" and given != operator:
                return httpx.Response(
                    401, json={"reason": ["Authentication Failed"], "status_code": 401}
                )
            self.token_requests += 1
            token = str(uuid.uuid4())
            self.tokens.add(token)
            if operator and given == operator:
                self.master_tokens.add(token)
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

        if path == "/api/auth/0.1/users/password/reset" and method == "GET":
            self.reset_emails.append(request.url.params.get("login"))
            return httpx.Response(204)
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

        # ----- auth: operator provisioning (tenants, policies, accounts)
        tenant_header = request.headers.get("wazo-tenant")
        if path == "/api/auth/0.1/tenants" and method == "GET":
            search = request.url.params.get("search") or ""
            items = [t for t in self.auth_tenants if search in (t["slug"] + t["name"])]
            return httpx.Response(200, json={"items": items, "total": len(items)})
        if path == "/api/auth/0.1/tenants" and method == "POST":
            tenant = {
                "uuid": str(uuid.uuid4()),
                "name": body["name"],
                "slug": body.get("slug", ""),
            }
            self.auth_tenants.append(tenant)
            return httpx.Response(200, json=tenant)
        m = re.fullmatch(r"/api/auth/0\.1/tenants/([^/]+)", path)
        if m and method == "DELETE":
            before = len(self.auth_tenants)
            self.auth_tenants = [
                t for t in self.auth_tenants if t["uuid"] != m.group(1)
            ]
            if len(self.auth_tenants) == before:
                return httpx.Response(404, json={"message": "No such tenant"})
            return httpx.Response(204)
        if path == "/api/auth/0.1/policies" and method == "GET":
            items = [
                p
                for p in self.auth_policies
                if p["tenant_uuid"] == tenant_header
                and (request.url.params.get("search") or "") in p["name"]
            ]
            return httpx.Response(200, json={"items": items, "total": len(items)})
        m = re.fullmatch(r"/api/auth/0\.1/policies/([^/]+)", path)
        if m and method == "PUT":
            for policy in self.auth_policies:
                if policy["uuid"] == m.group(1):
                    policy.update(body)
                    return httpx.Response(200, json=policy)
            return httpx.Response(404, json={"message": "No such policy"})
        if path == "/api/auth/0.1/policies" and method == "POST":
            policy = {**body, "uuid": str(uuid.uuid4()), "tenant_uuid": tenant_header}
            self.auth_policies.append(policy)
            return httpx.Response(200, json=policy)
        if path == "/api/auth/0.1/users" and method == "GET":
            items = [
                u
                for u in self.auth_users
                if u["tenant_uuid"] == tenant_header
                and (request.url.params.get("search") or "") in u["username"]
            ]
            return httpx.Response(200, json={"items": items, "total": len(items)})
        if path == "/api/auth/0.1/users" and method == "POST":
            account = {
                **body,
                "uuid": str(uuid.uuid4()),
                "tenant_uuid": tenant_header,
                "policies": [],
            }
            self.auth_users.append(account)
            return httpx.Response(
                200, json={k: v for k, v in account.items() if k != "password"}
            )
        m = re.fullmatch(r"/api/auth/0\.1/users/([^/]+)", path)
        if m and method == "DELETE":
            self.auth_users = [u for u in self.auth_users if u["uuid"] != m.group(1)]
            return httpx.Response(204)
        m = re.fullmatch(r"/api/auth/0\.1/users/([^/]+)/policies/([^/]+)", path)
        if m and method == "PUT":
            for account in self.auth_users:
                if account["uuid"] == m.group(1):
                    account["policies"].append(m.group(2))
                    return httpx.Response(204)
            return httpx.Response(404, json={"message": "No such user"})

        # ----- auth
        if path == f"/api/auth/0.1/tenants/{TENANT}" and method == "GET":
            return httpx.Response(200, json={"uuid": TENANT, "name": "Ivoire Immo"})
        for created in self.auth_tenants:
            if path == f"/api/auth/0.1/tenants/{created['uuid']}" and method == "GET":
                return httpx.Response(200, json=created)
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
            if request.headers.get("wazo-tenant") not in {
                TENANT,
                *(t["uuid"] for t in self.auth_tenants),
            }:
                return httpx.Response(401, json={"message": "Unauthorized tenant"})
        if path == f"{prefix}/users" and method == "GET":
            return httpx.Response(
                200, json={"items": self.users, "total": len(self.users)}
            )
        if path == f"{prefix}/queues" and method == "GET":
            return httpx.Response(
                200, json={"items": self.queues, "total": len(self.queues)}
            )
        if path == f"{prefix}/agents" and method == "GET":
            return httpx.Response(
                200, json={"items": self.agents, "total": len(self.agents)}
            )
        if path == f"{prefix}/contexts" and method == "POST":
            context = {
                "name": f"ctx-{body['type']}-{self._next}",
                **body,
                "id": self._id(),
                "tenant_uuid": tenant_header,
            }
            self.contexts.append(context)
            return httpx.Response(200, json=context)
        m = re.fullmatch(rf"{prefix}/contexts/(\d+)", path)
        if m and method == "PUT":
            for context in self.contexts:
                if context["id"] == int(m.group(1)):
                    context.update(body)
                    return httpx.Response(204)
            return httpx.Response(404, json=["Context not found"])
        m = re.fullmatch(rf"{prefix}/contexts/(\d+)/contexts", path)
        if m and method == "PUT":
            for context in self.contexts:
                if context["id"] == int(m.group(1)):
                    context["contexts"] = body["contexts"]
                    return httpx.Response(204)
            return httpx.Response(404, json=["Context not found"])
        if path == f"{prefix}/contexts":
            items = [
                c
                for c in self.contexts
                if not tenant_header or c.get("tenant_uuid") == tenant_header
            ]
            return httpx.Response(200, json={"items": items, "total": len(items)})
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
        if re.fullmatch(rf"{prefix}/incalls/\d+", path) and method == "DELETE":
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
            if not re.fullmatch(r"_?[0-9*#XZN.!\[\]-]+", body.get("exten") or ""):
                # The engine's pattern: digits and dialplan patterns, never a "+".
                return httpx.Response(
                    400, json=["exten: ['String does not match expected pattern.']"]
                )
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
        if re.fullmatch(rf"{prefix}/extensions/\d+", path) and method == "DELETE":
            extension_id = int(path.split("/")[-1])
            self.extensions = [e for e in self.extensions if e["id"] != extension_id]
            return httpx.Response(204)
        if path == f"{prefix}/asterisk/pjsip/global" and self.asterisk_master_only:
            # The real engine: global Asterisk settings need a master-tenant
            # token; a company's service account gets 401 (not 403).
            return httpx.Response(
                401, json={"reason": ["Unauthorized"], "status_code": 401}
            )
        if path == f"{prefix}/asterisk/pjsip/global" and method == "GET":
            return httpx.Response(200, json={"options": dict(self.pjsip)})
        if path == f"{prefix}/asterisk/pjsip/global" and method == "PUT":
            self.pjsip = dict(body["options"])
            return httpx.Response(204)

        # ----- administration (confd)
        if path == f"{prefix}/endpoints/sip/templates":
            return httpx.Response(
                200, json={"items": self.templates, "total": len(self.templates)}
            )
        if path == f"{prefix}/users" and method == "POST":
            if not body.get("firstname"):
                return httpx.Response(
                    400,
                    json=[
                        "Input Error - field 'firstname': Missing data for required field."
                    ],
                )
            for line in body.get("lines") or []:
                if "context" not in line:
                    return httpx.Response(
                        400,
                        json=["Input Error - field 'lines.0.context': Missing data"],
                    )
                for ext in line.get("extensions") or []:
                    if any(
                        e["exten"] == ext["exten"] and e["context"] == ext["context"]
                        for e in self.extensions
                    ):
                        return httpx.Response(
                            400, json=["Resource Error - Extension already exists"]
                        )
                templates = (line.get("endpoint_sip") or {}).get("templates") or []
                if any(
                    t.get("uuid") not in {x["uuid"] for x in self.templates}
                    for t in templates
                ):
                    return httpx.Response(
                        404, json=["Resource Not Found - EndpointSIPTemplate"]
                    )
            # Like the engine: logins (wazo-auth usernames) are unique across the
            # whole PBX, whatever the tenant.
            login = (body.get("auth") or {}).get("username")
            if login and any(
                (u.get("auth") or {}).get("username") == login for u in self.users
            ):
                return httpx.Response(
                    400,
                    json=[
                        "409 Client Error: Conflict detected for url: "
                        "http://localhost:80/api/auth/0.1/users"
                    ],
                )
            user = {"uuid": str(uuid.uuid4()), "id": self._id(), **body}
            created_lines = []
            for line in body.get("lines") or []:
                sip_uuid = str(uuid.uuid4())
                self.user_endpoints[sip_uuid] = {
                    "uuid": sip_uuid,
                    # The engine names the endpoint itself (random, ≠ auth user).
                    "name": f"ep{sip_uuid.replace('-', '')[:8]}",
                    **(line.get("endpoint_sip") or {}),
                }
                created_lines.append(
                    {
                        "id": self._id(),
                        "endpoint_sip": {"uuid": sip_uuid},
                        "extensions": line.get("extensions") or [],
                    }
                )
            for line in body.get("lines") or []:
                for ext in line.get("extensions") or []:
                    self.extensions.append(
                        {
                            "id": self._id(),
                            "exten": ext["exten"],
                            "context": ext["context"],
                            "user_uuid": user["uuid"],
                        }
                    )
            if body.get("voicemail"):
                self.voicemails.append({"id": self._id(), **body["voicemail"]})
            self.users.append(
                {
                    "id": user["id"],
                    "uuid": user["uuid"],
                    "firstname": body["firstname"],
                    "lastname": body.get("lastname"),
                    "extension": (body.get("lines") or [{}])[0]
                    .get("extensions", [{}])[0]
                    .get("exten"),
                    "email": body.get("email"),
                    "enabled": True,
                    "lines": created_lines,
                }
            )
            self.created_users.append(user)
            return httpx.Response(201, json=user)
        if (
            path.startswith(f"{prefix}/users/")
            and method == "DELETE"
            and path.count("/") == 5
        ):
            user_uuid = path.split("/")[-1]
            if not any(u["uuid"] == user_uuid for u in self.users):
                return httpx.Response(404, json=["Resource Not Found - User"])
            if request.url.params.get("recursive") != "true":
                return httpx.Response(
                    400, json=["Resource Error - User is associated with a Line"]
                )
            self.users = [u for u in self.users if u["uuid"] != user_uuid]
            self.extensions = [
                e for e in self.extensions if e.get("user_uuid") != user_uuid
            ]
            return httpx.Response(204)
        if path == f"{prefix}/agents" and method == "POST":
            if self.fail_agent_creation:
                return httpx.Response(
                    400, json=["Resource Error - Agent already exists"]
                )
            agent = {"id": self._id(), **body}
            self.agents.append(agent)
            return httpx.Response(201, json=agent)
        if path.startswith(f"{prefix}/agents/") and method == "DELETE":
            agent_id = int(path.split("/")[-1])
            self.agents = [a for a in self.agents if a["id"] != agent_id]
            return httpx.Response(204)
        if (
            path.startswith(f"{prefix}/users/")
            and "/agents/" in path
            and method == "PUT"
        ):
            return httpx.Response(204)
        if path == f"{prefix}/queues" and method == "POST":
            if not body.get("name") or not re.fullmatch(r"[a-z0-9_-]+", body["name"]):
                return httpx.Response(400, json=["Input Error - field 'name': invalid"])
            queue = {
                "id": self._id(),
                "members": {"agents": [], "users": []},
                "extensions": [],
                "wait_time_threshold": None,
                "wait_time_destination": None,
                "timeout": None,
                **body,
            }
            self.queues.append(queue)
            return httpx.Response(201, json=queue)
        if re.fullmatch(rf"{prefix}/queues/\d+", path):
            queue_id = int(path.split("/")[-1])
            queue = next((q for q in self.queues if q["id"] == queue_id), None)
            if queue is None:
                return httpx.Response(404, json=["Resource Not Found - Queue"])
            if method == "GET":
                return httpx.Response(200, json=queue)
            if method == "PUT":
                if "name" in body:
                    return httpx.Response(
                        400, json=["Input Error - field 'name': read only"]
                    )
                queue.update(body)
                return httpx.Response(204)
            if method == "DELETE":
                self.queues = [q for q in self.queues if q["id"] != queue_id]
                return httpx.Response(204)
        m = re.fullmatch(rf"{prefix}/queues/(\d+)/extensions/(\d+)", path)
        if m and method == "PUT":
            queue = next(q for q in self.queues if q["id"] == int(m.group(1)))
            extension = next(e for e in self.extensions if e["id"] == int(m.group(2)))
            queue["extensions"].append(extension)
            return httpx.Response(204)
        m = re.fullmatch(rf"{prefix}/queues/(\d+)/members/agents/(\d+)", path)
        if m:
            queue = next((q for q in self.queues if q["id"] == int(m.group(1))), None)
            agent_id = int(m.group(2))
            if queue is None or not any(a["id"] == agent_id for a in self.agents):
                return httpx.Response(404, json=["Resource Not Found"])
            members = queue["members"]["agents"]
            if method == "PUT":
                members[:] = [a for a in members if a["id"] != agent_id] + [
                    {"id": agent_id, "penalty": body.get("penalty", 0)}
                ]
            else:
                members[:] = [a for a in members if a["id"] != agent_id]
            return httpx.Response(204)
        m = re.fullmatch(rf"{prefix}/queues/(\d+)/fallbacks", path)
        if m and method == "PUT":
            self.fallbacks[int(m.group(1))] = body
            return httpx.Response(204)
        if path == f"{prefix}/voicemails":
            return httpx.Response(
                200, json={"items": self.voicemails, "total": len(self.voicemails)}
            )
        if path == f"{prefix}/schedules" and method == "GET":
            return httpx.Response(
                200, json={"items": self.schedules, "total": len(self.schedules)}
            )
        if path == f"{prefix}/schedules" and method == "POST":
            if "closed_destination" not in body:
                return httpx.Response(
                    400, json=["Input Error - field 'closed_destination': Missing data"]
                )
            schedule = {"id": self._id(), **body}
            self.schedules.append(schedule)
            return httpx.Response(201, json=schedule)
        m = re.fullmatch(rf"{prefix}/schedules/(\d+)", path)
        if m:
            schedule = next(
                (x for x in self.schedules if x["id"] == int(m.group(1))), None
            )
            if schedule is None:
                return httpx.Response(404, json=["Resource Not Found - Schedule"])
            if method == "PUT":
                schedule.update(body)
            else:
                self.schedules.remove(schedule)
            return httpx.Response(204)
        m = re.fullmatch(rf"{prefix}/incalls/(\d+)", path)
        if m and method == "GET":
            incall = next((i for i in self.incalls if i["id"] == int(m.group(1))), None)
            return (
                httpx.Response(200, json=incall)
                if incall
                else httpx.Response(404, json=["Resource Not Found - Incall"])
            )
        m = re.fullmatch(rf"{prefix}/incalls/(\d+)/schedules/(\d+)", path)
        if m:
            incall = next((i for i in self.incalls if i["id"] == int(m.group(1))), None)
            schedule = next(
                (x for x in self.schedules if x["id"] == int(m.group(2))), None
            )
            if incall is None or schedule is None:
                return httpx.Response(404, json=["Resource Not Found"])
            current = incall.setdefault("schedules", [])
            if method == "PUT":
                if current and current[0]["id"] != schedule["id"]:
                    return httpx.Response(
                        400, json=["Resource Error - Incall already has a schedule"]
                    )
                current[:] = [{"id": schedule["id"], "name": schedule["name"]}]
            else:
                current[:] = []
            return httpx.Response(204)

        # ----- incall update
        m = re.fullmatch(rf"{prefix}/incalls/(\d+)", path)
        if m and method == "PUT":
            incall = next((i for i in self.incalls if i["id"] == int(m.group(1))), None)
            if incall is None:
                return httpx.Response(404, json=["Resource Not Found - Incall"])
            if "destination" not in body:
                return httpx.Response(400, json=["Input Error - field 'destination'"])
            incall.update(body)
            return httpx.Response(204)

        # ----- voice menus
        if path == f"{prefix}/ivr" and method == "GET":
            return httpx.Response(
                200, json={"items": self.ivrs, "total": len(self.ivrs)}
            )
        if path == f"{prefix}/ivr" and method == "POST":
            if not body.get("name") or not body.get("menu_sound"):
                return httpx.Response(
                    400, json=["Input Error - field 'menu_sound': Missing data"]
                )
            for choice in body.get("choices") or []:
                if not re.fullmatch(r"[0-9*#]{1,255}", choice.get("exten", "")):
                    return httpx.Response(400, json=["Input Error - field 'exten'"])
            ivr = {"id": self._id(), "incalls": [], **body}
            self.ivrs.append(ivr)
            return httpx.Response(201, json=ivr)
        m = re.fullmatch(rf"{prefix}/ivr/(\d+)", path)
        if m:
            ivr = next((i for i in self.ivrs if i["id"] == int(m.group(1))), None)
            if ivr is None:
                return httpx.Response(404, json=["Resource Not Found - IVR"])
            if method == "GET":
                incalls = [
                    {"id": i["id"], "extensions": i["extensions"]}
                    for i in self.incalls
                    if (i.get("destination") or {}).get("type") == "ivr"
                    and i["destination"].get("ivr_id") == ivr["id"]
                ]
                return httpx.Response(200, json={**ivr, "incalls": incalls})
            if method == "PUT":
                if not body.get("menu_sound"):
                    return httpx.Response(400, json=["Input Error - menu_sound"])
                ivr.update(body)
                return httpx.Response(204)
            self.ivrs.remove(ivr)
            return httpx.Response(204)

        # ----- sounds
        if path == f"{prefix}/sounds" and method == "GET":
            items = [
                {"name": name, "tenant_uuid": TENANT} for name in self.sound_categories
            ] + [{"name": "system", "tenant_uuid": TENANT}]
            return httpx.Response(200, json={"items": items, "total": len(items)})
        if path == f"{prefix}/sounds" and method == "POST":
            name = body.get("name", "")
            if (
                not re.fullmatch(r"[a-zA-Z0-9][-_.a-zA-Z0-9]+", name)
                or name == "system"
            ):
                return httpx.Response(400, json=["Input Error - field 'name'"])
            if name in self.sound_categories:
                return httpx.Response(
                    400, json=["Resource Error - Sound already exists"]
                )
            self.sound_categories[name] = {}
            return httpx.Response(201, json={"name": name, "files": []})
        m = re.fullmatch(rf"{prefix}/sounds/([^/]+)", path)
        if m and method == "GET":
            category = m.group(1)
            if category not in self.sound_categories:
                return httpx.Response(404, json=["Resource Not Found - Sound"])
            wanted = request.url.params.get("file_name")
            files = [
                {
                    "name": name,
                    "formats": [
                        {
                            "format": "slin",
                            "language": None,
                            "path": f"/var/lib/wazo/sounds/tenants/{TENANT}/{category}/{name}",
                        }
                    ],
                }
                for name in self.sound_categories[category]
                if not wanted or name == wanted
            ]
            return httpx.Response(200, json={"name": category, "files": files})
        m = re.fullmatch(rf"{prefix}/sounds/([^/]+)/files/([^/]+)", path)
        if m:
            category, filename = m.group(1), m.group(2)
            if category not in self.sound_categories:
                return httpx.Response(404, json=["Resource Not Found - Sound"])
            if method == "PUT":
                if request.headers.get("content-type") != "application/octet-stream":
                    return httpx.Response(400, json=["Bad content type"])
                if request.content[:4] != b"RIFF":
                    return httpx.Response(400, json=["Not a WAV file"])
                self.sound_categories[category][filename] = request.content
                return httpx.Response(204)
            if self.sound_categories[category].pop(filename, None) is None:
                return httpx.Response(404, json=["Resource Not Found - Sound file"])
            return httpx.Response(204)

        # ----- operator lines
        if path == f"{prefix}/tenants/{TENANT}" and method == "GET":
            return httpx.Response(200, json=self.tenant_templates)
        if path == f"{prefix}/sip/transports":
            return httpx.Response(
                200, json={"items": self.transports, "total": len(self.transports)}
            )
        if path == f"{prefix}/endpoints/sip" and method == "POST":
            known = {t["uuid"] for t in self.templates} | {"tpl-trunk"}
            if any(t.get("uuid") not in known for t in body.get("templates") or []):
                return httpx.Response(
                    404, json=["Resource Not Found - EndpointSIPTemplate"]
                )
            endpoint = {"uuid": str(uuid.uuid4()), **body}
            self.endpoints_sip[endpoint["uuid"]] = endpoint
            return httpx.Response(201, json=endpoint)
        m = re.fullmatch(rf"{prefix}/endpoints/sip/([^/]+)", path)
        if m and method == "GET" and m.group(1) != "templates":
            endpoint = self.endpoints_sip.get(m.group(1)) or self.user_endpoints.get(
                m.group(1)
            )
            if endpoint is None:
                return httpx.Response(404, json=["Resource Not Found - EndpointSIP"])
            return httpx.Response(200, json=endpoint)
        if m and method == "PUT":
            # Like the engine: the body replaces the endpoint's editable fields.
            store = (
                self.endpoints_sip
                if m.group(1) in self.endpoints_sip
                else self.user_endpoints
            )
            current = store.get(m.group(1))
            if current is None:
                return httpx.Response(404, json=["Resource Not Found - EndpointSIP"])
            if "name" not in body:
                return httpx.Response(400, json=["Input Error - name: Missing data"])
            templates = {t["uuid"]: t for t in self.templates} | {
                t["uuid"]: t for t in current.get("templates") or []
            }
            store[m.group(1)] = {
                "uuid": current["uuid"],
                **body,
                "templates": [
                    templates.get(t["uuid"], t) for t in body.get("templates") or []
                ],
            }
            self.endpoint_updates.append(m.group(1))
            return httpx.Response(204)
        if m and method == "DELETE":
            if self.endpoints_sip.pop(m.group(1), None) is None:
                return httpx.Response(404, json=["Resource Not Found - EndpointSIP"])
            return httpx.Response(204)
        if path == f"{prefix}/trunks" and method == "GET":
            return httpx.Response(
                200, json={"items": self.trunks, "total": len(self.trunks)}
            )
        if path == f"{prefix}/trunks" and method == "POST":
            trunk = {
                "id": self._id(),
                "endpoint_sip": None,
                "outcalls": [],
                "context": body.get("context"),
                "outgoing_caller_id_format": body.get(
                    "outgoing_caller_id_format", "+E164"
                ),
            }
            self.trunks.append(trunk)
            return httpx.Response(201, json=trunk)
        m = re.fullmatch(rf"{prefix}/trunks/(\d+)", path)
        if m:
            trunk = next((t for t in self.trunks if t["id"] == int(m.group(1))), None)
            if trunk is None:
                return httpx.Response(404, json=["Resource Not Found - Trunk"])
            if method == "GET":
                return httpx.Response(200, json=trunk)
            self.trunks.remove(trunk)
            return httpx.Response(204)
        m = re.fullmatch(rf"{prefix}/trunks/(\d+)/endpoints/sip/([^/]+)", path)
        if m and method == "PUT":
            if self.fail_trunk_association:
                return httpx.Response(
                    400, json=["Resource Error - Trunk already associated"]
                )
            trunk = next((t for t in self.trunks if t["id"] == int(m.group(1))), None)
            endpoint = self.endpoints_sip.get(m.group(2))
            if trunk is None or endpoint is None:
                return httpx.Response(404, json=["Resource Not Found"])
            trunk["endpoint_sip"] = {
                "uuid": endpoint["uuid"],
                "label": endpoint.get("label"),
                "name": endpoint.get("name"),
                "auth_section_options": [
                    o
                    for o in endpoint.get("auth_section_options") or []
                    if o[0] == "username"
                ],
                "registration_section_options": [
                    o
                    for o in endpoint.get("registration_section_options") or []
                    if o[0] == "client_uri"
                ],
            }
            return httpx.Response(204)
        if path == f"{prefix}/outcalls" and method == "GET":
            return httpx.Response(
                200, json={"items": self.outcalls, "total": len(self.outcalls)}
            )
        if path == f"{prefix}/outcalls" and method == "POST":
            if not body.get("name"):
                return httpx.Response(400, json=["Input Error - field 'name'"])
            outcall = {"id": self._id(), "trunks": [], "extensions": [], **body}
            self.outcalls.append(outcall)
            return httpx.Response(201, json=outcall)
        m = re.fullmatch(rf"{prefix}/outcalls/(\d+)", path)
        if m and method == "DELETE":
            outcall = next(
                (o for o in self.outcalls if o["id"] == int(m.group(1))), None
            )
            if outcall is None:
                return httpx.Response(404, json=["Resource Not Found - Outcall"])
            self.outcalls.remove(outcall)
            for trunk in self.trunks:
                trunk["outcalls"] = [
                    o for o in trunk["outcalls"] if o["id"] != outcall["id"]
                ]
            return httpx.Response(204)
        m = re.fullmatch(rf"{prefix}/outcalls/(\d+)/trunks", path)
        if m and method == "PUT":
            outcall = next(
                (o for o in self.outcalls if o["id"] == int(m.group(1))), None
            )
            if outcall is None:
                return httpx.Response(404, json=["Resource Not Found - Outcall"])
            trunks = []
            for item in body.get("trunks") or []:
                trunk = next((t for t in self.trunks if t["id"] == item["id"]), None)
                if trunk is None:
                    return httpx.Response(404, json=["Resource Not Found - Trunk"])
                trunks.append(trunk)
            outcall["trunks"] = [
                {"id": t["id"], "endpoint_sip": t.get("endpoint_sip")} for t in trunks
            ]
            for trunk in trunks:
                trunk["outcalls"].append({"id": outcall["id"], "name": outcall["name"]})
            return httpx.Response(204)
        m = re.fullmatch(rf"{prefix}/outcalls/(\d+)/extensions/(\d+)", path)
        if m and method == "PUT":
            outcall = next(
                (o for o in self.outcalls if o["id"] == int(m.group(1))), None
            )
            extension = next(
                (e for e in self.extensions if e["id"] == int(m.group(2))), None
            )
            if outcall is None or extension is None:
                return httpx.Response(404, json=["Resource Not Found"])
            if extension["context"] != "to-extern":
                return httpx.Response(
                    400, json=["Resource Error - not an outcall context"]
                )
            outcall["extensions"].append({**body, **extension})
            return httpx.Response(204)
        # ----- call restrictions
        if path == f"{prefix}/callpermissions" and method == "GET":
            return httpx.Response(
                200,
                json={
                    "items": self.call_permissions,
                    "total": len(self.call_permissions),
                },
            )
        if path == f"{prefix}/callpermissions" and method == "POST":
            if not body.get("name") or body.get("mode") not in ("allow", "deny"):
                return httpx.Response(400, json=["Input Error - field 'name'"])
            if any(
                not re.fullmatch(r"(?:_?\+?[0-9NXZ*#\-\[\]]+[.!]?){1,40}", e)
                for e in body.get("extensions") or []
            ):
                return httpx.Response(400, json=["Input Error - field 'extensions'"])
            permission = {
                "id": self._id(),
                "users": [],
                "outcalls": [],
                "groups": [],
                **body,
            }
            self.call_permissions.append(permission)
            return httpx.Response(201, json=permission)
        m = re.fullmatch(rf"{prefix}/callpermissions/(\d+)", path)
        if m:
            permission = next(
                (p for p in self.call_permissions if p["id"] == int(m.group(1))), None
            )
            if permission is None:
                return httpx.Response(404, json=["Resource Not Found - CallPermission"])
            if method == "GET":
                return httpx.Response(200, json=permission)
            self.call_permissions.remove(permission)
            return httpx.Response(204)
        m = re.fullmatch(rf"{prefix}/users/(\d+)/callpermissions/(\d+)", path)
        if m:
            user = next((u for u in self.users if u.get("id") == int(m.group(1))), None)
            permission = next(
                (p for p in self.call_permissions if p["id"] == int(m.group(2))), None
            )
            if user is None or permission is None:
                return httpx.Response(404, json=["Resource Not Found"])
            members = permission["users"]
            members[:] = [x for x in members if x["uuid"] != user["uuid"]]
            if method == "PUT":
                members.append(
                    {
                        "uuid": user["uuid"],
                        "firstname": user.get("firstname"),
                        "lastname": user.get("lastname"),
                    }
                )
            return httpx.Response(204)

        # ----- single user (partial update, as the engine does)
        m = re.fullmatch(rf"{prefix}/users/([0-9a-z-]+)", path)
        if m and method in ("GET", "PUT") and not m.group(1).isdigit():
            user = next((u for u in self.users if u["uuid"] == m.group(1)), None)
            if user is None:
                return httpx.Response(404, json=["Resource Not Found - User"])
            settings = self.user_settings.setdefault(user["uuid"], {})
            if method == "GET":
                return httpx.Response(200, json={**user, **settings})
            if "firstname" in body and not body["firstname"]:
                return httpx.Response(400, json=["Input Error - firstname"])
            settings.update(body)
            return httpx.Response(204)

        # ----- call groups
        if path == f"{prefix}/groups" and method == "GET":
            return httpx.Response(
                200, json={"items": self.groups, "total": len(self.groups)}
            )
        if path == f"{prefix}/groups" and method == "POST":
            if not re.fullmatch(r"[-_.a-zA-Z0-9 ]+", body.get("label") or ""):
                return httpx.Response(400, json=["Input Error - field 'label'"])
            group = {
                "id": self._id(),
                "uuid": str(uuid.uuid4()),
                "name": f"grp-{self._next}",
                "extensions": [],
                "members": {"users": [], "extensions": []},
                "fallbacks": {
                    "noanswer_destination": None,
                    "congestion_destination": None,
                },
                **body,
            }
            self.groups.append(group)
            return httpx.Response(201, json=group)
        m = re.fullmatch(rf"{prefix}/groups/([0-9a-f-]+)(/.*)?", path)
        if m:
            group = next((g for g in self.groups if g["uuid"] == m.group(1)), None)
            if group is None:
                return httpx.Response(404, json=["Resource Not Found - Group"])
            rest = m.group(2) or ""
            if rest == "" and method == "GET":
                return httpx.Response(200, json=group)
            if rest == "" and method == "DELETE":
                self.groups.remove(group)
                return httpx.Response(204)
            if rest == "/members/users" and method == "PUT":
                users = []
                for member in body.get("users") or []:
                    user = next(
                        (u for u in self.users if u["uuid"] == member["uuid"]), None
                    )
                    if user is None:
                        return httpx.Response(404, json=["Resource Not Found - User"])
                    users.append(
                        {
                            "uuid": user["uuid"],
                            "firstname": user.get("firstname"),
                            "lastname": user.get("lastname"),
                            "priority": member.get("priority", 0),
                        }
                    )
                group["members"]["users"] = users
                return httpx.Response(204)
            em = re.fullmatch(r"/extensions/(\d+)", rest)
            if em and method == "PUT":
                extension = next(
                    (e for e in self.extensions if e["id"] == int(em.group(1))), None
                )
                if extension is None:
                    return httpx.Response(404, json=["Resource Not Found - Extension"])
                group["extensions"].append(extension)
                return httpx.Response(204)
            if rest == "/fallbacks" and method == "PUT":
                group["fallbacks"].update(body)
                return httpx.Response(204)

        # ----- forwards, services, fallbacks
        m = re.fullmatch(rf"{prefix}/users/(\d+)/(forwards|services|fallbacks)", path)
        if m:
            user_id = int(m.group(1))
            if not any(u.get("id") == user_id for u in self.users):
                return httpx.Response(404, json=["Resource Not Found - User"])
            store = {
                "forwards": self.user_forwards,
                "services": self.user_services,
                "fallbacks": self.user_fallbacks,
            }[m.group(2)]
            if method == "GET":
                defaults = {
                    "forwards": {
                        k: {"enabled": False, "destination": None}
                        for k in ("busy", "noanswer", "unconditional")
                    },
                    "services": {
                        "dnd": {"enabled": False},
                        "incallfilter": {"enabled": False},
                    },
                    "fallbacks": {
                        k: None
                        for k in (
                            "noanswer_destination",
                            "busy_destination",
                            "congestion_destination",
                            "fail_destination",
                        )
                    },
                }[m.group(2)]
                return httpx.Response(200, json={**defaults, **store.get(user_id, {})})
            if m.group(2) == "forwards":
                for forward in body.values():
                    if forward.get("enabled") and not forward.get("destination"):
                        return httpx.Response(400, json=["Input Error - destination"])
            store[user_id] = body
            return httpx.Response(204)

        # ----- call pickup groups, parking lots, paging
        users_by_uuid = {u["uuid"]: u for u in self.users}
        for kind, roles in (
            ("callpickups", ("interceptors", "targets")),
            ("pagings", ("members", "callers")),
        ):
            store = getattr(self, kind)
            if path == f"{prefix}/{kind}" and method == "GET":
                return httpx.Response(200, json={"items": store, "total": len(store)})
            if path == f"{prefix}/{kind}" and method == "POST":
                if kind == "pagings" and any(
                    x["number"] == body.get("number") for x in store
                ):
                    return httpx.Response(
                        400, json=["Resource Error - Paging already exists"]
                    )
                item = {"id": self._id(), **body, **{r: {"users": []} for r in roles}}
                store.append(item)
                return httpx.Response(201, json=item)
            m = re.fullmatch(rf"{prefix}/{kind}/(\d+)", path)
            if m and method == "DELETE":
                item = next((x for x in store if x["id"] == int(m.group(1))), None)
                if item is None:
                    return httpx.Response(404, json=["Resource Not Found"])
                store.remove(item)
                return httpx.Response(204)
            m = re.fullmatch(rf"{prefix}/{kind}/(\d+)/(\w+)/users", path)
            if m and method == "PUT" and m.group(2) in roles:
                item = next((x for x in store if x["id"] == int(m.group(1))), None)
                if item is None:
                    return httpx.Response(404, json=["Resource Not Found"])
                for u in body.get("users") or []:
                    if u.get("uuid") not in users_by_uuid:
                        return httpx.Response(404, json=["Resource Not Found - User"])
                item[m.group(2)] = {
                    "users": [
                        {
                            "uuid": u["uuid"],
                            "firstname": users_by_uuid[u["uuid"]].get("firstname"),
                            "lastname": users_by_uuid[u["uuid"]].get("lastname"),
                        }
                        for u in body.get("users") or []
                    ]
                }
                return httpx.Response(204)
        if path == f"{prefix}/parkinglots" and method == "GET":
            return httpx.Response(
                200, json={"items": self.parkinglots, "total": len(self.parkinglots)}
            )
        if path == f"{prefix}/parkinglots" and method == "POST":
            lot = {"id": self._id(), "extensions": [], **body}
            self.parkinglots.append(lot)
            return httpx.Response(201, json=lot)
        m = re.fullmatch(rf"{prefix}/parkinglots/(\d+)", path)
        if m and method == "DELETE":
            lot = next(
                (x for x in self.parkinglots if x["id"] == int(m.group(1))), None
            )
            if lot is None:
                return httpx.Response(404, json=["Resource Not Found - ParkingLot"])
            self.parkinglots.remove(lot)
            return httpx.Response(204)
        m = re.fullmatch(rf"{prefix}/parkinglots/(\d+)/extensions/(\d+)", path)
        if m and method == "PUT":
            lot = next(
                (x for x in self.parkinglots if x["id"] == int(m.group(1))), None
            )
            extension = next(
                (e for e in self.extensions if e["id"] == int(m.group(2))), None
            )
            if lot is None or extension is None:
                return httpx.Response(404, json=["Resource Not Found"])
            lot["extensions"] = [{"id": extension["id"], "exten": extension["exten"]}]
            return httpx.Response(204)
        m = re.fullmatch(rf"{prefix}/outcalls/(\d+)/schedules/(\d+)", path)
        if m and method in {"PUT", "DELETE"}:
            outcall = next(
                (o for o in self.outcalls if o["id"] == int(m.group(1))), None
            )
            schedule = next(
                (x for x in self.schedules if x["id"] == int(m.group(2))), None
            )
            if outcall is None or schedule is None:
                return httpx.Response(404, json=["Resource Not Found"])
            current = outcall.setdefault("schedules", [])
            if method == "PUT":
                if current and current[0]["id"] != schedule["id"]:
                    return httpx.Response(
                        400, json=["Resource Error - Outcall already has a schedule"]
                    )
                outcall["schedules"] = [
                    {"id": schedule["id"], "name": schedule.get("name")}
                ]
            else:
                outcall["schedules"] = [x for x in current if x["id"] != schedule["id"]]
            return httpx.Response(204)

        # ----- conferences
        if path == f"{prefix}/conferences" and method == "GET":
            return httpx.Response(
                200, json={"items": self.conferences, "total": len(self.conferences)}
            )
        if path == f"{prefix}/conferences" and method == "POST":
            for pin in (body.get("pin"), body.get("admin_pin")):
                if pin is not None and not str(pin).isdigit():
                    return httpx.Response(400, json=["Input Error - field 'pin'"])
            conference = {"id": self._id(), "extensions": [], **body}
            self.conferences.append(conference)
            return httpx.Response(201, json=conference)
        m = re.fullmatch(rf"{prefix}/conferences/(\d+)", path)
        if m and method == "DELETE":
            conference = next(
                (c for c in self.conferences if c["id"] == int(m.group(1))), None
            )
            if conference is None:
                return httpx.Response(404, json=["Resource Not Found - Conference"])
            self.conferences.remove(conference)
            return httpx.Response(204)
        m = re.fullmatch(rf"{prefix}/conferences/(\d+)/extensions/(\d+)", path)
        if m and method == "PUT":
            conference = next(
                (c for c in self.conferences if c["id"] == int(m.group(1))), None
            )
            extension = next(
                (e for e in self.extensions if e["id"] == int(m.group(2))), None
            )
            if conference is None or extension is None:
                return httpx.Response(404, json=["Resource Not Found"])
            conference["extensions"].append(extension)
            return httpx.Response(204)
        m = re.fullmatch(
            r"/api/calld/1.0/conferences/(\d+)/participants(?:/([^/]+)(?:/(mute|unmute))?)?",
            path,
        )
        if m:
            conference_id = int(m.group(1))
            if not any(c["id"] == conference_id for c in self.conferences):
                return httpx.Response(404, json={"message": "No such conference"})
            people = self.participants.get(conference_id, [])
            if m.group(2) is None:
                return httpx.Response(200, json={"items": people, "total": len(people)})
            participant = next((p for p in people if p["id"] == m.group(2)), None)
            if participant is None:
                return httpx.Response(404, json={"message": "No such participant"})
            action = m.group(3) or "kick"
            self.participant_actions.append((conference_id, participant["id"], action))
            if action == "kick":
                people.remove(participant)
            else:
                participant["muted"] = action == "mute"
            return httpx.Response(204)

        if path == "/api/calld/1.0/trunks":
            items = [
                {
                    "id": t["id"],
                    "technology": "sip",
                    "name": (t.get("endpoint_sip") or {}).get("name"),
                    **self.trunk_status.get(
                        t["id"], {"registered": False, "current_call_count": 0}
                    ),
                }
                for t in self.trunks
            ]
            return httpx.Response(200, json={"items": items, "total": len(items)})

        if path == "/api/chatd/1.0/users/presences" and method == "GET":
            return httpx.Response(
                200, json={"items": self.presences, "total": len(self.presences)}
            )
        m = re.fullmatch(r"/api/chatd/1\.0/users/([^/]+)/presences", path)
        if m and method == "PUT":
            for presence in self.presences:
                if presence["uuid"] == m.group(1):
                    presence.update(
                        {k: body[k] for k in ("state", "status") if k in body}
                    )
                    return httpx.Response(204)
            return httpx.Response(404, json={"message": "No such user"})
        if path == "/api/calld/1.0/calls" and method == "POST":
            source_user = (body.get("source") or {}).get("user")
            destination = body.get("destination") or {}
            if not any(u["uuid"] == source_user for u in self.users):
                return httpx.Response(
                    400, json={"message": "No such user", "error_id": "invalid-user"}
                )
            if not {"context", "extension", "priority"} <= destination.keys():
                return httpx.Response(400, json={"message": "Invalid destination"})
            call = {
                "call_id": f"orig-{len(self.originated) + 1}",
                "user_uuid": source_user,
            }
            self.originated.append(body)
            return httpx.Response(201, json=call)
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
        m = re.fullmatch(r"/api/calld/1.0/parkinglots/(\d+)", path)
        if m and method == "GET":
            # wazo-calld: the lot with its waiting calls, this tenant only.
            lot = next(
                (x for x in self.parkinglots if x["id"] == int(m.group(1))), None
            )
            if lot is None:
                return httpx.Response(404, json={"message": "No such parking lot"})
            calls = [p for p in self.parked if p.get("lot_id") == lot["id"]]
            return httpx.Response(
                200,
                json={
                    "id": lot["id"],
                    "name": lot.get("name"),
                    "slots_start": lot.get("slots_start"),
                    "slots_end": lot.get("slots_end"),
                    "calls": calls,
                },
            )
        if (
            path.startswith("/api/amid/")
            and self.amid_master_only
            and request.headers.get("x-auth-token") not in self.master_tokens
        ):
            return httpx.Response(
                401, json={"reason": ["Unauthorized"], "status_code": 401}
            )
        if path == "/api/amid/1.0/action/QueueStatus" and method == "POST":
            name = (body or {}).get("Queue")
            known = {q["name"] for q in self.queues}
            messages: list[dict] = [
                {
                    "Response": "Success",
                    "EventList": "start",
                    "Message": "Queue status will follow",
                }
            ]
            if name in known:
                entries = self.queue_entries.get(name, [])
                messages.append(
                    {
                        "Event": "QueueParams",
                        "Queue": name,
                        "Max": "0",
                        "Strategy": "ringall",
                        "Calls": str(len(entries)),
                        "Holdtime": "18",
                        "TalkTime": "160",
                        **self.queue_params.get(name, {}),
                    }
                )
                queue = next(q for q in self.queues if q["name"] == name)
                for member in queue["members"]["agents"]:
                    agent = next(
                        (a for a in self.agents if a["id"] == member["id"]), None
                    )
                    if agent is None:
                        continue
                    status = next(
                        (s for s in self.statuses if s["id"] == agent["id"]), {}
                    )
                    messages.append(
                        {
                            "Event": "QueueMember",
                            "Queue": name,
                            "Name": f"Agent/{agent['number']}",
                            "StateInterface": f"Local/id-{agent['id']}@agentcallback",
                            "CallsTaken": "5",
                            "InCall": "1"
                            if any(c.get("user_uuid") == "u-1" for c in self.calls)
                            else "0",
                            "Status": "2",
                            "Paused": "1" if status.get("paused") else "0",
                            "PausedReason": status.get("paused_reason") or "",
                        }
                    )
                for entry in entries:
                    messages.append({"Event": "QueueEntry", "Queue": name, **entry})
            messages.append({"Event": "QueueStatusComplete", "EventList": "Complete"})
            return httpx.Response(200, json=messages)
        if path in (
            "/api/call-logd/1.0/queues/statistics",
            "/api/call-logd/1.0/agents/statistics",
        ):
            if request.headers.get("wazo-tenant") != TENANT:
                return httpx.Response(401, json={"message": "Unauthorized tenant"})
            self.stat_requests.append(dict(request.url.params))
            items = self.queue_stats if "queues" in path else self.agent_stats
            period = {
                "from": request.url.params.get("from"),
                "until": request.url.params.get("until"),
            }
            items = [{**period, **i} for i in items]
            return httpx.Response(200, json={"items": items, "total": len(items)})
        if path == "/api/call-logd/1.0/cdr":
            items = self.cdr
            if request.url.params.get("recorded") == "true":
                items = [c for c in items if c.get("recordings")]
            if request.url.params.get("from"):
                since = request.url.params["from"]
                items = [c for c in items if (c.get("start") or "") >= since]
            if request.url.params.get("direction") == "asc":
                items = sorted(items, key=lambda c: c.get("start") or "")
                offset = int(request.url.params.get("offset") or 0)
                limit = int(request.url.params.get("limit") or 1000)
                items = items[offset : offset + limit]
            if request.url.params.get("user_uuid"):
                wanted = request.url.params["user_uuid"]
                items = [
                    c
                    for c in items
                    if wanted
                    in (c.get("source_user_uuid"), c.get("destination_user_uuid"))
                ]
            return httpx.Response(
                200,
                json={"items": items, "total": len(self.cdr), "filtered": len(items)},
            )
        m = re.fullmatch(r"/api/call-logd/1.0/cdr/(\d+)/recordings/([^/]+)/media", path)
        if m:
            uuid_ = m.group(2)
            if uuid_ not in self.recording_media:
                return httpx.Response(404, json={"message": "No recording"})
            if method == "DELETE":
                del self.recording_media[uuid_]
                self.deleted_media.append(uuid_)
                return httpx.Response(204)
            return httpx.Response(
                200,
                content=self.recording_media[uuid_],
                headers={"Content-Type": "audio/wav"},
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
    from api.services.pbx import supervision

    monkeypatch.setattr(supervision, "PbxClient", factory)
    monkeypatch.setattr(service, "assert_pbx_url_allowed", lambda url: None)


def as_dict(value: Any) -> Any:
    return value
