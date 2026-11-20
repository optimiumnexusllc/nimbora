"""Enterprise layer: subscriptions, Stripe, SSRF guard, contact center."""

import hashlib
import hmac
import json
import time
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from api.services.saas import subscription_service
from api.services.saas.subscription_service import add_months, roll_period_forward


# --------------------------------------------------------------- pure helpers
def test_add_months_clamps_to_month_end():
    assert add_months(datetime(2026, 1, 31, tzinfo=UTC), 1) == datetime(
        2026, 2, 28, tzinfo=UTC
    )
    assert add_months(datetime(2026, 11, 15, tzinfo=UTC), 2) == datetime(
        2027, 1, 15, tzinfo=UTC
    )


def test_roll_period_forward_contains_now():
    start = datetime(2026, 1, 10, tzinfo=UTC)
    end = datetime(2026, 2, 10, tzinfo=UTC)
    now = datetime(2026, 5, 3, tzinfo=UTC)
    new_start, new_end = roll_period_forward(start, end, now)
    assert new_start <= now < new_end
    assert (new_start, new_end) == (
        datetime(2026, 4, 10, tzinfo=UTC),
        datetime(2026, 5, 10, tzinfo=UTC),
    )


# --------------------------------------------------------------------- stripe
def _sign(payload: bytes, secret: str, timestamp: int) -> str:
    sig = hmac.new(
        secret.encode(), f"{timestamp}.".encode() + payload, hashlib.sha256
    ).hexdigest()
    return f"t={timestamp},v1={sig}"


def test_stripe_signature_accepts_valid_and_rejects_tampering():
    from api.services.saas.stripe_billing import (
        StripeSignatureError,
        verify_webhook_signature,
    )

    payload = b'{"type":"invoice.paid"}'
    now = int(time.time())
    header = _sign(payload, "whsec_test", now)
    verify_webhook_signature(payload, header, secret="whsec_test", now=now)

    with pytest.raises(StripeSignatureError):
        verify_webhook_signature(payload + b" ", header, secret="whsec_test", now=now)
    with pytest.raises(StripeSignatureError):
        verify_webhook_signature(payload, header, secret="other", now=now)
    with pytest.raises(StripeSignatureError):
        verify_webhook_signature(payload, header, secret="whsec_test", now=now + 3600)
    with pytest.raises(StripeSignatureError):
        verify_webhook_signature(payload, "garbage", secret="whsec_test", now=now)


# ---------------------------------------------------------------- SSRF guard
def test_saas_mode_blocks_private_urls_but_allows_platform_ai_hosts(monkeypatch):
    from api.utils import url_security

    monkeypatch.setattr(url_security, "DEPLOYMENT_MODE", "oss")
    monkeypatch.setattr(url_security, "SAAS_MODE", True)
    monkeypatch.setattr(url_security, "SERVICE_URL_ALLOWED_HOSTS", ["ollama"])

    with pytest.raises(ValueError):
        url_security.validate_user_configured_service_url(
            "http://127.0.0.1:5432", field_name="base_url"
        )
    with pytest.raises(ValueError):
        url_security.validate_user_configured_service_url(
            "http://169.254.169.254/latest", field_name="base_url"
        )
    # Model endpoints may target the platform's own AI containers...
    url_security.validate_user_configured_service_url(
        "http://ollama:11434/v1", field_name="base_url", allow_platform_services=True
    )
    # ...but arbitrary HTTP tools may not (Ollama has unauthenticated admin APIs).
    with pytest.raises(ValueError):
        url_security.validate_user_configured_service_url(
            "http://ollama:11434/api/delete", field_name="config.url"
        )


def test_single_company_oss_install_is_unrestricted(monkeypatch):
    from api.utils import url_security

    monkeypatch.setattr(url_security, "DEPLOYMENT_MODE", "oss")
    monkeypatch.setattr(url_security, "SAAS_MODE", False)
    url_security.validate_user_configured_service_url(
        "http://192.168.1.10:8000", field_name="base_url"
    )


