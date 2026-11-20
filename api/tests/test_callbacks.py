"""Callbacks: AI tool, abandoned queue calls, AI dispatch, click-to-call."""

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from api.services.contact_center import callbacks as cb


async def _new_org(db):
    user = await db.create_user_with_email(
        email=f"{uuid.uuid4().hex[:10]}@example.com", password_hash="x"
    )
    org, _ = await db.get_or_create_organization_by_provider_id(
        org_provider_id=f"org_{uuid.uuid4().hex}", user_id=user.id
    )
    await db.add_user_to_organization(user.id, org.id)
    await db.update_user_selected_organization(user.id, org.id)
    user.selected_organization_id = org.id
    return user, org


NOW = datetime(2026, 11, 20, 9, 0, tzinfo=UTC)


def test_preferred_time_parsing():
    paris = ZoneInfo("Europe/Paris")
    assert cb.parse_preferred_time("asap", now=NOW, tz=paris) == NOW
    assert cb.parse_preferred_time(
        "", now=NOW, tz=paris, default_delay_minutes=30
    ) == NOW + timedelta(minutes=30)
    # Naive time = the organization's local time (Paris is UTC+1 in November).
    assert cb.parse_preferred_time("2026-11-21T10:00", now=NOW, tz=paris) == datetime(
        2026, 11, 21, 9, 0, tzinfo=UTC
    )
    assert cb.parse_preferred_time("2026-11-21T10:00Z", now=NOW, tz=paris) == datetime(
        2026, 11, 21, 10, 0, tzinfo=UTC
    )
    # The past means "now"; more than 30 days ahead or garbage is refused.
    assert cb.parse_preferred_time("2020-01-01T10:00", now=NOW, tz=paris) == NOW
    with pytest.raises(cb.CallbackError):
        cb.parse_preferred_time("2027-06-01T10:00", now=NOW, tz=paris)
    with pytest.raises(cb.CallbackError):
        cb.parse_preferred_time("demain", now=NOW, tz=paris)


def test_tool_schema_and_config_validation():
    from api.schemas.tool import CreateToolRequest
    from api.services.workflow.tools.custom_tool import tool_to_function_schema

    request = CreateToolRequest(
        name="Planifier un rappel",
        definition={"type": "schedule_callback", "config": {"queue_slug": "support"}},
    )
    assert request.category == "schedule_callback"
    with pytest.raises(ValidationError):
        CreateToolRequest(
            name="x",
            definition={"type": "schedule_callback", "config": {"assign_to": "ai"}},
        )
    with pytest.raises(ValidationError):
        CreateToolRequest(
            name="x",
            definition={
                "type": "schedule_callback",
                "config": {"assign_to": "human", "workflow_id": 3},
            },
        )

    schema = tool_to_function_schema(
        SimpleNamespace(
            name="Planifier un rappel",
            description="Quand le client veut être rappelé",
            tool_uuid="u1",
            definition=request.definition.model_dump(),
        )
    )
    params = schema["function"]["parameters"]
    assert set(params["properties"]) == {
        "preferred_time",
        "reason",
        "customer_name",
        "phone_number",
    }
    assert params["required"] == ["preferred_time", "reason"]


async def test_tool_creates_then_updates_one_open_callback(db_session):
    _, org = await _new_org(db_session)
    run = SimpleNamespace(
        id=None,
        initial_context={"direction": "inbound", "caller_number": "+33 6 12 34 56 78"},
    )
    first = await cb.schedule_callback_from_call(
        organization_id=org.id,
        workflow_run=run,
        gathered_context={"customer_name": "Awa"},
        config={"assign_to": "human", "queue_slug": "support"},
        arguments={"preferred_time": "2026-11-21T10:00", "reason": "Facture"},
        now=NOW,
    )
    assert first["status"] == "scheduled"
    assert first["scheduled_for_local_time"] == "2026-11-21 10:00"
    stored = await db_session.get_callback_request(org.id, first["callback_id"])
    assert stored.phone == "+33612345678"
    assert stored.customer_name == "Awa" and stored.source == "ai_agent"

    # Same customer asks again, earlier: no duplicate, the earliest time wins.
    second = await cb.schedule_callback_from_call(
        organization_id=org.id,
        workflow_run=run,
        gathered_context={},
        config={"assign_to": "human"},
        arguments={"preferred_time": "asap", "reason": "Urgent : coupure"},
        now=NOW,
    )
    assert second["callback_id"] == first["callback_id"]
    merged = await db_session.get_callback_request(org.id, first["callback_id"])
    assert merged.scheduled_at == NOW
    assert "Urgent" in merged.reason and "Facture" in merged.reason

    bad = await cb.schedule_callback_from_call(
        organization_id=org.id,
        workflow_run=SimpleNamespace(id=None, initial_context={}),
        gathered_context={},
        config={},
        arguments={"preferred_time": "asap", "reason": "x"},
        now=NOW,
    )
    assert bad["status"] == "error"


