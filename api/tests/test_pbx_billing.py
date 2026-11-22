"""Human call minutes of the enterprise PBX, billed with the AI minutes."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from api.services.pbx import billing
from api.services.pbx import client as client_module
from api.services.pbx import service as pbx
from api.services.saas import subscription_service, usage_report
from api.tests.pbx_fake import TENANT, FakePbx, install

NOW = datetime(2026, 11, 21, 12, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _clear():
    client_module._TOKENS.clear()
    yield


def _cdr(**fields):
    base = {
        "id": int(uuid.uuid4().int % 10**9),
        "start": "2026-11-21T09:00:00+00:00",
        "answered": True,
        "duration": 120.0,
        "call_direction": "inbound",
        "source_extension": "+2250102030405",
        "source_name": "Ibrahim Touré",
        "destination_extension": "1001",
        "destination_name": "Koffi Yao",
    }
    return {**base, **fields}


async def _org(db, monkeypatch, fake):
    user = await db.create_user_with_email(
        email=f"{uuid.uuid4().hex[:10]}@example.com", password_hash="x"
    )
    org, _ = await db.get_or_create_organization_by_provider_id(
        org_provider_id=f"org_{uuid.uuid4().hex}", user_id=user.id
    )
    await db.add_user_to_organization(user.id, org.id)
    install(monkeypatch, fake)
    connection = await db.save_pbx_connection(
        org.id,
        {
            "base_url": "https://pbx.ivoire-immo.ci",
            "username": "nimbora",
            "password": "secret",
            "tenant_uuid": TENANT,
            "webhook_token": pbx.new_webhook_token(),
        },
    )
    return org, connection


# ------------------------------------------------------------------ rules


def test_only_answered_customer_calls_not_taken_by_ai_are_billed():
    row = billing.billable_call(_cdr(id=7), ai_routed=False)
    assert row == {
        "source": "pbx",
        "external_id": "7",
        "direction": "inbound",
        "started_at": datetime(2026, 11, 21, 9, 0, tzinfo=UTC),
        "billable_seconds": 120,
        "agent_name": "Koffi Yao",
    }
    outbound = billing.billable_call(
        _cdr(
            call_direction="outbound",
            source_extension="1001",
            source_name="Koffi Yao",
            destination_extension="0102030405",
        ),
        ai_routed=False,
    )
    assert outbound["direction"] == "outbound" and outbound["agent_name"] == "Koffi Yao"

    assert billing.billable_call(_cdr(), ai_routed=True) is None  # AI minutes
    assert (
        billing.billable_call(_cdr(answered=False, duration=0), ai_routed=False) is None
    )
    assert (
        billing.billable_call(_cdr(call_direction="internal"), ai_routed=False) is None
    )
    assert billing.billable_call(_cdr(source_extension="1002"), ai_routed=False) is None
    assert billing.billable_call(_cdr(duration=0), ai_routed=False) is None
    assert billing.billable_call(_cdr(start=None), ai_routed=False) is None
    assert billing.billable_call(_cdr(id=None), ai_routed=False) is None


# --------------------------------------------------------------- recording


async def test_webhook_counts_each_call_once(db_session, monkeypatch):
    fake = FakePbx()
    org, connection = await _org(db_session, monkeypatch, fake)
    cdr = _cdr(id=4242)

    assert await pbx.handle_event(connection, "call_log_created", cdr) in {
        "recorded",
        "memory_off",
    }
    assert not await billing.record_call(connection, cdr, ai_routed=False)
    seconds = await db_session.get_organization_human_seconds(
        org.id, NOW - timedelta(days=1), NOW + timedelta(days=1)
    )
    assert seconds == 120


async def test_catch_up_reads_missed_call_logs_and_skips_ai_calls(
    db_session, monkeypatch
):
    fake = FakePbx()
    org, connection = await _org(db_session, monkeypatch, fake)
    fake.cdr = [
        _cdr(id=1, start="2026-11-21T08:00:00+00:00", duration=60),
        _cdr(
            id=2,
            start="2026-11-21T08:10:00+00:00",
            duration=300,
            destination_extension="+22527000099",
        ),  # an AI agent's number
        _cdr(id=3, start="2026-11-21T08:20:00+00:00", answered=False, duration=0),
        _cdr(
            id=4,
            start="2026-11-21T08:30:00+00:00",
            duration=90,
            call_direction="outbound",
            destination_extension="+33612345678",
        ),
        _cdr(id=5, start="2026-11-18T08:00:00+00:00", duration=600),  # too old
    ]

    async def ai_numbers(connection):
        return {"+22527000099"}

    monkeypatch.setattr(billing, "_ai_numbers", ai_numbers)
    monkeypatch.setattr(billing, "PAGE", 2)  # paging through the call logs

    result = await billing.sync_connection(connection, now=NOW)
    assert result == {"read": 4, "counted": 2}
    seconds = await db_session.get_organization_human_seconds(
        org.id, NOW - timedelta(days=1), NOW
    )
    assert seconds == 150
    stored = await db_session.get_pbx_connection(org.id)
    assert stored.usage_synced_at == NOW

    # Next run: nothing new is counted twice.
    again = await billing.sync_connection(stored, now=NOW + timedelta(hours=1))
    assert again["counted"] == 0


async def test_cron_survives_an_unreachable_pbx(db_session, monkeypatch):
    fake = FakePbx()
    await _org(db_session, monkeypatch, fake)
    fake.down.add("call-logd")
    totals = await billing.sync_human_minutes()
    assert totals["counted"] == 0


# ----------------------------------------------------------------- invoice


@pytest.fixture
def saas_on(monkeypatch):
    monkeypatch.setattr(subscription_service, "SAAS_MODE", True)
    monkeypatch.setattr(subscription_service, "SAAS_TRIAL_DAYS", 14)
    monkeypatch.setattr(subscription_service, "SAAS_DEFAULT_PLAN", "starter")


async def _plan(db, **fields):
    code = f"test-{uuid.uuid4().hex[:8]}"
    return await db.upsert_subscription_plan(
        code,
        {
            "name": "Test",
            "monthly_price_cents": 0,
            "included_minutes": 100,
            "overage_price_cents_per_minute": 10,
            "included_human_minutes": 2,
            "human_overage_price_cents_per_minute": 3,
            **fields,
        },
    )


async def test_subscription_shows_human_minutes_and_their_overage(
    db_session, monkeypatch, saas_on
):
    fake = FakePbx()
    org, connection = await _org(db_session, monkeypatch, fake)
    plan = await _plan(db_session)
    await subscription_service.ensure_organization_subscription(org.id)
    await subscription_service.change_plan(org.id, plan, status="active")
    now = datetime.now(UTC)
    for minutes in (3, 2):
        await billing.record_call(
            connection,
            _cdr(start=now.isoformat(), duration=minutes * 60),
            ai_routed=False,
        )

    summary = await subscription_service.get_usage_summary(org.id)
    assert summary.human_used_minutes == 5
    assert summary.human_included_minutes == 2
    assert summary.human_remaining_minutes == 0
    assert summary.human_overage_minutes == 3
    assert summary.estimated_human_overage_cents == 9
    # Human calls never consume the AI allowance.
    assert summary.used_minutes == 0


async def test_monthly_report_lists_ai_and_human_minutes(
    db_session, monkeypatch, saas_on
):
    fake = FakePbx()
    org, connection = await _org(db_session, monkeypatch, fake)
    plan = await _plan(db_session, included_human_minutes=None)
    await subscription_service.ensure_organization_subscription(org.id)
    await subscription_service.change_plan(org.id, plan, status="active")
    await db_session.update_organization_subscription(
        org.id,
        {
            "company_name": "Ivoire Immo",
            "limit_overrides": {"included_human_minutes": 1},
        },
    )
    await billing.record_call(
        connection,
        _cdr(start="2026-10-15T10:00:00+00:00", duration=240),
        ai_routed=False,
    )
    await billing.record_call(  # another month
        connection,
        _cdr(start="2026-09-30T23:59:00+00:00", duration=600),
        ai_routed=False,
    )

    lines = await usage_report.monthly_usage("2026-10")
    line = next(item for item in lines if item.organization_id == org.id)
    assert line.company_name == "Ivoire Immo"
    assert line.human_minutes == 4
    assert line.human_included_minutes == 1  # the company's override
    assert line.human_overage_minutes == 3 and line.human_overage_cents == 9
    assert line.total_overage_cents == line.ai_overage_cents + 9

    csv_text = usage_report.to_csv([line])
    header, row = csv_text.strip().splitlines()
    assert header.split(";")[:3] == ["organization_id", "company_name", "billing_email"]
    assert "Ivoire Immo" in row

    with pytest.raises(ValueError):
        usage_report.month_bounds("2026-13")
    assert usage_report.month_bounds("2026-12")[1] == datetime(2027, 1, 1, tzinfo=UTC)