# ------------------------------------------------------------ startup checks
def test_saas_startup_refuses_default_jwt_secret(monkeypatch):
    from api import constants
    from api.services.saas.startup import validate_saas_configuration

    monkeypatch.setattr(constants, "SAAS_MODE", True)
    monkeypatch.setattr(constants, "DEPLOYMENT_MODE", "oss")
    monkeypatch.setattr(constants, "AUTH_PROVIDER", "local")
    monkeypatch.setattr(constants, "OSS_JWT_SECRET", "change-me-in-production")
    monkeypatch.setattr(constants, "STRIPE_SECRET_KEY", "sk_test")
    monkeypatch.setattr(constants, "STRIPE_WEBHOOK_SECRET", None)
    monkeypatch.setattr(constants, "CONTACT_CENTER_ENABLED", False)
    problems = validate_saas_configuration()
    assert any("OSS_JWT_SECRET" in p for p in problems)
    assert any("STRIPE_WEBHOOK_SECRET" in p for p in problems)

    monkeypatch.setattr(constants, "OSS_JWT_SECRET", "x" * 64)
    monkeypatch.setattr(constants, "STRIPE_WEBHOOK_SECRET", "whsec")
    assert validate_saas_configuration() == []


# ------------------------------------------------- contact center rendering
class _Agent:
    def __init__(self, org, ext, name="Alice", active=True):
        from api.services.contact_center.asterisk_config import (
            agent_sip_username,
            digest_md5,
        )

        self.id = int(ext)
        self.organization_id = org
        self.extension = ext
        self.display_name = name
        self.is_active = active
        self.sip_username = agent_sip_username(org, ext)
        self.sip_md5_cred = digest_md5(self.sip_username, "pw")
        self.queues = []


class _Queue:
    def __init__(self, org, slug, agents, overflow=None, strategy="rrmemory"):
        self.id = 1
        self.organization_id = org
        self.slug = slug
        self.name = slug
        self.strategy = strategy
        self.ring_timeout_seconds = 20
        self.max_wait_seconds = 300
        self.wrapup_seconds = 10
        self.announce_position = True
        self.overflow_destination = overflow
        self.is_active = True
        self.agents = agents


def test_rendered_config_isolates_tenants_and_sanitizes_values():
    from api.services.contact_center.asterisk_config import (
        render_extensions,
        render_pjsip,
        render_queues,
    )

    alice = _Agent(1, "1001", name='Alice"]\n[evil]\ntype=endpoint')
    bob = _Agent(2, "1001", name="Bob")
    queue = _Queue(1, "support", [alice, bob], overflow="1001", strategy="bogus")

    pjsip = render_pjsip([alice, bob])
    assert "[t1_1001]" in pjsip and "[t2_1001]" in pjsip
    assert "[evil]" not in pjsip
    assert "context=nimbora-agents-t1" in pjsip
    assert "md5_cred=" in pjsip and "password=" not in pjsip

    queues = render_queues([queue])
    assert "[t1-support]" in queues
    assert "strategy=rrmemory" in queues  # unknown strategy falls back
    assert "PJSIP/t1_1001" in queues
    assert "PJSIP/t2_1001" not in queues  # other tenant's agent never joins

    extensions = render_extensions([queue], [alice, bob])
    assert "exten => t1-support,1" in extensions
    assert "[nimbora-agents-t1]" in extensions and "[nimbora-agents-t2]" in extensions
    t1_context = extensions.split("[nimbora-agents-t1]")[1].split(
        "[nimbora-agents-t2]"
    )[0]
    assert "t2_" not in t1_context


def test_queue_destinations_and_raw_channel_guard(monkeypatch):
    from api.services.contact_center import destinations

    assert destinations.parse_queue_destination("queue:Support") == "support"
    assert destinations.parse_queue_destination("+33123456789") is None
    with pytest.raises(destinations.ContactCenterDestinationError):
        destinations.parse_queue_destination("queue:../../etc")
    assert (
        destinations.queue_dial_string(12, "ventes")
        == "Local/t12-ventes@nimbora-queues"
    )

    monkeypatch.setattr(destinations, "SAAS_MODE", True)
    with pytest.raises(destinations.ContactCenterDestinationError):
        destinations.assert_tenant_may_dial("PJSIP/t99_1001")
    with pytest.raises(destinations.ContactCenterDestinationError):
        destinations.assert_tenant_may_dial("Local/t99-support@nimbora-queues")
    destinations.assert_tenant_may_dial("+33123456789")

    monkeypatch.setattr(destinations, "SAAS_MODE", False)
    destinations.assert_tenant_may_dial("PJSIP/1001")


