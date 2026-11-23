"""Agent tests: a saved agent against a customer played by the AI."""

import json
import uuid

import pytest

from api.services.agent_tests import service as agent_tests
from api.services.agent_tests.service import AgentTestIn, parse_judgement
from api.services.catalog import service as catalog
from api.services.catalog.service import CatalogItemIn
from api.services.workflow.tools.custom_tool import custom_tool_function_name


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


def _definition(tool_uuids):
    return {
        "nodes": [
            {
                "id": "start",
                "type": "startCall",
                "position": {"x": 0, "y": 0},
                "data": {
                    "name": "Accueil",
                    "prompt": "Tu es l'agent de réservation de l'Hôtel Horizon. Utilise le catalogue pour les prix.",
                    "greeting": "Hôtel Horizon, bonjour !",
                    "is_start": True,
                    "allow_interrupt": False,
                    "add_global_prompt": False,
                    "tool_uuids": tool_uuids,
                },
            },
            {
                "id": "end",
                "type": "endCall",
                "position": {"x": 0, "y": 200},
                "data": {
                    "name": "Fin",
                    "prompt": "Prends congé.",
                    "is_end": True,
                    "allow_interrupt": False,
                    "add_global_prompt": False,
                },
            },
        ],
        "edges": [
            {
                "id": "s-e",
                "source": "start",
                "target": "end",
                "data": {"label": "Fin", "condition": "Le client a terminé"},
            }
        ],
    }


async def _agent(db, user, org):
    await catalog.save_item(
        org.id,
        CatalogItemIn(
            kind="room",
            sku="DLX",
            name="Chambre Délux vue mer",
            price=85000,
            unit="la nuit",
            stock=2,
        ),
    )
    cat = await db.create_tool(
        org.id,
        user.id,
        "Catalogue",
        {"type": "search_catalog", "config": {}},
        category="search_catalog",
    )
    lead = await db.create_tool(
        org.id,
        user.id,
        "Prospect",
        {"type": "qualify_lead", "config": {}},
        category="qualify_lead",
    )
    workflow = await db.create_workflow(
        "Réservations", _definition([cat.tool_uuid, lead.tool_uuid]), user.id, org.id
    )
    return (
        workflow,
        custom_tool_function_name("Catalogue"),
        custom_tool_function_name("Prospect"),
    )


class FakeModel:
    """Plays the agent, the customer and the judge from scripts."""

    native_tools = True

    def __init__(self, agent, customer, judge):
        self.agent, self.customer, self.judge = list(agent), list(customer), list(judge)
        self.agent_inputs = []

    async def complete(self, messages, tools=None, *, system=None):
        if system and system.startswith("Tu joues un CLIENT"):
            return {"content": self.customer.pop(0), "tool_calls": []}
        if system and system.startswith("Tu évalues"):
            return {"content": self.judge.pop(0), "tool_calls": []}
        self.agent_inputs.append([dict(m) for m in messages])
        content, calls = self.agent.pop(0)
        return {
            "content": content,
            "tool_calls": [
                {"id": f"c{i}{len(self.agent)}", "name": n, "args": a}
                for i, (n, a) in enumerate(calls)
            ],
        }

    async def close(self):
        pass


