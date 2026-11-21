"""Enterprise PBX (white-labelled Wazo Platform engine)."""

import uuid

import pytest

from api.services.branding import brand
from api.services.pbx import client as client_module
from api.services.pbx import service as pbx
from api.services.pbx.client import PbxAuthError, PbxClient, PbxSettings, PbxUnavailable
from api.services.telephony.ari_manager import inbound_route_args
from api.tests.pbx_fake import TENANT, FakePbx, install

BASE = "https://pbx.ivoire-immo.ci"


def settings(**overrides) -> PbxSettings:
    values = {
        "base_url": BASE,
        "username": "nimbora",
        "password": "secret",
        "tenant_uuid": TENANT,
    }
    values.update(overrides)
    return PbxSettings(**values)


@pytest.fixture(autouse=True)
def _clear_tokens():
    client_module._TOKENS.clear()
    yield
    client_module._TOKENS.clear()


# ---------------------------------------------------------------- client


async def test_token_is_cached_and_renewed_when_revoked():
    fake = FakePbx()
    async with PbxClient(settings(), transport=fake.transport) as client:
        assert [u["uuid"] for u in await client.users()] == ["u-1", "u-2"]
        await client.queues()
        assert fake.token_requests == 1
        fake.revoke_tokens()  # e.g. the PBX restarted or the password changed
        assert len(await client.agents()) == 1
        assert fake.token_requests == 2
    method, path, headers = fake.requests[-1]
    assert path == "/api/confd/1.1/agents"
    assert headers["wazo-tenant"] == TENANT
    assert "x-auth-token" in headers


async def test_errors_are_typed():
    fake = FakePbx(password="other")
    async with PbxClient(settings(), transport=fake.transport) as client:
        with pytest.raises(PbxAuthError):
            await client.users()

    def boom(request):
        import httpx

        raise httpx.ConnectError("refused")

    import httpx

    async with PbxClient(settings(), transport=httpx.MockTransport(boom)) as client:
        with pytest.raises(PbxUnavailable):
            await client.users()


async def test_probe_reports_version_and_tenant():
    fake = FakePbx()
    result = await pbx.probe(settings(), transport=fake.transport)
    assert result == {
        "engine_version": "26.09",
        "engine_uuid": "engine-uuid",
        "tenant_name": "Ivoire Immo",
    }
    with pytest.raises(client_module.PbxError) as error:
        await pbx.probe(
            settings(tenant_uuid="00000000-dead-beef-0000-000000000000"),
            transport=fake.transport,
        )
    assert error.value.status == 404


def test_stasis_route_arguments():
    assert inbound_route_args(["inbound", "called=+22527000099"]) == {
        "called": "+22527000099"
    }
    assert (
        inbound_route_args(["inbound,called=1234"]) is None
    )  # first arg must be the marker
    assert inbound_route_args(["workflow_run_id=1,workflow_id=2"]) is None
    assert inbound_route_args([]) is None


def test_brand_comes_from_environment(monkeypatch):
    assert brand().name == "NIMBORA" and brand().sip_user_agent == "NIMBORA-Voice"
    monkeypatch.setenv("BRAND_NAME", "Sahel Connect")
    monkeypatch.setenv("BRAND_DOMAIN", "sahelconnect.africa")
    b = brand()
    assert b.pbx_name == "Sahel Connect Voice"
    assert b.sip_user_agent == "Sahel-Connect-Voice"
    assert b.noreply_email == "noreply@sahelconnect.africa"


def test_brand_treats_empty_variables_as_unset(monkeypatch):
    """Compose passes `${BRAND_PBX_NAME:-}` as "" when .env has no value: that must
    not produce an empty PBX name or SIP User-Agent."""
    for name in ("BRAND_NAME", "BRAND_PBX_NAME", "BRAND_DOMAIN", "BRAND_SIP_USER_AGENT"):
        monkeypatch.setenv(name, "")
    b = brand()
    assert (b.name, b.pbx_name, b.sip_user_agent) == ("NIMBORA", "NIMBORA Voice", "NIMBORA-Voice")
    assert b.noreply_email == "noreply@nimbora.io"


# ---------------------------------------------------------- with the DB


