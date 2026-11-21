"""Verified customer identity for the web chat widget.

The widget's context comes from the host page, which the visitor controls:
an unverified phone number must never unlock someone's history. The
business's own backend signs the logged-in customer's phone number:

    customer_signature = hex(HMAC_SHA256(identity_secret, normalized_phone))

and passes ``customer_phone`` + ``customer_signature`` as widget context.
Only a valid signature links the chat to the customer (memory, history).
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from typing import Any

from api.enums import OrganizationConfigurationKey

SETTING_KEY = OrganizationConfigurationKey.CUSTOMER_IDENTITY_SECRET.value
PHONE_KEYS = ("customer_phone", "phone", "phone_number")


async def get_identity_secret(
    organization_id: int, *, create: bool = False
) -> str | None:
    from api.db import db_client

    value = await db_client.get_configuration_value(organization_id, SETTING_KEY)
    secret = (value or {}).get("secret") if isinstance(value, dict) else None
    if secret or not create:
        return secret
    secret = secrets.token_hex(32)
    await db_client.upsert_configuration(
        organization_id, SETTING_KEY, {"secret": secret}
    )
    return secret


async def rotate_identity_secret(organization_id: int) -> str:
    from api.db import db_client

    secret = secrets.token_hex(32)
    await db_client.upsert_configuration(
        organization_id, SETTING_KEY, {"secret": secret}
    )
    return secret


def sign_phone(secret: str, phone: str) -> str:
    return hmac.new(secret.encode(), phone.encode(), hashlib.sha256).hexdigest()


async def verified_web_identity(
    organization_id: int, context: dict[str, Any]
) -> str | None:
    """The normalized phone if the widget context carries a valid signature."""
    from api.services.customer_memory.service import normalize_phone

    signature = str(context.get("customer_signature") or "").strip().lower()
    raw_phone = next((context.get(k) for k in PHONE_KEYS if context.get(k)), None)
    phone = normalize_phone(raw_phone) if raw_phone else None
    if not signature or not phone:
        return None
    secret = await get_identity_secret(organization_id)
    if not secret:
        return None
    if not hmac.compare_digest(sign_phone(secret, phone), signature):
        return None
    return phone
