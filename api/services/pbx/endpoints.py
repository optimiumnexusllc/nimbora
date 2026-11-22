"""SIP endpoints of extensions: write one back, and repair browser lines.

A browser line (NIMBORA Softphone, WebRTC) must carry the engine's « webrtc »
template alone: it already inherits « global ». Lines created before lab
step 14 listed both, « global » last, which forced transport-udp: the engine
could not ring the browser at all (« Unsuitable transport selected to reach
destination », bug 23). ``repair_templates`` gives the fix for one endpoint.
"""

from __future__ import annotations

from typing import Any

# Fields of a SIP endpoint the engine accepts back on PUT (the rest is read-only
# or derived). Templates and transport are references: only their uuid goes.
ENDPOINT_FIELDS = (
    "name",
    "label",
    "asterisk_id",
    "aor_section_options",
    "auth_section_options",
    "endpoint_section_options",
    "identify_section_options",
    "registration_section_options",
    "registration_outbound_auth_section_options",
    "outbound_auth_section_options",
)


def endpoint_body(
    endpoint: dict[str, Any], templates: list[dict] | None = None
) -> dict:
    """The whole endpoint, as a PUT body that changes nothing by itself."""
    body = {k: endpoint[k] for k in ENDPOINT_FIELDS if k in endpoint}
    body["auth_section_options"] = [
        list(o) for o in endpoint.get("auth_section_options") or []
    ]
    body["templates"] = [
        {"uuid": t["uuid"]}
        for t in (
            templates if templates is not None else endpoint.get("templates") or []
        )
        if t.get("uuid")
    ]
    if (endpoint.get("transport") or {}).get("uuid"):
        body["transport"] = {"uuid": endpoint["transport"]["uuid"]}
    return body


def with_password(endpoint: dict[str, Any], password: str) -> dict:
    body = endpoint_body(endpoint)
    auth = body["auth_section_options"]
    if any(o[0] == "password" for o in auth):
        body["auth_section_options"] = [
            [k, password if k == "password" else v] for k, v in auth
        ]
    else:
        auth.append(["password", password])
    return body


def repair_templates(endpoint: dict[str, Any]) -> list[dict] | None:
    """The templates a browser line should have, or None when it is fine."""
    templates = endpoint.get("templates") or []
    labels = [(t.get("label") or "").lower() for t in templates]
    if "webrtc" not in labels or "global" not in labels:
        return None
    return [t for t, label in zip(templates, labels, strict=True) if label != "global"]
