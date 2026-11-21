"""Missed PBX calls called back by an AI agent; AI handoff cards closed from
the PBX's call logs; the card shown on the softphone and in supervision."""

import uuid
from datetime import UTC, date, datetime, timedelta

import pytest

from api.services.business.profile import (
    BusinessProfile,
    Closure,
    TimeRange,
    next_opening,
)
from api.services.pbx import client as client_module
from api.services.pbx import missed_calls, softphone, supervision
from api.services.pbx import service as pbx
from api.tests.pbx_fake import TENANT, FakePbx, install

BASE = "https://pbx.ivoire-immo.ci"
NOW = datetime(2026, 11, 23, 10, 0, tzinfo=UTC)  # a Monday


@pytest.fixture(autouse=True)
def _clear(monkeypatch):
    client_module._TOKENS.clear()
    supervision._live_cache.clear()

    async def no_throttle(client_key):
        return False

    monkeypatch.setattr(softphone, "_too_many_attempts", no_throttle)
    yield


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
    workflow = await db.create_workflow(
        "Rappels Ivoire Immo", {"nodes": [], "edges": []}, user.id, org.id
    )
    return user, org, workflow


def _cdr(**fields):
    base = {
        "id": int(uuid.uuid4().int % 10**9),
        "start": "2026-11-23T09:42:00+00:00",
        "answered": False,
        "duration": 0.0,
        "call_direction": "inbound",
        "source_extension": "+2250102030405",
        "source_name": "Ibrahim Touré",
        "requested_extension": "3001",
        "destination_extension": "3001",
        "destination_name": "Ventes",
    }
    return {**base, **fields}


def test_next_opening_follows_hours_and_closures():
    profile = BusinessProfile(
        name="Ivoire Immo",
        timezone="Africa/Abidjan",
        opening_hours={
            "mon": [
                TimeRange(open="08:00", close="12:00"),
                TimeRange(open="14:00", close="18:00"),
            ],
            "tue": [TimeRange(open="08:00", close="18:00")],
        },
        closures=[Closure(date=date(2026, 11, 24), label="Férié")],
    )
    assert next_opening(profile, NOW) == NOW  # Monday 10:00: open
    lunch = datetime(2026, 11, 23, 12, 30, tzinfo=UTC)
    assert next_opening(profile, lunch) == datetime(2026, 11, 23, 14, 0, tzinfo=UTC)
    evening = datetime(2026, 11, 23, 19, 0, tzinfo=UTC)
    # Tuesday is closed (holiday): next Monday 08:00.
    assert next_opening(profile, evening) == datetime(2026, 11, 30, 8, 0, tzinfo=UTC)
    assert next_opening(BusinessProfile(name="x"), evening) == evening


async def test_policy_validation(db_session, monkeypatch):
    _, org, workflow = await _org(db_session, monkeypatch, FakePbx())
    connection = await db_session.get_pbx_connection(org.id)
    assert missed_calls.read_policy(connection)["enabled"] is False
    with pytest.raises(pbx.PbxRouteError):
        await missed_calls.save_policy(org.id, {"enabled": True})  # no agent
    with pytest.raises(pbx.PbxRouteError) as other:
        await missed_calls.save_policy(org.id, {"workflow_id": 999999})
    assert other.value.status == 404
    policy = await missed_calls.save_policy(
        org.id, {"enabled": True, "workflow_id": workflow.id, "delay_minutes": 10}
    )
    assert policy["delay_minutes"] == 10 and policy["scope"] == "queues"


