"""Turning transfer destinations into Asterisk dial strings, tenant-safely.

AI agents hand a caller to humans with the destination ``queue:<slug>``. The
slug is resolved against the queues of the organization that owns the call,
so a tenant can only ever reach its own queues: the generated Asterisk
dialplan has one explicit extension per tenant queue and nothing else.
"""

from __future__ import annotations

import re

from api.constants import SAAS_MODE
from api.services.telephony.providers.ari.dial_string import (
    build_dial_string,
    has_channel_technology,
)

QUEUE_PREFIX = "queue:"
QUEUE_DIALPLAN_CONTEXT = "nimbora-queues"
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,46}$")


class ContactCenterDestinationError(ValueError):
    """The destination is not allowed or does not exist for this tenant."""


def queue_asterisk_name(organization_id: int, slug: str) -> str:
    """Name of a tenant queue inside the shared Asterisk (``t<org>-<slug>``)."""
    return f"t{int(organization_id)}-{slug}"


def queue_dial_string(organization_id: int, slug: str) -> str:
    return (
        f"Local/{queue_asterisk_name(organization_id, slug)}@{QUEUE_DIALPLAN_CONTEXT}"
    )


def parse_queue_destination(destination: str) -> str | None:
    destination = (destination or "").strip()
    if not destination.lower().startswith(QUEUE_PREFIX):
        return None
    slug = destination[len(QUEUE_PREFIX) :].strip().lower()
    if not SLUG_RE.match(slug):
        raise ContactCenterDestinationError(f"Invalid queue name: {slug!r}")
    return slug


def assert_tenant_may_dial(destination: str) -> None:
    """In SAAS_MODE, refuse raw channel destinations (``PJSIP/…``, ``Local/…``).

    Those would let one tenant ring another tenant's agents or enter internal
    dialplan contexts of the shared Asterisk. Tenants dial numbers (routed by
    the operator's dial-string template) or their own ``queue:<slug>``.
    """
    if SAAS_MODE and has_channel_technology(destination or ""):
        raise ContactCenterDestinationError(
            "Raw channel destinations are not allowed on this platform; "
            "use a phone number or queue:<name>."
        )


async def resolve_transfer_dial_string(
    destination: str,
    *,
    organization_id: int | None,
    dial_string_template: str,
    ari_endpoint: str | None = None,
) -> str:
    # "pbx-queue:<id>" / "pbx-extension:<n>": the company's enterprise PBX,
    # reachable only when the call runs on that PBX's Asterisk.
    from api.services.pbx import handoff as pbx_handoff

    pbx_target = pbx_handoff.parse_destination(destination)
    if pbx_target is not None:
        if organization_id is None:
            raise ContactCenterDestinationError(
                "PBX transfers need the call's organization"
            )
        target = await pbx_handoff.resolve(
            int(organization_id), *pbx_target, ari_endpoint=ari_endpoint
        )
        return target.dial_string
    slug = parse_queue_destination(destination)
    if slug is None:
        assert_tenant_may_dial(destination)
        return build_dial_string(destination, dial_string_template)
    if organization_id is None:
        raise ContactCenterDestinationError(
            "Queue transfers need the call's organization"
        )
    from api.db import db_client

    queue = await db_client.get_contact_center_queue_by_slug(int(organization_id), slug)
    if queue is None or not queue.is_active:
        raise ContactCenterDestinationError(f"Unknown or inactive queue: {slug}")
    return queue_dial_string(int(organization_id), slug)