# ------------------------------------------------------------- DB-backed
async def _new_org(db, email=None):
    user = await db.create_user_with_email(
        email=email or f"{uuid.uuid4().hex[:10]}@example.com", password_hash="x"
    )
    org, _ = await db.get_or_create_organization_by_provider_id(
        org_provider_id=f"org_{uuid.uuid4().hex}", user_id=user.id
    )
    await db.add_user_to_organization(user.id, org.id)
    await db.update_user_selected_organization(user.id, org.id)
    user.selected_organization_id = org.id
    return user, org


@pytest.fixture
def saas_on(monkeypatch):
    monkeypatch.setattr(subscription_service, "SAAS_MODE", True)
    monkeypatch.setattr(subscription_service, "SAAS_TRIAL_DAYS", 14)
    monkeypatch.setattr(subscription_service, "SAAS_DEFAULT_PLAN", "starter")
    from api.routes import saas as saas_routes
    from api.services.saas import limits

    monkeypatch.setattr(limits, "SAAS_MODE", True)
    monkeypatch.setattr(saas_routes, "SAAS_MODE", True)


async def test_new_org_gets_trial_and_plan_concurrency(db_session, saas_on):
    from api.enums import OrganizationConfigurationKey

    _, org = await _new_org(db_session)
    sub = await subscription_service.ensure_organization_subscription(org.id)
    assert sub.status == "trialing" and sub.plan.code == "starter"
    # Idempotent.
    again = await subscription_service.ensure_organization_subscription(org.id)
    assert again.id == sub.id
    limit = await db_session.get_configuration(
        org.id, OrganizationConfigurationKey.CONCURRENT_CALL_LIMIT.value
    )
    assert limit.value == {"value": 3}
    assert (await subscription_service.authorize_call(org.id)).allowed


async def test_expired_trial_and_suspension_block_calls(db_session, saas_on):
    _, org = await _new_org(db_session)
    await subscription_service.ensure_organization_subscription(org.id)
    later = datetime.now(UTC) + timedelta(days=15)
    result = await subscription_service.authorize_call(org.id, now=later)
    assert not result.allowed and result.error_code == "trial_expired"

    await db_session.update_organization_subscription(org.id, {"status": "suspended"})
    result = await subscription_service.authorize_call(org.id)
    assert not result.allowed and result.error_code == "subscription_suspended"


async def test_past_due_grace_period(db_session, saas_on):
    _, org = await _new_org(db_session)
    await subscription_service.ensure_organization_subscription(org.id)
    now = datetime.now(UTC)
    await db_session.update_organization_subscription(
        org.id, {"status": "past_due", "past_due_since": now - timedelta(days=1)}
    )
    assert (await subscription_service.authorize_call(org.id, now=now)).allowed
    later = now + timedelta(days=10)
    result = await subscription_service.authorize_call(org.id, now=later)
    assert result.error_code == "payment_overdue"


async def test_minutes_exhausted_blocks_trial_but_active_plan_bills_overage(
    db_session, saas_on, monkeypatch
):
    _, org = await _new_org(db_session)
    await subscription_service.ensure_organization_subscription(org.id)

    async def fake_seconds(organization_id, start, end):
        return 1000 * 60.0  # the whole starter allowance

    monkeypatch.setattr(db_session, "get_organization_billable_seconds", fake_seconds)
    result = await subscription_service.authorize_call(org.id)
    assert result.error_code == "minutes_exhausted"

    await db_session.update_organization_subscription(org.id, {"status": "active"})
    assert (await subscription_service.authorize_call(org.id)).allowed
    summary = await subscription_service.get_usage_summary(org.id)
    assert summary.remaining_minutes == 0


