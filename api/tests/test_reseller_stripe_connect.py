"""Stripe Connect (Express) for resellers.

The reseller connects its Stripe account from its console; its companies then
pay online: the subscription lives on the platform's account, each payment
goes to the reseller (transfer_data.destination, on_behalf_of) minus the
platform's commission (application_fee_percent). Stripe is faked at the HTTP
level and records what the platform sends.
"""

import hashlib
import hmac
import json
import time
import types
import urllib.parse
import uuid

import httpx
import pytest

from api.services.saas import stripe_billing, subscription_service
from api.tests.test_resellers import (  # noqa: F401 - fixtures
    _accept,
    _offer,
    _reseller,
    _user,
    as_user,
    saas_on,
)


class FakeStripe:
    def __init__(self):
        self.requests: list[tuple[str, str, dict]] = []
        self.account = {"charges_enabled": False, "details_submitted": False}
        self.accounts_created = 0

    def handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        data = (
            dict(urllib.parse.parse_qsl(request.content.decode()))
            if request.content
            else {}
        )
        self.requests.append((request.method, path, data))
        if path == "/v1/accounts" and request.method == "POST":
            self.accounts_created += 1
            return httpx.Response(200, json={"id": "acct_reseller1", **self.account})
        if path == "/v1/accounts/acct_reseller1" and request.method == "GET":
            return httpx.Response(200, json={"id": "acct_reseller1", **self.account})
        if path == "/v1/account_links":
            return httpx.Response(
                200, json={"url": "https://connect.stripe.test/setup/abc"}
            )
        if path == "/v1/accounts/acct_reseller1/login_links":
            if not self.account["details_submitted"]:
                # Stripe refuses a login link before onboarding is submitted.
                return httpx.Response(
                    400, json={"error": {"type": "invalid_request_error"}}
                )
            return httpx.Response(
                200, json={"url": "https://connect.stripe.test/express/xyz"}
            )
        if path == "/v1/checkout/sessions":
            return httpx.Response(
                200, json={"url": "https://checkout.stripe.test/c/pay"}
            )
        return httpx.Response(404, json={"error": {"message": f"unknown {path}"}})

    def sent(self, path: str) -> dict:
        return [data for _, p, data in self.requests if p == path][-1]


@pytest.fixture
def stripe(monkeypatch):
    fake = FakeStripe()
    # Only the Stripe module talks to the fake (the test client keeps httpx).
    fake_httpx = types.SimpleNamespace(**vars(httpx))
    fake_httpx.AsyncClient = lambda **kwargs: httpx.AsyncClient(
        transport=httpx.MockTransport(fake.handle), **kwargs
    )
    monkeypatch.setattr(stripe_billing, "httpx", fake_httpx)
    monkeypatch.setattr(stripe_billing, "STRIPE_SECRET_KEY", "sk_test_platform")
    monkeypatch.setattr(stripe_billing, "STRIPE_WEBHOOK_SECRET", "whsec_platform")
    monkeypatch.setattr(
        stripe_billing, "STRIPE_CONNECT_WEBHOOK_SECRET", "whsec_connect"
    )
    return fake


async def _reseller_with_company(db, as_user, commission=20):
    await subscription_service.ensure_default_plans()
    root = await _user(db, superuser=True)
    async with as_user(root) as client:
        created = await _reseller(client, commission=commission)
        accepted = await _accept(client, created["invitation_url"])
    admin = await db.get_user_by_id(accepted.json()["user"]["id"])
    async with as_user(admin) as client:
        code = await _offer(client)
        made = (
            await client.post(
                "/api/v1/reseller/companies",
                json={
                    "company_name": "Pharmacie Mensah",
                    "owner_email": f"{uuid.uuid4().hex[:6]}@mensah.example",
                    "plan_code": code,
                },
            )
        ).json()
    async with as_user(admin) as client:
        owner_response = await _accept(client, made["invitation_url"])
    owner = await db.get_user_by_id(owner_response.json()["user"]["id"])
    owner.selected_organization_id = made["company"]["organization_id"]
    return created["reseller"], admin, owner, code, made["company"]["organization_id"]


