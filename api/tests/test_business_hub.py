"""AI Business Hub: figures by channel, compared with the period before."""

import uuid
from datetime import UTC, datetime, timedelta

from api.db.models import (
    AppointmentModel,
    CallHandoffModel,
    CustomerProfileModel,
    HumanCallUsageModel,
    LeadModel,
    TelephonyConfigurationModel,
    WhatsAppConversationModel,
    WorkflowRunModel,
)
from api.services.business_hub.service import (
    business_hub,
    change,
    channel_of,
    period_bounds,
)

NOW = datetime(2026, 11, 22, 15, 0, tzinfo=UTC)


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


def test_channels_and_changes():
    assert [
        channel_of(m) for m in ("ari", "twilio", "whatsapp", "textchat", "webrtc")
    ] == [
        "phone",
        "phone",
        "whatsapp",
        "web",
        "web",
    ]
    assert change(15, 10) == 50.0
    assert change(5, 0) is None
    start, end, previous, days = period_bounds("7d", NOW, "Africa/Abidjan")
    assert (end - start).days == 7 and (start - previous).days == 7
    assert days[-1] == "2026-11-22" and len(days) == 7


async def _seed(db, user, org):
    async with db.async_session() as session:
        whatsapp = TelephonyConfigurationModel(
            organization_id=org.id, name="WhatsApp", provider="whatsapp", credentials={}
        )
        session.add(whatsapp)
        await session.commit()
        await session.refresh(whatsapp)
    workflow = await db.create_workflow(
        "Accueil", {"nodes": [], "edges": []}, user.id, org.id
    )
    day = timedelta(days=1)
    rows = [
        # This week: 3 AI phone calls (2 in, 1 out, 120 s each), 1 web chat.
        *[
            WorkflowRunModel(
                name="r",
                workflow_id=workflow.id,
                mode="ari",
                call_type=c,
                created_at=NOW - day,
                usage_info={"call_duration_seconds": 120},
            )
            for c in ("inbound", "inbound", "outbound")
        ],
        WorkflowRunModel(
            name="w",
            workflow_id=workflow.id,
            mode="textchat",
            call_type="inbound",
            created_at=NOW - 2 * day,
            usage_info={},
        ),
        # The week before: 1 AI call.
        WorkflowRunModel(
            name="old",
            workflow_id=workflow.id,
            mode="ari",
            call_type="inbound",
            created_at=NOW - 9 * day,
            usage_info={"call_duration_seconds": 60},
        ),
        HumanCallUsageModel(
            organization_id=org.id,
            source="pbx",
            external_id="h1",
            direction="inbound",
            started_at=NOW - day,
            billable_seconds=300,
        ),
        WhatsAppConversationModel(
            organization_id=org.id,
            telephony_configuration_id=whatsapp.id,
            phone_number_id="p",
            customer_wa_id="225070",
            message_count=6,
            created_at=NOW - 3 * day,
        ),
        CallHandoffModel(
            organization_id=org.id,
            caller_number="+225070",
            created_at=NOW - day,
            answered_at=NOW - day,
        ),
        AppointmentModel(
            organization_id=org.id,
            calendar_key="cal",
            start_at=NOW + 2 * day,
            end_at=NOW + 2 * day + timedelta(minutes=30),
            status="booked",
            created_at=NOW - day,
        ),
        LeadModel(
            organization_id=org.id,
            need="Villa",
            stage="won",
            currency="XOF",
            created_at=NOW - 2 * day,
            closed_at=NOW - day,
        ),
        LeadModel(
            organization_id=org.id,
            need="Bureau",
            stage="qualified",
            currency="XOF",
            budget_max=50_000_000,
            created_at=NOW - day,
        ),
        CustomerProfileModel(
            organization_id=org.id,
            phone="+225070",
            phone_suffix="225070",
            first_seen_at=NOW - day,
            last_seen_at=NOW - day,
        ),
    ]
    async with db.async_session() as session:
        session.add_all(rows)
        await session.commit()


async def test_the_hub_counts_each_channel_and_compares(
    db_session, test_client_factory
):
    user, org = await _new_org(db_session)
    await _seed(db_session, user, org)

    hub = await business_hub(org.id, "7d", now=NOW)
    kpis = hub["kpis"]
    assert kpis["ai_calls"]["value"] == 3
    assert (
        kpis["ai_calls"]["inbound"],
        kpis["ai_calls"]["outbound"],
        kpis["ai_calls"]["minutes"],
    ) == (2, 1, 6)
    assert kpis["ai_calls"]["change"] == 200.0  # 3 vs 1 the week before
    assert (kpis["human_calls"]["value"], kpis["human_calls"]["minutes"]) == (1, 5)
    assert kpis["conversations"]["value"] == 6  # 3 AI + 1 human + 1 WhatsApp + 1 web
    assert kpis["appointments"]["value"] == 1 and kpis["appointments"]["upcoming"] == 1
    assert (
        kpis["leads"]["value"],
        kpis["leads"]["won"],
        kpis["leads"]["conversion"],
    ) == (2, 1, 50.0)
    assert kpis["customers"]["value"] == 1
    channels = {c["channel"]: c for c in hub["channels"]}
    assert (
        channels["phone"]["count"],
        channels["whatsapp"]["count"],
        channels["web"]["count"],
    ) == (4, 1, 1)
    assert hub["actions"]["handoffs"] == 1 and hub["actions"]["handoff_rate"] == 33.3
    assert hub["actions"]["whatsapp_messages"] == 6
    assert hub["pipeline"] == [
        {
            "currency": "XOF",
            "open_leads": 1,
            "budget": 50_000_000,
            "text": "50 000 000 F CFA",
        }
    ]
    yesterday = next(d for d in hub["daily"] if d["day"] == "2026-11-21")
    assert (
        yesterday["phone_ai"],
        yesterday["phone_human"],
        yesterday["appointments"],
        yesterday["leads"],
    ) == (3, 1, 1, 1)
    assert len(hub["daily"]) == 7

    # The route, and another company sees nothing of it.
    other, _ = await _new_org(db_session)
    async with test_client_factory(other) as client:
        foreign = (
            await client.get("/api/v1/business-hub", params={"period": "90d"})
        ).json()
    assert foreign["kpis"]["conversations"]["value"] == 0
    assert len(foreign["daily"]) == 90
    async with test_client_factory(user) as client:
        bad = await client.get("/api/v1/business-hub", params={"period": "1y"})
    assert bad.status_code == 422