async def test_agent_limit_is_enforced_at_creation(db_session, saas_on):
    from api.services.saas.limits import PlanLimitExceeded

    user, org = await _new_org(db_session)
    await subscription_service.ensure_organization_subscription(org.id)
    for i in range(3):
        await db_session.create_workflow(f"agent {i}", {}, user.id, org.id)
    with pytest.raises(PlanLimitExceeded):
        await db_session.create_workflow("agent 4", {}, user.id, org.id)


async def test_stripe_checkout_and_failed_payment_events(db_session, saas_on):
    from api.services.saas import stripe_billing

    _, org = await _new_org(db_session)
    await subscription_service.ensure_default_plans()
    outcome = await stripe_billing.handle_event(
        {
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "object": "checkout.session",
                    "client_reference_id": str(org.id),
                    "metadata": {
                        "organization_id": str(org.id),
                        "plan_code": "business",
                    },
                    "customer": "cus_123",
                    "subscription": "sub_123",
                }
            },
        }
    )
    assert outcome == "checkout_completed"
    sub = await db_session.get_organization_subscription(org.id)
    assert (sub.status, sub.plan.code, sub.stripe_customer_id) == (
        "active",
        "business",
        "cus_123",
    )

    outcome = await stripe_billing.handle_event(
        {
            "type": "invoice.payment_failed",
            "data": {"object": {"object": "invoice", "customer": "cus_123"}},
        }
    )
    assert outcome == "payment_failed"
    sub = await db_session.get_organization_subscription(org.id)
    assert sub.status == "past_due" and sub.past_due_since is not None


async def test_contact_center_members_cannot_cross_tenants(db_session):
    _, org_a = await _new_org(db_session)
    _, org_b = await _new_org(db_session)
    agent_b = await db_session.create_contact_center_agent(
        org_b.id,
        display_name="Bob",
        extension="1001",
        sip_username=f"t{org_b.id}_1001",
        sip_md5_cred="0" * 32,
    )
    queue_a = await db_session.create_contact_center_queue(
        org_a.id, "support", {"name": "Support"}
    )
    with pytest.raises(ValueError):
        await db_session.set_contact_center_queue_members(
            org_a.id, queue_a.id, [agent_b.id]
        )
    # Other tenants cannot read, change or delete the queue.
    assert await db_session.get_contact_center_queue(org_b.id, queue_a.id) is None
    assert not await db_session.delete_contact_center_queue(org_b.id, queue_a.id)


async def test_queue_transfer_resolves_only_own_queues(db_session):
    from api.services.contact_center.destinations import (
        ContactCenterDestinationError,
        resolve_transfer_dial_string,
    )

    _, org_a = await _new_org(db_session)
    _, org_b = await _new_org(db_session)
    await db_session.create_contact_center_queue(org_a.id, "ventes", {"name": "Ventes"})
    dial = await resolve_transfer_dial_string(
        "queue:ventes", organization_id=org_a.id, dial_string_template="PJSIP/{number}"
    )
    assert dial == f"Local/t{org_a.id}-ventes@nimbora-queues"
    with pytest.raises(ContactCenterDestinationError):
        await resolve_transfer_dial_string(
            "queue:ventes",
            organization_id=org_b.id,
            dial_string_template="PJSIP/{number}",
        )