async def test_missed_queue_call_is_called_back_by_the_ai(db_session, monkeypatch):
    fake = FakePbx()
    _, org, workflow = await _org(db_session, monkeypatch, fake)
    connection = await db_session.get_pbx_connection(org.id)
    # Off: nothing happens.
    assert (
        await missed_calls.on_call_log(connection, _cdr(), ai_routed=False, now=NOW)
        is None
    )

    await missed_calls.save_policy(
        org.id,
        {
            "enabled": True,
            "workflow_id": workflow.id,
            "delay_minutes": 5,
            "within_hours": False,
        },
    )
    connection = await db_session.get_pbx_connection(org.id)
    done = await missed_calls.on_call_log(connection, _cdr(), ai_routed=False, now=NOW)
    assert done == "missed_callback"
    callback = await db_session.find_open_callback_for_phone(org.id, "+2250102030405")
    assert callback.source == "pbx_missed" and callback.assign_to == "ai"
    assert callback.workflow_id == workflow.id
    assert callback.scheduled_at == NOW + timedelta(minutes=5)
    assert callback.customer_name == "Ibrahim Touré"
    assert "file Ventes" in callback.reason and "23/11 à 09:42" in callback.reason

    # A second missed call merges into the same callback.
    await missed_calls.on_call_log(connection, _cdr(), ai_routed=False, now=NOW)
    recent = await missed_calls.recent_callbacks(org.id)
    assert len(recent) == 1

    # Calls to an extension are left alone with the "queues" scope…
    direct = _cdr(
        source_extension="+2250707070707",
        requested_extension="1001",
        destination_extension="1001",
        destination_name="Koffi Yao",
    )
    assert (
        await missed_calls.on_call_log(connection, direct, ai_routed=False, now=NOW)
        is None
    )
    # …and called back with "all".
    await missed_calls.save_policy(org.id, {"scope": "all"})
    connection = await db_session.get_pbx_connection(org.id)
    assert (
        await missed_calls.on_call_log(connection, direct, ai_routed=False, now=NOW)
        == "missed_callback"
    )
    other = await db_session.find_open_callback_for_phone(org.id, "+2250707070707")
    assert "Koffi Yao" in other.reason

    # The customer gets through (calls again, or someone calls them): the
    # automatic callback is canceled.
    served = _cdr(
        answered=True,
        duration=95.0,
        destination_extension="1001",
        destination_user_uuid="u-1",
    )
    assert (
        await missed_calls.on_call_log(connection, served, ai_routed=False, now=NOW)
        == "served"
    )
    canceled = await db_session.get_callback_request(org.id, callback.id)
    assert canceled.status == "canceled" and "servi" in canceled.outcome

    # Internal calls, AI calls, outbound attempts, hidden numbers: ignored.
    for cdr, routed in (
        (_cdr(call_direction="internal"), False),
        (_cdr(source_extension="+2250808080808"), True),
        (
            _cdr(call_direction="outbound", destination_extension="+2250909090909"),
            False,
        ),
        (_cdr(source_extension="anonymous"), False),
    ):
        assert (
            await missed_calls.on_call_log(connection, cdr, ai_routed=routed, now=NOW)
            is None
        )


async def test_blocked_numbers_are_never_called_back(db_session, monkeypatch):
    fake = FakePbx()
    _, org, workflow = await _org(db_session, monkeypatch, fake)
    await missed_calls.save_policy(
        org.id, {"enabled": True, "workflow_id": workflow.id}
    )
    from api.services.telephony import blocklist

    async def blocked(organization_id, phone, direction):
        return object()

    monkeypatch.setattr(blocklist, "find_block", blocked)
    connection = await db_session.get_pbx_connection(org.id)
    await missed_calls.on_call_log(connection, _cdr(), ai_routed=False, now=NOW)
    assert (
        await db_session.find_open_callback_for_phone(org.id, "+2250102030405") is None
    )


async def test_ai_handoff_cards_are_closed_from_call_logs(db_session, monkeypatch):
    fake = FakePbx()
    _, org, workflow = await _org(db_session, monkeypatch, fake)
    await missed_calls.save_policy(
        org.id, {"enabled": True, "workflow_id": workflow.id, "within_hours": False}
    )
    connection = await db_session.get_pbx_connection(org.id)

    answered = await db_session.create_call_handoff(
        organization_id=org.id,
        queue_slug="pbx:q1",
        caller_number="+2250700112233",
        status="pending",
        reason="Visite à Cocody",
    )
    log = _cdr(
        source_extension="+2250700112233",
        answered=True,
        duration=120.0,
        destination_user_uuid="u-1",
        requested_extension="+22527000000",
    )
    # Answered by a person, even on a number routed to the AI first.
    assert (
        await missed_calls.on_call_log(connection, log, ai_routed=True)
        == "handoff_answered"
    )
    assert (await db_session.get_call_handoff(org.id, answered.id)).status == "answered"

    abandoned = await db_session.create_call_handoff(
        organization_id=org.id,
        queue_slug="pbx:q1",
        caller_number="+2250505050505",
        status="pending",
        reason="Contester une facture d'eau",
        customer_name="Mme Bamba",
        summary="Facture de septembre trop élevée ; souhaite un échéancier.",
    )
    # The AI answered (so the log says "answered"), but nobody after it.
    log = _cdr(
        source_extension="+2250505050505",
        answered=True,
        duration=80.0,
        requested_extension="+22527000000",
    )
    assert (
        await missed_calls.on_call_log(connection, log, ai_routed=True)
        == "handoff_abandoned_callback"
    )
    assert (
        await db_session.get_call_handoff(org.id, abandoned.id)
    ).status == "abandoned"
    callback = await db_session.find_open_callback_for_phone(org.id, "+2250505050505")
    assert callback.reason == "Contester une facture d'eau"
    assert callback.handoff_id == abandoned.id and callback.customer_name == "Mme Bamba"
    assert callback.notes.startswith("Facture de septembre")


