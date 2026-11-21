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
        self.contexts = [
            {"id": 1, "name": "from-extern", "type": "incall", "tenant_uuid": TENANT},
            {"id": 2, "name": "default", "type": "internal", "tenant_uuid": TENANT},
            {"id": 3, "name": "to-extern", "type": "outcall", "tenant_uuid": TENANT},
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
        self.endpoints_sip: dict[str, dict] = {}
        self.trunks: list[dict] = []
        self.trunk_status: dict[int, dict] = {}
        self.outcalls: list[dict] = []
        self.fail_trunk_association = False
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
            user = {"uuid": str(uuid.uuid4()), "id": self._id(), **body}
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
                    "uuid": user["uuid"],
                    "firstname": body["firstname"],
                    "lastname": body.get("lastname"),
                    "extension": (body.get("lines") or [{}])[0]
                    .get("extensions", [{}])[0]
                    .get("exten"),
                    "email": body.get("email"),
                    "enabled": True,
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