async def test_abandoned_handoff_becomes_team_callback(db_session):
    _, org = await _new_org(db_session)
    await db_session.create_contact_center_queue(
        org.id, "support", {"name": "Support", "max_wait_seconds": 60}
    )
    old = await db_session.create_call_handoff(
        organization_id=org.id,
        queue_slug="support",
        caller_number="+22790000011",
        status="pending",
        reason="Problème de livraison",
        customer_name="Moussa",
        summary="Colis bloqué",
        collected_data={},
        transcript=[],
        summary_status="ready",
        created_at=NOW - timedelta(minutes=10),
    )
    fresh = await db_session.create_call_handoff(
        organization_id=org.id,
        queue_slug="support",
        caller_number="+22790000012",
        status="pending",
        collected_data={},
        transcript=[],
        summary_status="skipped",
        created_at=NOW - timedelta(seconds=30),
    )

    assert await cb.convert_abandoned_handoffs(NOW) >= 1
    assert (await db_session.get_call_handoff(org.id, old.id)).status == "abandoned"
    assert (await db_session.get_call_handoff(org.id, fresh.id)).status == "pending"
    callbacks = await db_session.list_callback_requests(org.id)
    assert len(callbacks) == 1
    callback = callbacks[0]
    assert callback.source == "queue_timeout" and callback.assign_to == "human"
    assert callback.phone == "+22790000011" and callback.queue_slug == "support"
    assert callback.customer_name == "Moussa" and callback.notes == "Colis bloqué"
    assert callback.handoff_id == old.id


async def test_ai_dispatch_claims_once_and_retries_then_fails(db_session, monkeypatch):
    user, org = await _new_org(db_session)
    workflow = await db_session.create_workflow(
        "Agent rappel", {"nodes": [], "edges": []}, user.id, org.id
    )
    callback = await cb.create_or_update_callback(
        org.id,
        phone="+22790000021",
        scheduled_at=NOW - timedelta(minutes=1),
        source="manual",
        assign_to="ai",
        workflow_id=workflow.id,
        reason="Confirmer le rendez-vous",
    )
    later = await cb.create_or_update_callback(
        org.id,
        phone="+22790000022",
        scheduled_at=NOW + timedelta(hours=1),
        source="manual",
        assign_to="ai",
        workflow_id=workflow.id,
    )

    placed = []

    async def fake_place(c):
        placed.append(c.id)

    monkeypatch.setattr(cb, "_place_ai_callback", fake_place)
    assert await cb.dispatch_due_ai_callbacks(NOW) >= 1
    assert callback.id in placed and later.id not in placed
    claimed = await db_session.get_callback_request(org.id, callback.id)
    assert claimed.status == "in_progress" and claimed.attempts == 1
    # Already in progress: never placed twice.
    placed.clear()
    await cb.dispatch_due_ai_callbacks(NOW)
    assert callback.id not in placed

    # Failure path: retried in 15 minutes, then failed after max attempts.
    async def failing(c):
        raise cb.CallbackError("Concurrent call limit reached")

    monkeypatch.setattr(cb, "_place_ai_callback", failing)
    await db_session.update_callback_request(
        org.id, later.id, {"scheduled_at": NOW - timedelta(minutes=1)}
    )
    await cb.dispatch_due_ai_callbacks(NOW)
    retried = await db_session.get_callback_request(org.id, later.id)
    assert retried.status == "pending"
    assert retried.scheduled_at == NOW + cb.RETRY_DELAY
    assert "Concurrent" in retried.outcome
    await db_session.update_callback_request(
        org.id, later.id, {"attempts": 2, "scheduled_at": NOW}
    )
    await cb.dispatch_due_ai_callbacks(NOW)
    assert (await db_session.get_callback_request(org.id, later.id)).status == "failed"