async def test_webhook_runs_the_missed_call_policy(
    db_session, monkeypatch, test_client_factory
):
    fake = FakePbx()
    user, org, workflow = await _org(db_session, monkeypatch, fake)
    async with test_client_factory(user) as client:
        bad = await client.put("/api/v1/pbx/missed-calls", json={"enabled": True})
        assert bad.status_code == 422
        saved = await client.put(
            "/api/v1/pbx/missed-calls",
            json={
                "enabled": True,
                "workflow_id": workflow.id,
                "delay_minutes": 0,
                "within_hours": False,
            },
        )
        assert saved.status_code == 200
        connection = await db_session.get_pbx_connection(org.id)
        delivered = await client.post(
            f"/api/v1/pbx/events/{connection.webhook_token}?event=call_log_created",
            json={"name": "call_log_created", "data": _cdr()},
        )
        assert delivered.status_code == 204
        state = (await client.get("/api/v1/pbx/missed-calls")).json()
        assert state["policy"]["enabled"] is True
        assert state["recent"][0]["phone"] == "+2250102030405"
        assert state["recent"][0]["status"] == "pending"


async def test_softphone_and_supervision_show_the_card(
    db_session, monkeypatch, test_client_factory
):
    fake = FakePbx()
    fake.queue_entries["ventes"][0]["CallerIDNum"] = "+2250102030405"
    user, org, _ = await _org(db_session, monkeypatch, fake)
    card = await db_session.create_call_handoff(
        organization_id=org.id,
        queue_slug="pbx:q1",
        caller_number="+2250102030405",
        status="pending",
        reason="Résilier le bail",
        sentiment="frustrated",
        summary="Le client part à Yamoussoukro fin décembre.",
    )
    live = await supervision.live(org.id, use_cache=False)
    caller = live["queues"][0]["callers"][0]
    assert caller["handoff"]["reason"] == "Résilier le bail"
    assert caller["handoff"]["sentiment"] == "frustrated"
    assert live["calls"][0]["handoff"] is None  # Awa was not handed over

    activation = await softphone.create_activation(org.id, "u-1", created_by=user.id)
    paired = await softphone.activate(
        activation["code"],
        device_name="PC",
        platform="windows",
        app_version="1.1.0",
        client_key="k",
    )
    headers = {"Authorization": f"Bearer {paired['token']}"}
    async with test_client_factory(user) as client:
        ringing = await client.get(
            "/api/v1/softphone/handoff",
            params={"number": "0102030405"},
            headers=headers,
        )
        if ringing.json()["card"] is None:  # national format, depends on country rules
            ringing = await client.get(
                "/api/v1/softphone/handoff",
                params={"number": "+225 01 02 03 04 05"},
                headers=headers,
            )
        assert ringing.json()["card"]["id"] == card.id
        assert ringing.json()["card"]["summary"].startswith("Le client part")
        assert (
            await client.get("/api/v1/softphone/handoff", params={"number": "+225"})
        ).status_code == 401
        took = await client.post(
            f"/api/v1/softphone/handoff/{card.id}/answered", headers=headers
        )
        assert took.status_code == 204
        assert (await db_session.get_call_handoff(org.id, card.id)).status == "answered"
        again = await client.get(
            "/api/v1/softphone/handoff",
            params={"number": "+2250102030405"},
            headers=headers,
        )
        assert again.json()["card"] is None  # no longer waiting
        assert (
            await client.post(
                "/api/v1/softphone/handoff/nope/answered", headers=headers
            )
        ).status_code == 404

        targets = await client.get("/api/v1/pbx/transfer-targets")
        assert (
            targets.status_code == 200
            and targets.json()[0]["destination"] == "pbx-queue:1"
        )