async def _org_with_pbx(db, monkeypatch, fake):
    user = await db.create_user_with_email(
        email=f"{uuid.uuid4().hex[:10]}@example.com", password_hash="x"
    )
    org, _ = await db.get_or_create_organization_by_provider_id(
        org_provider_id=f"org_{uuid.uuid4().hex}", user_id=user.id
    )
    await db.add_user_to_organization(user.id, org.id)
    await db.update_user_selected_organization(user.id, org.id)
    user.selected_organization_id = org.id
    ari = await db.create_telephony_configuration(
        organization_id=org.id,
        name="PBX (ARI)",
        provider="ari",
        credentials={
            "ari_endpoint": "http://pbx:5039",
            "app_name": "nimbora",
            "app_password": "x",
            "stasis_app_name": "nimbora_ab12cd34ef56",
        },
    )
    workflow = await db.create_workflow(
        "Accueil Ivoire Immo", {"nodes": [], "edges": []}, user.id, org.id
    )
    install(monkeypatch, fake)
    await db.save_pbx_connection(
        org.id,
        {
            "name": "PBX",
            "base_url": BASE,
            "username": "nimbora",
            "password": "secret",
            "tenant_uuid": TENANT,
            "ari_configuration_id": ari.id,
            "webhook_token": pbx.new_webhook_token(),
        },
    )
    return user, org, ari, workflow


async def test_route_a_pbx_number_to_an_ai_agent(db_session, monkeypatch):
    fake = FakePbx()
    _, org, ari, workflow = await _org_with_pbx(db_session, monkeypatch, fake)

    route = await pbx.route_number_to_agent(org.id, "+225 27 00 00 99", workflow.id)
    incall = next(i for i in fake.incalls if i["id"] == route["incall_id"])
    assert incall["destination"] == {
        "type": "custom",
        "command": "Stasis(nimbora_ab12cd34ef56,inbound,called=+22527000099)",
    }
    assert incall["extensions"][0]["exten"] == "+22527000099"
    assert (
        incall["extensions"][0]["context"] == "from-extern"
    )  # the PBX's incall context
    assert "NIMBORA" in incall["description"] and "Wazo" not in incall["description"]

    # NIMBORA knows the number: the ARI inbound path finds the agent from it.
    row = await db_session.find_active_phone_number_for_inbound(
        org.id, "+22527000099", "ari"
    )
    assert (
        row.inbound_workflow_id == workflow.id
        and row.telephony_configuration_id == ari.id
    )
    assert row.extra_metadata["pbx_route"]["incall_id"] == route["incall_id"]

    # A number already routed on the PBX (to humans) is never taken over.
    with pytest.raises(pbx.PbxRouteError) as conflict:
        await pbx.route_number_to_agent(org.id, "+22527000000", workflow.id)
    assert conflict.value.status == 409
    assert len([i for i in fake.incalls if i["id"] == 5]) == 1

    inventory = await pbx.inventory(org.id)
    numbers = {n["number"]: n for n in inventory["numbers"]}
    assert numbers["+22527000099"]["destination"] == "Agent IA"
    assert numbers["+22527000099"]["ai_workflow_name"] == "Accueil Ivoire Immo"
    assert numbers["+22527000000"]["destination"] == "File d'attente"

    assert await pbx.unroute_number(org.id, "+22527000099") is True
    assert not any(i["id"] == route["incall_id"] for i in fake.incalls)
    assert not any(e["exten"] == "+22527000099" for e in fake.extensions)
    assert (
        await db_session.find_active_phone_number_for_inbound(
            org.id, "+22527000099", "ari"
        )
        is None
    )
    assert await pbx.unroute_number(org.id, "+22527000099") is False


async def test_route_requires_ari_and_valid_number(db_session, monkeypatch):
    fake = FakePbx()
    _, org, _, workflow = await _org_with_pbx(db_session, monkeypatch, fake)
    with pytest.raises(pbx.PbxRouteError):
        await pbx.route_number_to_agent(org.id, "abc", workflow.id)
    await db_session.save_pbx_connection(org.id, {"ari_configuration_id": None})
    with pytest.raises(pbx.PbxRouteError) as error:
        await pbx.route_number_to_agent(org.id, "+22527000099", workflow.id)
    assert error.value.status == 409 and not fake.incalls[1:]


async def test_inventory_merges_agent_status_and_survives_a_failing_service(
    db_session, monkeypatch
):
    fake = FakePbx()
    _, org, _, _ = await _org_with_pbx(db_session, monkeypatch, fake)
    fake.down.add("calld")
    inventory = await pbx.inventory(org.id)
    assert inventory["users"][0] == {
        "id": 1,
        "uuid": "u-1",
        "name": "Koffi Yao",
        "extension": "1001",
        "email": "koffi@ivoire-immo.ci",
        "enabled": True,
        "login": "koffi@ivoire-immo.ci",
    }
    assert (
        inventory["agents"][0]["paused"] is True
        and inventory["agents"][0]["paused_reason"] == "pause déjeuner"
    )
    assert inventory["queues"][0] == {
        "id": 1,
        "name": "Ventes",
        "extensions": ["3001"],
        "members": 1,
        "agent_ids": [7],
        "overflow": None,
        "wait_time_threshold": None,
    }
    assert inventory["calls"] == [] and "calls" in inventory["errors"]


