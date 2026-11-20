"""Minimal Stripe integration over plain HTTPS (no SDK dependency).

Covers what a subscription platform needs: Checkout to subscribe, the
customer portal to manage payment methods, and webhooks to keep the local
subscription in sync. Stripe stays the source of truth for paid subscriptions;
the local row is what call authorization reads.
"""

from __future__ import annotations

import hashlib
import hmac
import time
from datetime import UTC, datetime
from typing import Any

import httpx
from loguru import logger

from api.constants import STRIPE_API_BASE, STRIPE_SECRET_KEY, STRIPE_WEBHOOK_SECRET
from api.db import db_client
from api.services.saas import subscription_service

WEBHOOK_TOLERANCE_SECONDS = 300

# Stripe subscription status -> local status.
STRIPE_STATUS_MAP = {
    "trialing": "trialing",
    "active": "active",
    "past_due": "past_due",
    "incomplete": "past_due",
    "unpaid": "suspended",
    "paused": "suspended",
    "incomplete_expired": "canceled",
    "canceled": "canceled",
}


class StripeNotConfigured(RuntimeError):
    pass


class StripeSignatureError(ValueError):
    pass


def is_configured() -> bool:
    return bool(STRIPE_SECRET_KEY)


async def _post(path: str, data: dict[str, Any]) -> dict:
    if not STRIPE_SECRET_KEY:
        raise StripeNotConfigured("STRIPE_SECRET_KEY is not set")
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(
            f"{STRIPE_API_BASE}/v1/{path}",
            data=data,
            auth=(STRIPE_SECRET_KEY, ""),
        )
    if response.status_code >= 400:
        logger.warning("Stripe {} failed: {}", path, response.text[:500])
        response.raise_for_status()
    return response.json()


async def create_checkout_session(
    *,
    organization_id: int,
    plan_code: str,
    price_id: str,
    success_url: str,
    cancel_url: str,
    customer_id: str | None = None,
    customer_email: str | None = None,
) -> str:
    data: dict[str, Any] = {
        "mode": "subscription",
        "line_items[0][price]": price_id,
        "line_items[0][quantity]": 1,
        "success_url": success_url,
        "cancel_url": cancel_url,
        "client_reference_id": str(organization_id),
        "metadata[organization_id]": str(organization_id),
        "metadata[plan_code]": plan_code,
        "subscription_data[metadata][organization_id]": str(organization_id),
        "subscription_data[metadata][plan_code]": plan_code,
        "allow_promotion_codes": "true",
    }
    if customer_id:
        data["customer"] = customer_id
    elif customer_email:
        data["customer_email"] = customer_email
    session = await _post("checkout/sessions", data)
    return session["url"]


async def create_portal_session(*, customer_id: str, return_url: str) -> str:
    session = await _post(
        "billing_portal/sessions", {"customer": customer_id, "return_url": return_url}
    )
    return session["url"]


def verify_webhook_signature(
    payload: bytes,
    signature_header: str,
    *,
    secret: str | None = None,
    now: float | None = None,
) -> None:
    """Raise StripeSignatureError unless the payload is signed by Stripe."""
    secret = secret or STRIPE_WEBHOOK_SECRET
    if not secret:
        raise StripeSignatureError("STRIPE_WEBHOOK_SECRET is not set")
    timestamp: int | None = None
    signatures: list[str] = []
    for part in (signature_header or "").split(","):
        key, _, value = part.strip().partition("=")
        if key == "t":
            try:
                timestamp = int(value)
            except ValueError:
                raise StripeSignatureError("Malformed timestamp") from None
        elif key == "v1":
            signatures.append(value)
    if timestamp is None or not signatures:
        raise StripeSignatureError("Missing timestamp or signature")
    now = time.time() if now is None else now
    if abs(now - timestamp) > WEBHOOK_TOLERANCE_SECONDS:
        raise StripeSignatureError("Timestamp outside tolerance")
    expected = hmac.new(
        secret.encode(), f"{timestamp}.".encode() + payload, hashlib.sha256
    ).hexdigest()
    if not any(hmac.compare_digest(expected, sig) for sig in signatures):
        raise StripeSignatureError("Signature mismatch")