async def test_reseller_connects_its_stripe_express_account(
    db_session, saas_on, stripe, as_user
):
    _, admin, _, _, _ = await _reseller_with_company(db_session, as_user)
    async with as_user(admin) as client:
        first = await client.post("/api/v1/reseller/stripe/onboarding")
        again = await client.post("/api/v1/reseller/stripe/onboarding")
        state = (await client.get("/api/v1/reseller/stripe")).json()
        assert (await client.get("/api/v1/reseller")).json()["stripe_ready"] is False

        stripe.account = {"charges_enabled": True, "details_submitted": True}
        ready = (await client.get("/api/v1/reseller/stripe")).json()
        dashboard = await client.post("/api/v1/reseller/stripe/dashboard")
        assert (await client.get("/api/v1/reseller")).json()["stripe_ready"] is True

    assert first.status_code == 200 and first.json()["url"].startswith(
        "https://connect.stripe.test/"
    )
    assert again.status_code == 200
    assert stripe.accounts_created == 1  # the same account is reused
    account = stripe.sent("/v1/accounts")
    assert account["type"] == "express"
    assert account["capabilities[card_payments][requested]"] == "true"
    assert account["capabilities[transfers][requested]"] == "true"
    assert account["metadata[reseller_id]"]
    link = stripe.sent("/v1/account_links")
    assert link["account"] == "acct_reseller1" and link["type"] == "account_onboarding"
    assert link["return_url"].endswith("/reseller?stripe=return")
    assert link["refresh_url"].endswith("/reseller?stripe=refresh")
    assert state == {
        "connected": True,
        "charges_enabled": False,
        "details_submitted": False,
    }
    assert ready["charges_enabled"] is True
    assert dashboard.json()["url"].startswith("https://connect.stripe.test/express/")


async def test_company_pays_its_reseller_minus_the_commission(
    db_session, saas_on, stripe, as_user
):
    reseller, admin, owner, code, org_id = await _reseller_with_company(
        db_session, as_user, commission=17.5
    )
    async with as_user(owner) as client:
        early = await client.post("/api/v1/saas/checkout", json={"plan_code": code})
        assert early.status_code == 409
        assert "revendeur" in early.json()["detail"]

    async with as_user(admin) as client:
        await client.post("/api/v1/reseller/stripe/onboarding")
    stripe.account = {"charges_enabled": True, "details_submitted": True}
    async with as_user(admin) as client:
        await client.get("/api/v1/reseller/stripe")

    async with as_user(owner) as client:
        offers = (await client.get("/api/v1/saas/subscription/plans")).json()
        assert [p["code"] for p in offers] == [code]
        paid = await client.post("/api/v1/saas/checkout", json={"plan_code": code})
        platform_plan = await client.post(
            "/api/v1/saas/checkout", json={"plan_code": "business"}
        )
    assert paid.status_code == 200, paid.text
    assert paid.json()["url"] == "https://checkout.stripe.test/c/pay"
    assert platform_plan.status_code == 404

    session = stripe.sent("/v1/checkout/sessions")
    assert session["mode"] == "subscription"
    assert session["line_items[0][price_data][currency]"] == "eur"
    assert session["line_items[0][price_data][unit_amount]"] == "50000"
    assert session["line_items[0][price_data][recurring][interval]"] == "month"
    assert session["line_items[0][price_data][product_data][name]"]
    assert session["subscription_data[transfer_data][destination]"] == "acct_reseller1"
    assert session["subscription_data[on_behalf_of]"] == "acct_reseller1"
    assert session["subscription_data[application_fee_percent]"] == "17.5"
    assert session["metadata[organization_id]"] == str(org_id)
    assert session["metadata[plan_code]"] == code
    # Back on the page that confirms the payment.
    assert session["success_url"].endswith("/subscription?checkout=success")

    # Stripe confirms: the company is active on its reseller's offer.
    outcome = await stripe_billing.handle_event(
        {
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "object": "checkout.session",
                    "metadata": {"organization_id": str(org_id), "plan_code": code},
                    "customer": "cus_mensah",
                    "subscription": "sub_mensah",
                }
            },
        }
    )
    assert outcome == "checkout_completed"
    sub = await db_session.get_organization_subscription(org_id)
    assert (sub.status, sub.plan.code) == ("active", code)