async def test_white_label_and_event_subscription(db_session, monkeypatch):
    fake = FakePbx()
    _, org, _, _ = await _org_with_pbx(db_session, monkeypatch, fake)
    assert await pbx.apply_branding(org.id) == {
        "sip_user_agent": "NIMBORA-Voice",
        "applied_by": "platform",
    }
    assert fake.pjsip == {
        "user_agent": "NIMBORA-Voice",
        "keep_alive_interval": "30",
    }  # others kept

    first = await pbx.ensure_webhook(org.id, "https://app.nimbora.io")
    connection = await db_session.get_pbx_connection(org.id)
    sub = fake.subscriptions[first]
    assert sub["events"] == pbx.WEBHOOK_EVENTS
    assert {"call_log_created", "call_created", "call_ended"} <= set(sub["events"])
    assert (
        sub["config"]["url"]
        == f"https://app.nimbora.io/api/v1/pbx/events/{connection.webhook_token}?event={{{{ event_name }}}}"
    )
    assert "Wazo" not in sub["name"]
    second = await pbx.ensure_webhook(org.id, "https://app.nimbora.io")
    assert first not in fake.subscriptions and second in fake.subscriptions
    assert connection.branding_applied_at is not None


async def test_branding_is_reported_as_the_kits_when_the_engine_refuses(db_session, monkeypatch):
    """Seen on a real engine (26.11): /asterisk/pjsip/global needs a master-tenant
    token, so the company's least-privilege service account gets 401. The kit
    brands the SIP headers at install time: the platform reports that instead of
    answering 502."""
    fake = FakePbx()
    fake.asterisk_master_only = True
    _, org, _, _ = await _org_with_pbx(db_session, monkeypatch, fake)
    result = await pbx.apply_branding(org.id)
    assert result["applied_by"] == "kit"
    assert result["sip_user_agent"] == "NIMBORA-Voice"
    assert "whitelabel.yml" in result["detail"]
    assert fake.pjsip["user_agent"] == "Wazo"  # untouched: not ours to change
    connection = await db_session.get_pbx_connection(org.id)
    assert connection.branding_applied_at is None


async def test_human_calls_feed_customer_history(db_session, monkeypatch):
    fake = FakePbx()
    _, org, _, workflow = await _org_with_pbx(db_session, monkeypatch, fake)
    from api.services.supervision import live_calls

    store: dict[str, str] = {}

    class FakeRedis:
        async def set(self, key, value, nx=False, ex=None):
            if nx and key in store:
                return None
            store[key] = value
            return True

    async def fake_redis():
        return FakeRedis()

    monkeypatch.setattr(live_calls, "get_redis", fake_redis)
    connection = await db_session.get_pbx_connection(org.id)
    cdr = {**fake.cdr[0], "id": 901}

    assert await pbx.handle_event(connection, "call_log_created", cdr) == "recorded"
    profile = await db_session.get_or_create_customer_profile(
        org.id, "+2250700112233", "700112233"
    )
    interactions = await db_session.list_customer_interactions(org.id, profile.id)
    assert (
        interactions[0].channel == "phone" and interactions[0].agent_name == "Koffi Yao"
    )
    assert interactions[0].summary == "Appel entrant avec Koffi Yao (3 min)"
    assert interactions[0].duration_seconds == 185

    assert await pbx.handle_event(connection, "call_log_created", cdr) == "duplicate"
    missed = {**cdr, "id": 902, "answered": False, "duration": 0}
    assert (
        await pbx.handle_event(
            connection, None, {"name": "call_log_created", "data": missed}
        )
        == "recorded"
    )
    assert (await db_session.list_customer_interactions(org.id, profile.id))[
        0
    ].summary == "Appel manqué"
    internal = {**cdr, "id": 903, "call_direction": "internal"}
    assert (
        await pbx.handle_event(connection, "call_log_created", internal)
        == "no_customer"
    )
    assert (
        await pbx.handle_event(connection, "agent_status_update", {"agent_id": 7})
        == "notified"
    )
    assert await pbx.handle_event(connection, "user_created", {}) == "ignored"
    # Calls to a number routed to an AI agent are recorded by the agent run.
    await pbx.route_number_to_agent(org.id, "+22527000099", workflow.id)
    ai = {
        **cdr,
        "id": 904,
        "requested_extension": "+22527000099",
        "destination_extension": "+22527000099",
    }
    assert await pbx.handle_event(connection, "call_log_created", ai) == "ai_call"