async def test_saas_and_contact_center_routes(
    db_session, saas_on, test_client_factory, monkeypatch, tmp_path
):
    from api.routes import contact_center as cc_routes
    from api.services.contact_center import asterisk_config

    monkeypatch.setattr(cc_routes, "CONTACT_CENTER_ENABLED", True)
    monkeypatch.setattr(asterisk_config, "ASTERISK_GENERATED_CONFIG_DIR", str(tmp_path))
    monkeypatch.setattr(asterisk_config, "CONTACT_CENTER_ENABLED", True)
    monkeypatch.setattr(asterisk_config, "ASTERISK_ARI_PASSWORD", None)

    user, org = await _new_org(db_session)
    async with test_client_factory(user) as client:
        plans = (await client.get("/api/v1/saas/plans")).json()
        assert {p["code"] for p in plans} >= {"starter", "business", "enterprise"}

        sub = (await client.get("/api/v1/saas/subscription")).json()
        assert sub["plan_code"] == "starter" and sub["status"] == "trialing"

        created = await client.post(
            "/api/v1/contact-center/agents",
            json={"display_name": "Alice", "extension": "1001"},
        )
        assert created.status_code == 201, created.text
        body = created.json()
        assert body["sip_username"] == f"t{org.id}_1001" and body["sip_password"]
        agent_id = body["agent"]["id"]

        queue = await client.post(
            "/api/v1/contact-center/queues",
            json={"slug": "support", "name": "Support", "agent_ids": [agent_id]},
        )
        assert queue.status_code == 201, queue.text
        assert queue.json()["transfer_destination"] == "queue:support"

        duplicate = await client.post(
            "/api/v1/contact-center/agents",
            json={"display_name": "Alias", "extension": "1001"},
        )
        assert duplicate.status_code == 409

        claimed = await client.post(f"/api/v1/contact-center/agents/{agent_id}/claim")
        assert claimed.status_code == 200 and claimed.json()["user_id"] == user.id
        me = await client.get("/api/v1/contact-center/me")
        assert me.json()["extension"] == "1001"

        # Starter allows 2 human seats.
        await client.post(
            "/api/v1/contact-center/agents",
            json={"display_name": "Bob", "extension": "1002"},
        )
        third = await client.post(
            "/api/v1/contact-center/agents",
            json={"display_name": "Carol", "extension": "1003"},
        )
        assert third.status_code == 402

        # Non-superusers cannot reach the operator console.
        assert (await client.get("/api/v1/saas/admin/tenants")).status_code in {
            401,
            403,
        }

    generated = (tmp_path / "queues_nimbora.conf").read_text()
    assert f"[t{org.id}-support]" in generated
    assert f"PJSIP/t{org.id}_1001" in generated
    pjsip = (tmp_path / "pjsip_nimbora_agents.conf").read_text()
    assert body["sip_password"] not in pjsip


async def test_stripe_webhook_route_rejects_unsigned(db_session, saas_on, monkeypatch):
    from httpx import ASGITransport, AsyncClient

    from api.app import app
    from api.services.saas import stripe_billing

    monkeypatch.setattr(stripe_billing, "STRIPE_WEBHOOK_SECRET", "whsec_route")
    payload = json.dumps({"type": "invoice.paid", "data": {"object": {}}}).encode()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        bad = await c.post(
            "/api/v1/saas/stripe/webhook",
            content=payload,
            headers={"Stripe-Signature": "t=1,v1=00"},
        )
        assert bad.status_code == 400
        good = await c.post(
            "/api/v1/saas/stripe/webhook",
            content=payload,
            headers={
                "Stripe-Signature": _sign(payload, "whsec_route", int(time.time()))
            },
        )
        assert good.status_code == 200 and good.json()["outcome"] == "ignored"


# ------------------------------------------------------------------ local AI
def test_local_spec_is_a_valid_pipeline_configuration():
    from uuid import uuid4

    from api.schemas.model_connections import ModelConfigurationSpec
    from api.services.local_ai.provisioning import local_model_configuration_spec

    spec = local_model_configuration_spec(uuid4(), uuid4(), language="sw")
    ModelConfigurationSpec.model_validate(spec)
    assert spec["stt"]["settings"]["language"] == "sw"
    assert "lanfrica" in spec["tts"]["settings"]["voice"]

    # A language without a local voice listens in that language, speaks French.
    spec = local_model_configuration_spec(uuid4(), uuid4(), language="ha")
    assert spec["stt"]["settings"]["language"] == "ha"
    assert spec["tts"]["settings"]["voice"] == "ff_siwis"


async def test_local_bootstrap_resolves_to_local_services(db_session):
    from api.services.configuration.model_connections import resolve_model_configuration
    from api.services.local_ai.provisioning import bootstrap_local_model_configuration

    _, org = await _new_org(db_session)
    await bootstrap_local_model_configuration(org.id)
    resolved = await resolve_model_configuration(org.id)
    effective = resolved.effective
    assert effective.llm.provider == "speaches"
    assert effective.llm.base_url == "http://ollama:11434/v1"
    assert effective.stt.base_url == "http://speaches:8000/v1"
    assert effective.stt.language == "fr"
    assert effective.tts.voice == "ff_siwis"
    assert effective.managed_service_version is None  # no NIMBORA cloud key