async def test_offers_are_purchasable_once_the_reseller_takes_payments(
    db_session, saas_on, stripe, as_user
):
    """The company's subscription page shows « Choisir cette offre » only for
    purchasable offers: a reseller's offer has no Stripe price of its own, it
    is purchasable as soon as its reseller can take payments."""
    _, admin, owner, code, _ = await _reseller_with_company(db_session, as_user)
    async with as_user(owner) as client:
        before = (await client.get("/api/v1/saas/subscription/plans")).json()
    async with as_user(admin) as client:
        await client.post("/api/v1/reseller/stripe/onboarding")
        stripe.account = {"charges_enabled": True, "details_submitted": True}
        await client.get("/api/v1/reseller/stripe")
    async with as_user(owner) as client:
        after = (await client.get("/api/v1/saas/subscription/plans")).json()
    assert [(p["code"], p["purchasable"]) for p in before] == [(code, False)]
    assert [(p["code"], p["purchasable"]) for p in after] == [(code, True)]


async def test_dashboard_waits_for_the_submitted_onboarding(
    db_session, saas_on, stripe, as_user
):
    """Before the reseller submits Stripe's onboarding, Stripe has no
    dashboard to open: say so (409), not « Stripe indisponible » (502)."""
    _, admin, _, _, _ = await _reseller_with_company(db_session, as_user)
    async with as_user(admin) as client:
        await client.post("/api/v1/reseller/stripe/onboarding")
        early = await client.post("/api/v1/reseller/stripe/dashboard")
        stripe.account = {"charges_enabled": False, "details_submitted": True}
        later = await client.post("/api/v1/reseller/stripe/dashboard")
    assert early.status_code == 409, early.text
    assert "inscription" in early.json()["detail"].lower()
    assert later.status_code == 200, later.text


async def test_account_updated_events_follow_the_reseller_account(
    db_session, saas_on, stripe, as_user
):
    reseller, admin, _, _, _ = await _reseller_with_company(db_session, as_user)
    async with as_user(admin) as client:
        await client.post("/api/v1/reseller/stripe/onboarding")
    event = {
        "type": "account.updated",
        "account": "acct_reseller1",
        "data": {
            "object": {
                "object": "account",
                "id": "acct_reseller1",
                "charges_enabled": True,
            }
        },
    }
    assert await stripe_billing.handle_event(event) == "account_updated"
    stored = await db_session.get_reseller(reseller["id"])
    assert stored.stripe_charges_enabled is True
    other = {
        **event,
        "data": {
            "object": {
                "object": "account",
                "id": "acct_nobody",
                "charges_enabled": True,
            }
        },
    }
    assert await stripe_billing.handle_event(other) == "ignored"


def _signature(payload: bytes, secret: str) -> str:
    stamp = int(time.time())
    mac = hmac.new(secret.encode(), f"{stamp}.".encode() + payload, hashlib.sha256)
    return f"t={stamp},v1={mac.hexdigest()}"


def test_connect_events_are_signed_with_their_own_secret(stripe):
    payload = json.dumps({"type": "account.updated"}).encode()
    stripe_billing.verify_webhook_signature(
        payload, _signature(payload, "whsec_platform")
    )
    stripe_billing.verify_webhook_signature(
        payload, _signature(payload, "whsec_connect")
    )
    with pytest.raises(stripe_billing.StripeSignatureError):
        stripe_billing.verify_webhook_signature(
            payload, _signature(payload, "whsec_other")
        )


async def test_direct_customers_still_see_the_public_plans(
    db_session, saas_on, as_user
):
    await subscription_service.ensure_default_plans()
    user = await db_session.create_user_with_email(
        email=f"{uuid.uuid4().hex[:8]}@direct.example", password_hash="x"
    )
    org, _ = await db_session.get_or_create_organization_by_provider_id(
        org_provider_id=f"direct_{uuid.uuid4().hex}", user_id=user.id
    )
    user.selected_organization_id = org.id
    async with as_user(user) as client:
        plans = (await client.get("/api/v1/saas/subscription/plans")).json()
    assert {"starter", "business"} <= {p["code"] for p in plans}
