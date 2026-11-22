"""Leads: qualification by the agent, pipeline in the console."""

import uuid

from api.services.actions.common import ActionContext
from api.services.actions.dispatch import run_action
from api.services.leads.service import score_of


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


def _ctx(org_id, phone="+2250700112233", run=None, channel=None):
    initial = {"caller_number": phone} if phone else {}
    if channel:
        initial["channel"] = channel
    return ActionContext(
        organization_id=org_id,
        tool_uuid="lead-1",
        tool_name="Prospect",
        workflow_run_id=run,
        initial_context=initial,
    )


def test_each_answer_adds_to_the_score():
    assert score_of({}) == 0
    assert score_of({"need": "Villa 4 chambres"}) == 25
    full = {
        "need": "Villa",
        "budget_max": 1,
        "timeline": "3 mois",
        "decision_maker": True,
        "name": "Awa",
        "interests": ["Villa Riviera"],
    }
    assert score_of(full) == 100
    assert score_of({**full, "decision_maker": False}) == 92


async def test_the_agent_qualifies_over_two_calls_without_duplicates(db_session):
    _, org = await _new_org(db_session)
    first = await run_action(
        "qualify_lead",
        _ctx(org.id, run=11),
        {"currency": "XOF"},
        {"need": "Villa 4 chambres avec piscine à Cocody", "budget_max": 150000000},
    )
    assert first["status"] == "ok"
    assert first["score"] == 50 and first["stage"] == "Nouveau"
    assert "when they want it" in first["hint"]

    # Next call from the same number completes the same lead.
    second = await run_action(
        "qualify_lead",
        _ctx(org.id, run=12),
        {},
        {
            "timeline": "dans 3 mois",
            "decision_maker": True,
            "name": "Awa Koné",
            "interests": ["Villa Riviera"],
            "notes": "Veut visiter samedi",
        },
    )
    assert second["lead_id"] == first["lead_id"]
    assert second["score"] == 100 and second["stage"] == "Qualifié"
    assert second["still_unknown"] == []
    leads = await db_session.list_leads(org.id)
    assert len(leads) == 1
    lead = leads[0]
    assert (lead.budget_max, lead.source, lead.workflow_run_id) == (
        150000000,
        "call",
        12,
    )
    assert lead.interests == ["Villa Riviera"]
    assert "Veut visiter samedi" in lead.notes


async def test_a_closed_lead_is_not_reopened_and_web_leads_follow_the_conversation(
    db_session,
):
    _, org = await _new_org(db_session)
    won = await run_action("qualify_lead", _ctx(org.id), {}, {"need": "Studio"})
    await db_session.update_lead(org.id, won["lead_id"], {"stage": "won"})
    again = await run_action("qualify_lead", _ctx(org.id), {}, {"need": "Bureau"})
    assert again["lead_id"] != won["lead_id"]

    # No number (web chat): the conversation keeps its own lead.
    web = await run_action(
        "qualify_lead",
        _ctx(org.id, phone=None, run=99, channel="web"),
        {},
        {"need": "Devis"},
    )
    same = await run_action(
        "qualify_lead",
        _ctx(org.id, phone=None, run=99, channel="web"),
        {},
        {"email": "a@b.ci"},
    )
    assert web["lead_id"] == same["lead_id"]
    lead = await db_session.get_lead(org.id, web["lead_id"])
    assert (lead.source, lead.email) == ("web", "a@b.ci")


async def test_pipeline_in_the_console(db_session, test_client_factory):
    user, org = await _new_org(db_session)
    other, _ = await _new_org(db_session)
    await run_action(
        "qualify_lead", _ctx(org.id), {}, {"need": "Villa", "budget_max": 150000000}
    )
    async with test_client_factory(user) as client:
        created = await client.post(
            "/api/v1/leads",
            json={
                "name": "Ibrahim Sanogo",
                "company": "Sanogo SARL",
                "need": "Bureaux",
                "budget_min": 2000000,
                "budget_max": 1000000,
                "stage": "proposal",
            },
        )
        listed = (await client.get("/api/v1/leads")).json()
        searched = (await client.get("/api/v1/leads", params={"q": "sanogo"})).json()
        lost = await client.post(
            f"/api/v1/leads/{created.json()['id']}/stage",
            json={"stage": "lost", "lost_reason": "Trop cher"},
        )
        reopened = await client.post(
            f"/api/v1/leads/{created.json()['id']}/stage", json={"stage": "negotiation"}
        )
        exported = await client.get("/api/v1/leads/export.csv")
    async with test_client_factory(other) as client:
        foreign = (await client.get("/api/v1/leads")).json()
        foreign_move = await client.post(
            f"/api/v1/leads/{created.json()['id']}/stage", json={"stage": "won"}
        )
    assert created.status_code == 201
    made = created.json()
    # Budgets given the wrong way round are put back in order.
    assert (made["budget_min"], made["budget_max"]) == (1000000, 2000000)
    assert made["budget_text"] == "1 000 000 F CFA à 2 000 000 F CFA"
    assert len(listed["leads"]) == 2
    stages = {p["stage"]: p for p in listed["pipeline"]}
    assert [p["stage"] for p in listed["pipeline"]] == [
        "new",
        "qualified",
        "proposal",
        "negotiation",
        "won",
        "lost",
    ]
    assert (
        stages["new"]["count"] == 1
        and stages["new"]["budgets"][0]["text"] == "150 000 000 F CFA"
    )
    assert [x["name"] for x in searched["leads"]] == ["Ibrahim Sanogo"]
    assert lost.json()["closed_at"] and lost.json()["lost_reason"] == "Trop cher"
    assert reopened.json()["closed_at"] is None
    assert "Ibrahim Sanogo" in exported.text
    assert foreign["leads"] == [] and foreign_move.status_code == 404


async def test_the_lead_tool_can_be_saved(db_session, test_client_factory):
    user, _ = await _new_org(db_session)
    async with test_client_factory(user) as client:
        response = await client.post(
            "/api/v1/tools/",
            json={
                "name": "Prospect",
                "definition": {
                    "type": "qualify_lead",
                    "config": {"qualified_score": 70},
                },
            },
        )
    assert response.status_code in (200, 201), response.text