async def test_ai_callback_closed_from_post_call(db_session):
    user, org = await _new_org(db_session)
    workflow = await db_session.create_workflow(
        "Agent rappel", {"nodes": [], "edges": []}, user.id, org.id
    )
    run = await db_session.create_workflow_run(
        name="WR-1",
        workflow_id=workflow.id,
        mode="twilio",
        user_id=user.id,
        organization_id=org.id,
    )
    callback = await cb.create_or_update_callback(
        org.id,
        phone="+22790000031",
        scheduled_at=NOW,
        source="manual",
        assign_to="ai",
        workflow_id=workflow.id,
    )
    await db_session.update_callback_request(
        org.id,
        callback.id,
        {"status": "in_progress", "attempts": 1, "callback_workflow_run_id": run.id},
    )
    await cb.complete_ai_callback_from_run(
        SimpleNamespace(
            id=run.id,
            usage_info={"call_duration_seconds": 42},
            gathered_context={"call_disposition": "rdv_confirme"},
        ),
        org.id,
    )
    done = await db_session.get_callback_request(org.id, callback.id)
    assert done.status == "done" and "rdv_confirme" in done.outcome


async def test_callback_routes_scope_dial_and_complete(
    db_session, test_client_factory, monkeypatch, tmp_path
):
    from api.routes import contact_center as cc_routes
    from api.services.contact_center import asterisk_config

    monkeypatch.setattr(cc_routes, "CONTACT_CENTER_ENABLED", True)
    monkeypatch.setattr(asterisk_config, "ASTERISK_GENERATED_CONFIG_DIR", str(tmp_path))
    monkeypatch.setattr(asterisk_config, "ASTERISK_ARI_PASSWORD", None)

    user, org = await _new_org(db_session)
    other_user, _ = await _new_org(db_session)
    seat = await db_session.create_contact_center_agent(
        org.id,
        display_name="Awa",
        extension="2001",
        sip_username=f"t{org.id}_2001",
        sip_md5_cred="0" * 32,
        user_id=user.id,
    )

    dialed = []

    async def fake_dial(callback, agent):
        dialed.append((callback.phone, agent.sip_username))
        return "chan-1"

    monkeypatch.setattr(cb, "dial_callback_for_agent", fake_dial)

    async with test_client_factory(user) as client:
        bad = await client.post(
            "/api/v1/contact-center/callbacks",
            json={"phone": "+22790000041", "assign_to": "ai"},
        )
        assert bad.status_code == 400
        created = await client.post(
            "/api/v1/contact-center/callbacks",
            json={
                "phone": "+33 6 12 34 56 79",
                "reason": "Devis",
                "customer_name": "Ali",
            },
        )
        assert created.status_code == 201
        callback = created.json()
        assert callback["phone"] == "+33612345679" and callback["status"] == "pending"

        mine = (await client.get("/api/v1/contact-center/callbacks?mine=true")).json()
        assert [c["id"] for c in mine] == [callback["id"]]

        dial = await client.post(
            f"/api/v1/contact-center/callbacks/{callback['id']}/dial"
        )
        assert dial.status_code == 200 and dial.json()["status"] == "in_progress"
        assert dialed == [("+33612345679", seat.sip_username)]
        # A second click (or a colleague) cannot ring the customer twice.
        again = await client.post(
            f"/api/v1/contact-center/callbacks/{callback['id']}/dial"
        )
        assert again.status_code == 409

        no_answer = await client.post(
            f"/api/v1/contact-center/callbacks/{callback['id']}/complete",
            json={"result": "no_answer", "retry_in_minutes": 30},
        )
        assert no_answer.json()["status"] == "pending"
        assert no_answer.json()["assigned_agent_id"] is None

        await client.post(f"/api/v1/contact-center/callbacks/{callback['id']}/dial")
        reached = await client.post(
            f"/api/v1/contact-center/callbacks/{callback['id']}/complete",
            json={"result": "reached", "outcome": "Devis envoyé"},
        )
        body = reached.json()
        assert body["status"] == "done" and body["outcome"].endswith("Devis envoyé")
        assert body["attempts"] == 2

        closed = (
            await client.get("/api/v1/contact-center/callbacks?view=closed")
        ).json()
        assert [c["id"] for c in closed] == [callback["id"]]

    async with test_client_factory(other_user) as client:
        assert (await client.get("/api/v1/contact-center/callbacks")).json() == []
        assert (
            await client.patch(
                f"/api/v1/contact-center/callbacks/{callback['id']}",
                json={"status": "canceled"},
            )
        ).status_code == 404
        # No seat: cannot place calls.
        assert (
            await client.post(f"/api/v1/contact-center/callbacks/{callback['id']}/dial")
        ).status_code in {403, 404}


def test_callback_dialplan_context_is_generated():
    from api.services.contact_center.asterisk_config import render_extensions

    text = render_extensions([], [])
    assert "[nimbora-callback-out]" in text
    assert "Dial(Local/${EXTEN}@nimbora-outbound,60)" in text
