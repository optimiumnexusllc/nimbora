"""Supervision alerts: rules evaluated on the live PBX state, shown in the
console, and sent (start and end, with a cooldown) by webhook and e-mail."""

import uuid

import pytest

from api.services.pbx import alerts, supervision
from api.services.pbx import client as client_module
from api.services.pbx import service as pbx
from api.tests.pbx_fake import TENANT, FakePbx, install

BASE = "https://pbx.ivoire-immo.ci"


@pytest.fixture(autouse=True)
async def _clear():
    from api.services.supervision.live_calls import get_redis

    client_module._TOKENS.clear()
    supervision._live_cache.clear()
    yield
    supervision._live_cache.clear()
    redis = await get_redis()
    for key in await redis.keys("nimbora:pbx:alerts:*"):
        await redis.delete(key)


async def _org(db, monkeypatch, fake):
    user = await db.create_user_with_email(
        email=f"{uuid.uuid4().hex[:10]}@example.com", password_hash="x"
    )
    org, _ = await db.get_or_create_organization_by_provider_id(
        org_provider_id=f"org_{uuid.uuid4().hex}", user_id=user.id
    )
    await db.add_user_to_organization(user.id, org.id)
    await db.update_user_selected_organization(user.id, org.id)
    user.selected_organization_id = org.id
    install(monkeypatch, fake)
    await db.save_pbx_connection(
        org.id,
        {
            "base_url": BASE,
            "username": "nimbora",
            "password": "secret",
            "tenant_uuid": TENANT,
            "webhook_token": pbx.new_webhook_token(),
        },
    )
    return user, org


def _queue(**fields):
    base = {
        "id": 1,
        "name": "Ventes",
        "live": True,
        "waiting": 2,
        "longest_wait_seconds": 30,
        "agents_available": 1,
        "agents_logged": 2,
    }
    return {**base, **fields}


def test_rules():
    settings = {
        **alerts.DEFAULTS,
        "enabled": True,
        "max_wait_seconds": 60,
        "max_waiting": 3,
    }
    assert alerts.evaluate({"queues": [_queue()]}, settings) == []
    assert (
        alerts.evaluate(
            {"queues": [_queue(longest_wait_seconds=300)]},
            {**settings, "enabled": False},
        )
        == []
    )

    found = alerts.evaluate(
        {"queues": [_queue(waiting=5, longest_wait_seconds=130, agents_available=0)]},
        settings,
    )
    assert [a["kind"] for a in found] == ["long_wait", "no_agent", "queue_full"]
    long_wait = found[0]
    assert long_wait["level"] == "critical"  # more than twice the threshold
    assert long_wait["key"] == "long_wait:1"
    assert "2 min 10 s" in long_wait["message"] and "Ventes" in long_wait["message"]
    assert "aucun conseiller disponible" in found[1]["message"]
    nobody = alerts.evaluate(
        {"queues": [_queue(agents_available=0, agents_logged=0)]}, settings
    )
    assert "aucun conseiller connecté" in nobody[0]["message"]
    # Empty queues, queues not read live, and queues left out are ignored.
    assert (
        alerts.evaluate({"queues": [_queue(waiting=0, agents_available=0)]}, settings)
        == []
    )
    assert (
        alerts.evaluate(
            {"queues": [_queue(live=False, longest_wait_seconds=999)]}, settings
        )
        == []
    )
    assert (
        alerts.evaluate(
            {"queues": [_queue(longest_wait_seconds=999)]},
            {**settings, "queue_ids": [2]},
        )
        == []
    )
    assert (
        alerts.evaluate(
            {"queues": [_queue(agents_available=0)]}, {**settings, "no_agent": False}
        )
        == []
    )


async def test_settings_validation(db_session, monkeypatch):
    user, org = await _org(db_session, monkeypatch, FakePbx())
    for bad in (
        {"webhook_url": "http://hooks.example.com/x"},
        {"max_wait_seconds": 5},
        {"email_recipients": ["chef@ivoire-immo.ci"]},  # no e-mail tool
        {"email_tool_uuid": "not-a-tool", "email_recipients": ["chef@ivoire-immo.ci"]},
    ):
        with pytest.raises(pbx.PbxRouteError):
            await alerts.save_settings(org.id, bad)
    sms = await db_session.create_tool(
        org.id,
        user.id,
        "SMS client",
        {"config": {"channel": "sms", "provider": "twilio"}},
        category="send_message",
    )
    with pytest.raises(pbx.PbxRouteError):
        await alerts.save_settings(org.id, {"email_tool_uuid": str(sms.tool_uuid)})
    mail = await db_session.create_tool(
        org.id,
        user.id,
        "E-mail",
        {
            "config": {
                "channel": "email",
                "provider": "smtp",
                "smtp_host": "smtp.example.com",
                "sender": "alertes@ivoire-immo.ci",
                "credential_uuid": "c",
            }
        },
        category="send_message",
    )
    saved = await alerts.save_settings(
        org.id,
        {
            "enabled": True,
            "webhook_url": "https://hooks.slack.com/services/T/B/X",
            "email_tool_uuid": str(mail.tool_uuid),
            "email_recipients": [" chef@ivoire-immo.ci ", ""],
        },
    )
    assert saved["email_recipients"] == ["chef@ivoire-immo.ci"]
    # Other supervision settings are kept.
    connection = await db_session.get_pbx_connection(org.id)
    assert connection.supervision_settings["alerts"]["enabled"] is True