async def test_a_simulated_customer_against_the_saved_agent(
    db_session, test_client_factory
):
    user, org = await _new_org(db_session)
    workflow, cat_fn, lead_fn = await _agent(db_session, user, org)
    async with test_client_factory(user) as client:
        created = await client.post(
            "/api/v1/agent-tests",
            json={
                "workflow_id": workflow.id,
                "name": "Client pressé, chambre vue mer",
                "persona": "Tu es Awa, pressée, tu veux une chambre vue mer pour ce soir, 90 000 F au plus.",
                "opening": "Bonjour, il vous reste une chambre vue mer ce soir ?",
                "success_criteria": [
                    "Annonce le prix de la chambre",
                    "Propose de réserver",
                ],
                "must_call": [cat_fn],
                "must_not_call": ["transfer"],
                "forbidden_phrases": ["je ne sais pas"],
                "max_turns": 4,
            },
        )
    assert created.status_code == 201, created.text
    test_id = created.json()["id"]

    model = FakeModel(
        agent=[
            ("", [(cat_fn, {"action": "search", "query": "chambre vue mer"})]),
            ("Oui : la Chambre Délux vue mer, 85 000 F CFA la nuit.", []),
            ("", [(lead_fn, {"need": "chambre vue mer", "budget_max": 90000})]),
            ("C'est noté, à ce soir !", []),
        ],
        customer=["Parfait, je la prends. [FIN]"],
        judge=[
            json.dumps(
                {
                    "criteria": [
                        {"passed": True, "reason": "85 000 F CFA annoncé"},
                        {"passed": False, "reason": "aucune réservation proposée"},
                    ],
                    "summary": "Rapide mais incomplet.",
                }
            )
        ],
    )
    run = await agent_tests.run_test(org.id, test_id, user_id=user.id, model=model)
    result = run["result"]
    # The catalog search ran for real on the company's catalog…
    tool_reply = next(m for m in model.agent_inputs[1] if m["role"] == "tool")
    assert catalog.format_price(85000, "XOF", "la nuit") in tool_reply["content"]
    # …the lead tool was only simulated.
    lead_reply = [m for m in model.agent_inputs[3] if m["role"] == "tool"][-1]
    assert json.loads(lead_reply["content"])["simulated"] is True
    assert [t["role"] for t in result["transcript"]] == [
        "agent",
        "customer",
        "agent",
        "customer",
        "agent",
    ]
    assert result["transcript"][0]["text"] == "Hôtel Horizon, bonjour !"
    assert result["transcript"][3]["text"] == "Parfait, je la prends."
    assert result["outcome"] == "customer_ended"
    assert [c["live"] for c in result["tool_calls"]] == [True, False]
    assert all(c["passed"] for c in result["checks"])
    assert [c["passed"] for c in result["criteria"]] == [True, False]
    assert run["status"] == "failed" and run["summary"] == "Rapide mais incomplet."

    async with test_client_factory(user) as client:
        listed = (
            await client.get(f"/api/v1/agent-tests?workflow_id={workflow.id}")
        ).json()
        assert listed[0]["last_run"]["status"] == "failed"
        detail = (await client.get(f"/api/v1/agent-tests/runs/{run['id']}")).json()
        assert (
            detail["result"]["criteria"][1]["reason"] == "aucune réservation proposée"
        )


async def test_forbidden_phrases_and_tools_fail_the_run(db_session):
    user, org = await _new_org(db_session)
    workflow, cat_fn, _ = await _agent(db_session, user, org)
    test = await db_session.save_agent_test(
        org.id,
        workflow.id,
        AgentTestIn(
            name="Hors sujet",
            persona="Tu demandes la météo de demain.",
            must_not_call=[cat_fn],
            forbidden_phrases=["Je ne sais pas"],
            max_turns=2,
        ).model_dump(),
    )
    model = FakeModel(
        agent=[
            ("", [(cat_fn, {"action": "search", "query": "météo"})]),
            ("Je ne sais pas.", []),
            ("Autre chose ?", []),
        ],
        customer=["Il fera beau demain ?", "Tant pis."],
        judge=[],
    )
    run = await agent_tests.run_test(org.id, test.id, model=model)
    checks = {c["check"]: c["passed"] for c in run["result"]["checks"]}
    assert checks == {
        f"N'utilise pas l'outil {cat_fn}": False,
        "Ne dit jamais « Je ne sais pas »": False,
    }
    assert run["status"] == "failed" and run["result"]["outcome"] == "max_turns"