async def test_bootstrap_uses_local_ai_without_cloud_calls(db_session, monkeypatch):
    from api.services import organization_bootstrap
    from api.services.configuration.model_connections import (
        get_default_model_configuration,
    )

    monkeypatch.setattr(organization_bootstrap, "LOCAL_AI_ENABLED", True)

    async def no_cloud(*args, **kwargs):
        raise AssertionError("must not call NIMBORA cloud services")

    monkeypatch.setattr(organization_bootstrap, "mint_managed_service_key", no_cloud)
    monkeypatch.setattr(
        organization_bootstrap, "ensure_hosted_mps_billing_account_v2", no_cloud
    )
    monkeypatch.setattr(
        organization_bootstrap, "provision_managed_sip_connectivity", no_cloud
    )
    _, org = await _new_org(db_session)
    assert await organization_bootstrap.ensure_organization_bootstrapped(
        org.id, created_by="tester"
    )
    default = await get_default_model_configuration(org.id)
    assert default is not None


# ------------------------------------------------------------ F1 handoffs
def test_handoff_summary_parsing_is_strict():
    from api.services.contact_center.handoff import parse_summary

    card = parse_summary(
        'Voici: {"reason": "Colis non reçu", "summary": "Commande 42 en retard.",'
        ' "customer_name": "null", "sentiment": "Frustrated", "next_step": "Vérifier"}'
    )
    assert card == {
        "reason": "Colis non reçu",
        "summary": "Commande 42 en retard.",
        "customer_name": None,
        "sentiment": "frustrated",
        "next_step": "Vérifier",
    }
    assert parse_summary("pas de json") is None
    assert parse_summary('{"sentiment": "happy"}') is None
    assert (
        parse_summary('{"summary": "ok", "sentiment": "ecstatic"}')["sentiment"] is None
    )


def test_handoff_transcript_and_collected_data_filtering():
    from api.services.contact_center.handoff import (
        collected_data,
        conversation_transcript,
    )

    turns = conversation_transcript(
        [
            {"role": "system", "content": "secret prompt"},
            {"role": "user", "content": "  Bonjour,   je   suis Awa "},
            {"role": "assistant", "content": "", "tool_calls": [{"id": 1}]},
            {"role": "assistant", "content": "Bonjour Awa"},
            {"role": "tool", "content": "{}"},
        ]
    )
    assert turns == [
        {"speaker": "client", "text": "Bonjour, je suis Awa"},
        {"speaker": "agent_ia", "text": "Bonjour Awa"},
    ]
    data = collected_data(
        {
            "order_id": "42",
            "mps_correlation_id": "x",
            "_internal": 1,
            "empty": "",
            "call_id": "c1",
            "items": ["a", "b"],
        }
    )
    assert data == {"order_id": "42", "items": ["a", "b"]}


class _FakeLLM:
    def __init__(self, reply):
        self.reply = reply
        self.calls = 0

    async def run_inference(self, context, system_instruction=None):
        self.calls += 1
        return self.reply


class _FakeEngine:
    def __init__(self, reply):
        from types import SimpleNamespace

        self.active_agent = SimpleNamespace(inference_llm=_FakeLLM(reply))
        self.context = SimpleNamespace(
            messages=[
                {"role": "user", "content": "Mon colis n'est pas arrivé, commande 42"},
                {"role": "assistant", "content": "Je vous passe un conseiller."},
            ]
        )
        self._gathered_context = {"order_id": "42"}