async def test_routes_connection_isolation_and_events(
    db_session, monkeypatch, test_client_factory
):
    fake = FakePbx()
    user, org, ari, workflow = await _org_with_pbx(db_session, monkeypatch, fake)
    await db_session.delete_pbx_connection(org.id)
    other = await db_session.create_user_with_email(
        email=f"{uuid.uuid4().hex[:10]}@example.com", password_hash="x"
    )
    other_org, _ = await db_session.get_or_create_organization_by_provider_id(
        org_provider_id=f"org_{uuid.uuid4().hex}", user_id=other.id
    )
    await db_session.add_user_to_organization(other.id, other_org.id)
    await db_session.update_user_selected_organization(other.id, other_org.id)
    other.selected_organization_id = other_org.id

    body = {
        "base_url": BASE + "/",
        "username": "nimbora",
        "password": "secret",
        "tenant_uuid": TENANT,
        "ari_configuration_id": ari.id,
    }
    async with test_client_factory(user) as client:
        empty = (await client.get("/api/v1/pbx/connection")).json()
        assert (
            empty["configured"] is False
            and empty["brand"]["pbx_name"] == "NIMBORA Voice"
        )
        saved = (await client.put("/api/v1/pbx/connection", json=body)).json()
        assert saved["status"] == "ok" and saved["engine_version"] == "26.09"
        assert saved["password"] == "••••••••" and saved["base_url"] == BASE
        # Saving with the masked password keeps the stored one.
        kept = (
            await client.put(
                "/api/v1/pbx/connection",
                json={**body, "password": "••••••••", "name": "Siège"},
            )
        ).json()
        assert kept["name"] == "Siège" and kept["status"] == "ok"
        bad = (
            await client.put(
                "/api/v1/pbx/connection", json={**body, "password": "wrong"}
            )
        ).json()
        assert bad["status"] == "error" and "refusés" in bad["last_error"]
        await client.put("/api/v1/pbx/connection", json=body)

        inventory = (await client.get("/api/v1/pbx/inventory")).json()
        assert inventory["calls"][0]["caller_name"] == "Awa"
        route = await client.post(
            "/api/v1/pbx/routes",
            json={"number": "+22527000099", "workflow_id": workflow.id},
        )
        assert route.status_code == 200
        conflict = await client.post(
            "/api/v1/pbx/routes",
            json={"number": "+22527000000", "workflow_id": workflow.id},
        )
        assert conflict.status_code == 409
        assert (
            await client.post("/api/v1/pbx/calls/1700000000.1/hangup")
        ).status_code == 204
        assert fake.hung_up == ["1700000000.1"]
        assert (await client.post("/api/v1/pbx/calls/nope/hangup")).status_code == 404
        assert (
            await client.post(
                "/api/v1/pbx/agents/1001/pause", json={"reason": "formation"}
            )
        ).status_code == 204
        assert (
            await client.post("/api/v1/pbx/agents/1001/login", json={})
        ).status_code == 422
        assert fake.agent_actions == [("1001", "pause", {"reason": "formation"})]
        logs = (await client.get("/api/v1/pbx/call-logs")).json()
        assert logs[0]["destination_name"] == "Koffi Yao"
        assert (await client.post("/api/v1/pbx/branding/apply")).json() == {
            "sip_user_agent": "NIMBORA-Voice",
            "applied_by": "platform",
        }
        assert (await client.post("/api/v1/pbx/events/connect")).status_code == 200
        foreign_ari = (
            await client.put(
                "/api/v1/pbx/connection", json={**body, "ari_configuration_id": 999999}
            )
        ).status_code
        assert foreign_ari == 404

    async with test_client_factory(other) as client:
        assert (await client.get("/api/v1/pbx/connection")).json()[
            "configured"
        ] is False
        assert (await client.get("/api/v1/pbx/inventory")).status_code == 404
        # Another company's ARI configuration cannot be linked.
        assert (
            await client.put("/api/v1/pbx/connection", json=body)
        ).status_code == 404

    connection = await db_session.get_pbx_connection(org.id)
    async with test_client_factory(other) as client:
        assert (
            await client.post(
                "/api/v1/pbx/events/not-a-token?event=call_log_created", json={}
            )
        ).status_code == 404
        delivered = await client.post(
            f"/api/v1/pbx/events/{connection.webhook_token}?event=agent_status_update",
            json={"agent_id": 7},
        )
        assert delivered.status_code == 204