async def test_start_end_and_cooldown(db_session, monkeypatch):
    fake = FakePbx()
    fake.statuses[0]["paused"] = True  # Koffi paused: nobody available
    _, org = await _org(db_session, monkeypatch, fake)
    sent: list[str] = []

    async def webhook(url, text, payload):
        sent.append(text)

    monkeypatch.setattr(alerts, "_post_webhook", webhook)
    await alerts.save_settings(
        org.id,
        {
            "enabled": True,
            "max_wait_seconds": 30,
            "webhook_url": "https://hooks.example.com/a",
            "cooldown_minutes": 10,
        },
    )
    # The console sees the alerts on the live state at once.
    live = await supervision.live(org.id, use_cache=False)
    assert {a["kind"] for a in live["alerts"]} == {"no_agent", "long_wait"}

    counts = await alerts.check_organization(org.id, now=1000.0)
    assert counts == {"raised": 2, "cleared": 0} and len(sent) == 2
    assert all(t.startswith("⚠️") for t in sent)
    # Still active: nothing new.
    supervision.invalidate(org.id)
    assert (await alerts.check_organization(org.id, now=1060.0))["raised"] == 0

    # The caller is answered: both alerts end, once.
    fake.queue_entries["ventes"] = []
    supervision.invalidate(org.id)
    assert (await alerts.check_organization(org.id, now=1120.0))["cleared"] == 2
    assert sent[-1].startswith("✅ Rétabli")
    log = await alerts.recent_log(org.id)
    assert log[0]["event"] == "resolved" and log[0]["duration_seconds"] == 120

    # Back within the cooldown: shown in the console, not sent again.
    fake.queue_entries["ventes"] = [{"Position": "1", "Wait": "90"}]
    supervision.invalidate(org.id)
    assert (await alerts.check_organization(org.id, now=1200.0))["raised"] == 0
    assert len(sent) == 4
    # Its end is silent too (its return was never sent).
    fake.queue_entries["ventes"] = []
    supervision.invalidate(org.id)
    await alerts.check_organization(org.id, now=1260.0)
    assert len(sent) == 4
    # After the cooldown it is sent again.
    fake.queue_entries["ventes"] = [{"Position": "1", "Wait": "90"}]
    supervision.invalidate(org.id)
    assert (await alerts.check_organization(org.id, now=1000.0 + 3600))["raised"] == 2


async def test_e_mail_channel_and_failures_are_independent(db_session, monkeypatch):
    user, org = await _org(db_session, monkeypatch, FakePbx())
    mail = await db_session.create_tool(
        org.id,
        user.id,
        "E-mail",
        {
            "config": {
                "channel": "email",
                "provider": "smtp",
                "smtp_host": "smtp.example.com",
                "sender": "alertes@ivoire-immo.ci",
                "credential_uuid": "cred",
            }
        },
        category="send_message",
    )
    mails = []

    async def credential(organization_id, credential_uuid):
        return "basic_auth", {"username": "u", "password": "p"}

    async def send(config, cred, recipient, subject, body):
        mails.append((recipient, subject))

    async def broken(url, text, payload):
        raise RuntimeError("Slack down")

    from api.services.actions import common, messaging

    monkeypatch.setattr(common, "load_credential", credential)
    monkeypatch.setattr(messaging, "send_email", send)
    monkeypatch.setattr(alerts, "_post_webhook", broken)
    settings = await alerts.save_settings(
        org.id,
        {
            "enabled": True,
            "webhook_url": "https://hooks.example.com/a",
            "email_tool_uuid": str(mail.tool_uuid),
            "email_recipients": ["chef@ivoire-immo.ci", "superviseur@ivoire-immo.ci"],
        },
    )
    outcome = await alerts.notify(
        org.id, settings, "⚠️ Ventes : test", {"event": "test"}
    )
    assert outcome["email"] == "sent" and outcome["webhook"].startswith("failed")
    assert [m[0] for m in mails] == [
        "chef@ivoire-immo.ci",
        "superviseur@ivoire-immo.ci",
    ]
    assert "Ventes : test" in mails[0][1]


async def test_cron_and_routes(db_session, monkeypatch, test_client_factory):
    fake = FakePbx()
    fake.statuses[0]["paused"] = True
    user, org = await _org(db_session, monkeypatch, fake)
    sent = []

    async def webhook(url, text, payload):
        sent.append(payload)

    monkeypatch.setattr(alerts, "_post_webhook", webhook)
    async with test_client_factory(user) as client:
        state = (await client.get("/api/v1/pbx/supervision/alerts")).json()
        assert state["settings"]["enabled"] is False and state["log"] == []
        assert (
            await client.post("/api/v1/pbx/supervision/alerts/test")
        ).status_code == 422
        bad = await client.put(
            "/api/v1/pbx/supervision/alerts", json={"webhook_url": "ftp://x"}
        )
        assert bad.status_code == 422
        saved = await client.put(
            "/api/v1/pbx/supervision/alerts",
            json={
                "enabled": True,
                "max_wait_seconds": 30,
                "webhook_url": "https://hooks.example.com/a",
            },
        )
        assert saved.status_code == 200
        test = await client.post("/api/v1/pbx/supervision/alerts/test")
        assert (
            test.json()["channels"] == {"webhook": "sent"}
            and sent[-1]["event"] == "test"
        )

        totals = await alerts.run_alert_checks()
        assert totals["organizations"] >= 1 and totals["raised"] >= 2
        log = (await client.get("/api/v1/pbx/supervision/alerts")).json()["log"]
        assert {entry["kind"] for entry in log} == {"no_agent", "long_wait"}
        live = (await client.get("/api/v1/pbx/supervision/live")).json()
        assert live["alerts"][0]["level"] == "critical"