def _ts(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    return datetime.fromtimestamp(int(value), tz=UTC)


def _subscription_period(obj: dict) -> tuple[datetime | None, datetime | None]:
    """Period bounds, from the subscription or (newer API) its first item."""
    start, end = obj.get("current_period_start"), obj.get("current_period_end")
    if start is None or end is None:
        items = (obj.get("items") or {}).get("data") or []
        if items:
            start = start or items[0].get("current_period_start")
            end = end or items[0].get("current_period_end")
    return _ts(start), _ts(end)


def _subscription_price_id(obj: dict) -> str | None:
    items = (obj.get("items") or {}).get("data") or []
    if not items:
        return None
    return (items[0].get("price") or {}).get("id")


async def _organization_id_for(obj: dict) -> int | None:
    metadata = obj.get("metadata") or {}
    raw = metadata.get("organization_id") or obj.get("client_reference_id")
    if raw:
        try:
            return int(raw)
        except (TypeError, ValueError):
            return None
    subscription_id = obj.get("subscription") or (
        obj.get("id") if obj.get("object") == "subscription" else None
    )
    existing = await db_client.find_organization_subscription_by_stripe(
        customer_id=obj.get("customer"), subscription_id=subscription_id
    )
    return existing.organization_id if existing else None


async def handle_event(event: dict) -> str:
    """Apply one verified Stripe event. Returns a short outcome label."""
    event_type = event.get("type", "")
    obj = (event.get("data") or {}).get("object") or {}
    organization_id = await _organization_id_for(obj)
    if organization_id is None:
        logger.info("Stripe event {} matches no organization; ignored", event_type)
        return "ignored"
    await subscription_service.ensure_organization_subscription(organization_id)

    if event_type == "checkout.session.completed":
        fields: dict[str, Any] = {
            "stripe_customer_id": obj.get("customer"),
            "stripe_subscription_id": obj.get("subscription"),
            "status": "active",
            "past_due_since": None,
        }
        email = (obj.get("customer_details") or {}).get("email")
        if email:
            fields["billing_email"] = email
        plan_code = (obj.get("metadata") or {}).get("plan_code")
        plan = (
            await db_client.get_subscription_plan_by_code(plan_code)
            if plan_code
            else None
        )
        if plan is not None:
            fields["plan_id"] = plan.id
        await db_client.update_organization_subscription(organization_id, fields)
        if plan is not None:
            updated = await db_client.get_organization_subscription(organization_id)
            await subscription_service.sync_concurrency_limit(organization_id, updated)
        return "checkout_completed"

    if event_type in {
        "customer.subscription.created",
        "customer.subscription.updated",
        "customer.subscription.deleted",
    }:
        status = (
            "canceled"
            if event_type == "customer.subscription.deleted"
            else STRIPE_STATUS_MAP.get(obj.get("status", ""), "past_due")
        )
        fields = {
            "status": status,
            "stripe_subscription_id": obj.get("id"),
            "stripe_customer_id": obj.get("customer"),
        }
        start, end = _subscription_period(obj)
        if start and end:
            fields["current_period_start"] = start
            fields["current_period_end"] = end
        if status == "past_due":
            current = await db_client.get_organization_subscription(organization_id)
            if current is None or current.past_due_since is None:
                fields["past_due_since"] = datetime.now(UTC)
        else:
            fields["past_due_since"] = None
        price_id = _subscription_price_id(obj)
        plan = (
            await db_client.get_subscription_plan_by_stripe_price(price_id)
            if price_id
            else None
        )
        if plan is not None:
            fields["plan_id"] = plan.id
        updated = await db_client.update_organization_subscription(
            organization_id, fields
        )
        if updated is not None:
            await subscription_service.sync_concurrency_limit(organization_id, updated)
        return f"subscription_{status}"

    if event_type == "invoice.payment_failed":
        current = await db_client.get_organization_subscription(organization_id)
        fields = {"status": "past_due"}
        if current is None or current.past_due_since is None:
            fields["past_due_since"] = datetime.now(UTC)
        await db_client.update_organization_subscription(organization_id, fields)
        return "payment_failed"

    if event_type in {"invoice.paid", "invoice.payment_succeeded"}:
        await db_client.update_organization_subscription(
            organization_id, {"status": "active", "past_due_since": None}
        )
        return "payment_succeeded"

    return "ignored"