async def test_saas_mode_refuses_private_pbx_addresses(monkeypatch):
    from api.utils import url_security

    monkeypatch.setattr(url_security, "_enforcing", lambda: True)
    with pytest.raises(ValueError):
        pbx.assert_pbx_url_allowed("https://10.0.0.5")
    with pytest.raises(ValueError):
        pbx.assert_pbx_url_allowed("ftp://pbx.example.com")
    monkeypatch.setattr("api.constants.PBX_ALLOWED_HOSTS", ["pbx.internal"])
    pbx.assert_pbx_url_allowed("https://pbx.internal")  # the operator's own PBX


async def test_ari_takes_a_pbx_routed_call_as_inbound_with_its_number(monkeypatch):
    """The PBX may answer before Stasis and runs it in a subroutine (exten "s")."""
    import asyncio
    import json
    from unittest.mock import AsyncMock

    from api.services.telephony import ari_manager
    from api.services.telephony.ari_manager import ARIConnection

    connection = ARIConnection(
        organization_id=1,
        telephony_configuration_id=2,
        ari_endpoint="http://pbx:5039",
        app_name="nimbora",
        app_password="x",
        stasis_app_name="nimbora_ab12cd34ef56",
    )
    monkeypatch.setattr(connection, "_is_ext_channel", AsyncMock(return_value=False))
    outbound = AsyncMock()
    monkeypatch.setattr(connection, "_handle_stasis_start", outbound)
    looked_up = []

    async def find(organization_id, address, provider):
        looked_up.append((organization_id, address, provider))
        return None

    monkeypatch.setattr(
        ari_manager.db_client, "find_active_phone_number_for_inbound", find
    )
    monkeypatch.setattr(connection, "_delete_channel", AsyncMock())
    await connection._handle_event(
        json.dumps(
            {
                "type": "StasisStart",
                "channel": {
                    "id": "c-1",
                    "state": "Up",
                    "caller": {"number": "+2250700112233"},
                    "dialplan": {"exten": "s"},
                },
                "args": ["inbound", "called=+22527000099"],
            }
        )
    )
    for _ in range(20):
        await asyncio.sleep(0.01)
        if looked_up:
            break
    assert looked_up == [(1, "+22527000099", "ari")]
    outbound.assert_not_called()


async def test_white_label_password_reset_only_reaches_known_pbxs(
    db_session, monkeypatch, test_client_factory
):
    fake = FakePbx()
    user, org, _, _ = await _org_with_pbx(db_session, monkeypatch, fake)
    body = {
        "host": "pbx.ivoire-immo.ci",
        "user_uuid": "u-1-uuid-0000",
        "token": "email-token-123",
        "password": "Nouveau-2026!",
    }
    async with test_client_factory(user) as client:
        assert (
            await client.post("/api/v1/pbx/password-reset", json=body)
        ).status_code == 204
        assert fake.password_resets == [("u-1-uuid-0000", "Nouveau-2026!")]
        # A host from a forged link is never contacted.
        before = len(fake.requests)
        forged = await client.post(
            "/api/v1/pbx/password-reset", json={**body, "host": "169.254.169.254"}
        )
        assert forged.status_code == 404 and len(fake.requests) == before
        expired = await client.post(
            "/api/v1/pbx/password-reset", json={**body, "token": "used-token-000"}
        )
        assert expired.status_code == 400 and "expiré" in expired.json()["detail"]
        weak = await client.post(
            "/api/v1/pbx/password-reset", json={**body, "password": "123"}
        )
        assert weak.status_code == 422


def test_service_account_policy_grants_exactly_what_the_client_needs():
    """deploy/pbx/integration-policy.json ↔ REQUIRED_ACL (least privilege)."""
    import json
    import re
    from pathlib import Path

    from api.services.pbx.client import REQUIRED_ACL

    policy = json.loads(
        (Path(__file__).parents[2] / "deploy/pbx/integration-policy.json").read_text()
    )
    granted = policy["acl"]

    def matches(pattern: str, acl: str) -> bool:
        # Engine wildcards: "*" = one segment, "#" = any number of segments.
        regex = re.escape(pattern).replace(r"\*", r"[^.]+").replace(r"\#", r".*")
        return re.fullmatch(regex, acl) is not None

    for name, required in REQUIRED_ACL.items():
        concrete = re.sub(r"\{[a-z_]+\}", "42", required)
        assert any(matches(p, concrete) for p in granted), (name, required)
    assert all("#" not in p for p in granted)  # no blanket grants
    for pattern in granted:  # nothing granted that the client does not use
        assert any(
            matches(pattern, re.sub(r"\{[a-z_]+\}", "42", r))
            for r in REQUIRED_ACL.values()
        ), pattern
