"""Shared pieces of the agent actions (calendar, messages, tickets)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

TEMPLATE_RE = re.compile(r"\{\{\s*([a-zA-Z0-9_.]+)\s*\}\}")


class ActionError(RuntimeError):
    """An action that cannot be done; the message is safe to give the agent."""


@dataclass
class ActionContext:
    organization_id: int
    tool_uuid: str
    tool_name: str
    workflow_run_id: int | None = None
    initial_context: dict[str, Any] = field(default_factory=dict)
    gathered_context: dict[str, Any] = field(default_factory=dict)
    now: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def caller_phone(self) -> str | None:
        from api.services.customer_memory.service import (
            customer_phone_from_context,
            normalize_phone,
        )

        return (
            normalize_phone(customer_phone_from_context(self.initial_context)) or None
        )

    @property
    def customer_name(self) -> str | None:
        for source in (self.gathered_context, self.initial_context):
            name = source.get("customer_name")
            if isinstance(name, str) and name.strip():
                return name.strip()
        return None

    def variables(self) -> dict[str, Any]:
        merged = {**self.initial_context, **self.gathered_context}
        merged.setdefault("customer_name", self.customer_name or "")
        return merged


def render_template(text: str, variables: dict[str, Any]) -> str:
    """{{name}} placeholders; unknown variables render empty, never as raw braces."""

    def replace(match: re.Match) -> str:
        value: Any = variables
        for part in match.group(1).split("."):
            value = value.get(part) if isinstance(value, dict) else None
        return "" if value is None else str(value)

    rendered = TEMPLATE_RE.sub(replace, text)
    return re.sub(r"[ \t]{2,}", " ", rendered).strip()


async def load_credential(
    organization_id: int, credential_uuid: str | None
) -> tuple[str, dict]:
    if not credential_uuid:
        raise ActionError("No credential configured for this tool")
    from api.db import db_client

    credential = await db_client.get_credential_by_uuid(
        credential_uuid, organization_id
    )
    if credential is None:
        raise ActionError("The credential configured for this tool no longer exists")
    return str(credential.credential_type), dict(credential.credential_data or {})


def basic_auth_pair(credential_type: str, data: dict) -> tuple[str, str]:
    if credential_type != "basic_auth" or not data.get("username"):
        raise ActionError("This tool needs a username/password (basic auth) credential")
    return str(data["username"]), str(data.get("password") or "")


def check_outbound_url(url: str, field_name: str) -> None:
    """Multi-tenant SSRF guard (same rule as HTTP tools)."""
    from api.utils.url_security import validate_user_configured_service_url

    try:
        validate_user_configured_service_url(url, field_name=field_name)
    except ValueError as exc:
        raise ActionError(str(exc)) from exc