async def test_runs_are_queued_and_other_companies_see_nothing(
    db_session, monkeypatch, test_client_factory
):
    user, org = await _new_org(db_session)
    other, _ = await _new_org(db_session)
    workflow, _, _ = await _agent(db_session, user, org)
    queued = []

    async def enqueue(name, *args):
        queued.append((name, args))

    monkeypatch.setattr("api.tasks.arq.enqueue_job", enqueue)
    async with test_client_factory(user) as client:
        for name in ("A", "B"):
            await client.post(
                "/api/v1/agent-tests",
                json={
                    "workflow_id": workflow.id,
                    "name": name,
                    "persona": "Un client ordinaire.",
                },
            )
        runs = await client.post(
            "/api/v1/agent-tests/run", json={"workflow_id": workflow.id}
        )
        assert runs.status_code == 202 and [r["status"] for r in runs.json()] == [
            "queued",
            "queued",
        ]
        published = await client.post(
            "/api/v1/agent-tests/run",
            json={"workflow_id": workflow.id, "version": "published"},
        )
        assert published.status_code in (202, 409)
    assert [q[0] for q in queued][:2] == ["run_agent_test", "run_agent_test"]

    async with test_client_factory(other) as client:
        assert (
            await client.get(f"/api/v1/agent-tests?workflow_id={workflow.id}")
        ).status_code == 404
        assert (
            await client.get(f"/api/v1/agent-tests/runs/{runs.json()[0]['id']}")
        ).status_code == 404
        assert (
            await client.post(
                "/api/v1/agent-tests/run", json={"workflow_id": workflow.id}
            )
        ).status_code == 404


async def test_without_a_language_model_the_run_says_so(db_session):
    user, org = await _new_org(db_session)
    workflow, _, _ = await _agent(db_session, user, org)
    test = await db_session.save_agent_test(
        org.id,
        workflow.id,
        AgentTestIn(name="T", persona="Un client ordinaire.").model_dump(),
    )
    run = await agent_tests.run_test(org.id, test.id)
    assert run["status"] == "error" and "modèle" in run["error"].lower()


def test_the_judge_is_read_strictly():
    criteria = ["A", "B", "C"]
    out, summary = parse_judgement(
        'Voici : {"criteria": [{"passed": true, "reason": "ok"}, {"passed": "yes"}], "summary": "Bien"}',
        criteria,
    )
    assert [c["passed"] for c in out] == [True, False, False]  # only a real true counts
    assert out[2]["reason"] == "Non évalué par le juge" and summary == "Bien"
    with pytest.raises(ValueError):
        AgentTestIn(name="x", persona="court")


async def test_suggested_tests_come_from_the_agent_prompts(db_session):
    user, org = await _new_org(db_session)
    workflow, _, _ = await _agent(db_session, user, org)
    seen = []

    class Suggest(FakeModel):
        async def complete(self, messages, tools=None, *, system=None):
            seen.append(messages[0]["content"])
            return {
                "content": json.dumps(
                    {
                        "tests": [
                            {
                                "name": "Nominal",
                                "persona": "Tu veux une chambre double pour deux nuits.",
                                "success_criteria": ["Donne le prix"],
                            },
                            {"name": "", "persona": "x"},
                        ]
                    }
                ),
                "tool_calls": [],
            }

    out = await agent_tests.suggest_tests(
        org.id, workflow.id, model=Suggest([], [], [])
    )
    assert [t["name"] for t in out] == ["Nominal"]  # the unusable one is dropped
    assert "Hôtel Horizon" in seen[0] and "Catalogue (search_catalog)" in seen[0]


def test_tool_function_names_keep_the_letters_of_accented_words():
    assert custom_tool_function_name("Réserver") == "reserver"
    assert custom_tool_function_name("Créer un ticket – SAV") == "creer_un_ticket_sav"
    assert custom_tool_function_name("Prise de rendez-vous") == "prise_de_rendez_vous"