async def test_handoff_card_created_and_summarized_in_background(db_session):
    import asyncio
    from types import SimpleNamespace

    from api.services.contact_center import handoff as handoff_service

    _, org = await _new_org(db_session)
    engine = _FakeEngine(
        '{"reason": "Colis non reçu", "summary": "Commande 42 non livrée.",'
        ' "customer_name": null, "sentiment": "frustrated",'
        ' "next_step": "Ouvrir une enquête transporteur"}'
    )
    run = SimpleNamespace(id=None, initial_context={"caller_number": "+22790000000"})
    handoff_id = await handoff_service.create_handoff_for_transfer(
        engine, organization_id=org.id, workflow_run=run, queue_slug="support"
    )
    assert handoff_id
    created = await db_session.get_call_handoff(org.id, handoff_id)
    assert created.status == "pending" and created.caller_number == "+22790000000"
    assert created.collected_data == {"order_id": "42"}
    assert len(created.transcript) == 2
    await asyncio.gather(*list(handoff_service._background))
    card = await db_session.get_call_handoff(org.id, handoff_id)
    assert card.summary_status == "ready"
    assert card.reason == "Colis non reçu" and card.sentiment == "frustrated"


async def test_handoff_summary_failure_never_blocks(db_session):
    import asyncio
    from types import SimpleNamespace

    from api.services.contact_center import handoff as handoff_service

    _, org = await _new_org(db_session)
    engine = _FakeEngine("désolé, je ne peux pas")
    handoff_id = await handoff_service.create_handoff_for_transfer(
        engine,
        organization_id=org.id,
        workflow_run=SimpleNamespace(id=None, initial_context={}),
        queue_slug="support",
    )
    await asyncio.gather(*list(handoff_service._background))
    card = await db_session.get_call_handoff(org.id, handoff_id)
    assert card.summary_status == "failed" and card.status == "pending"


async def test_handoff_routes_scope_to_tenant_and_seat_queues(
    db_session, test_client_factory, monkeypatch, tmp_path
):
    from api.routes import contact_center as cc_routes
    from api.services.contact_center import asterisk_config

    monkeypatch.setattr(cc_routes, "CONTACT_CENTER_ENABLED", True)
    monkeypatch.setattr(asterisk_config, "ASTERISK_GENERATED_CONFIG_DIR", str(tmp_path))
    monkeypatch.setattr(asterisk_config, "ASTERISK_ARI_PASSWORD", None)

    user, org = await _new_org(db_session)
    other_user, other_org = await _new_org(db_session)
    agent = await db_session.create_contact_center_agent(
        org.id,
        display_name="Awa",
        extension="2001",
        sip_username=f"t{org.id}_2001",
        sip_md5_cred="0" * 32,
        user_id=user.id,
    )
    support = await db_session.create_contact_center_queue(
        org.id, "support", {"name": "S"}
    )
    await db_session.create_contact_center_queue(org.id, "ventes", {"name": "V"})
    await db_session.set_contact_center_queue_members(org.id, support.id, [agent.id])
    mine = await db_session.create_call_handoff(
        organization_id=org.id,
        queue_slug="support",
        status="pending",
        collected_data={},
        transcript=[],
        summary_status="skipped",
    )
    await db_session.create_call_handoff(
        organization_id=org.id,
        queue_slug="ventes",
        status="pending",
        collected_data={},
        transcript=[],
        summary_status="skipped",
    )

    async with test_client_factory(user) as client:
        listed = (await client.get("/api/v1/contact-center/handoffs?mine=true")).json()
        assert [h["id"] for h in listed] == [mine.id]
        accepted = await client.post(
            f"/api/v1/contact-center/handoffs/{mine.id}/accept"
        )
        assert accepted.json()["status"] == "answered"
    stored = await db_session.get_call_handoff(org.id, mine.id)
    assert stored.answered_by_agent_id == agent.id

    async with test_client_factory(other_user) as client:
        assert (
            await client.get(f"/api/v1/contact-center/handoffs/{mine.id}")
        ).status_code == 404
        assert (
            await client.post(f"/api/v1/contact-center/handoffs/{mine.id}/accept")
        ).status_code == 404


def test_queue_dialplan_attaches_handoff_header():
    from api.services.contact_center.asterisk_config import render_extensions

    extensions = render_extensions([_Queue(4, "support", [])], [])
    assert "Queue(t4-support,tb(nimbora-handoff^s^1),,,300)" in extensions
    assert "PJSIP_HEADER(add,X-Nimbora-Handoff)=${NIMBORA_HANDOFF}" in extensions
