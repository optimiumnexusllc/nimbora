"""Company card: validation, opening hours, prompt, templates, routes, runtime."""

import uuid
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from api.schemas.workflow_configurations import (
    WorkflowConfigurationDefaults as WorkflowConfigurations,
)
from api.services.business import service as business_service
from api.services.business.profile import (
    BusinessProfile,
    business_variables,
    opening_status,
    parse_profile,
    render_business_prompt,
)
from api.services.business.templates import (
    TEMPLATES,
    apply_template_to_profile,
    build_agent_definition,
)
from api.services.workflow.dto import ReactFlowDTO
from api.services.workflow.pipecat_engine_context_composer import (
    compose_system_prompt_for_node,
)
from api.services.workflow.workflow_graph import WorkflowGraph

ABIDJAN = ZoneInfo("Africa/Abidjan")
WEEKDAYS = {
    d: [{"open": "08:00", "close": "12:00"}, {"open": "14:00", "close": "18:00"}]
    for d in ("mon", "tue", "wed", "thu", "fri")
}


def immo(**overrides) -> BusinessProfile:
    data = {
        "industry": "real_estate",
        "name": "Ivoire Immo",
        "activity": "agence immobilière",
        "assistant_name": "Sarah",
        "tone": "chaleureux et professionnel",
        "phone": "+225 27 22 00 00 00",
        "whatsapp": "+225 07 00 00 00 01",
        "address": "Rue des Jardins, Riviera 3",
        "city": "Abidjan",
        "country": "Côte d'Ivoire",
        "directions": "En face de la pharmacie des Jardins",
        "timezone": "Africa/Abidjan",
        "opening_hours": {**WEEKDAYS, "sat": [{"open": "9:00", "close": "13:00"}]},
        "closures": [{"date": "2026-12-25", "label": "Noël"}],
        "languages": ["français", "anglais"],
        "offers": [
            {
                "name": "3 pièces Riviera 3",
                "price": "240 000 FCFA / mois",
                "category": "Location",
            }
        ],
        "faq": [{"question": "Frais d'agence ?", "answer": "Un mois de loyer."}],
        "policies": [{"title": "Visites", "content": "Sur rendez-vous uniquement."}],
        "instructions": "Ne promettez jamais de remise.",
    }
    data.update(overrides)
    return BusinessProfile.model_validate(data)


def at(y, m, d, hh, mm=0):
    return datetime(y, m, d, hh, mm, tzinfo=ABIDJAN)


def test_validation_rules():
    with pytest.raises(ValidationError):
        immo(opening_hours={"mon": [{"open": "18:00", "close": "08:00"}]})
    with pytest.raises(ValidationError):
        immo(
            opening_hours={
                "mon": [
                    {"open": "08:00", "close": "13:00"},
                    {"open": "12:00", "close": "18:00"},
                ]
            }
        )
    with pytest.raises(ValidationError):
        immo(opening_hours={"monday": []})
    with pytest.raises(ValidationError):
        immo(timezone="Mars/Olympus")
    with pytest.raises(ValidationError):
        immo(unknown_field=1)
    # 9:00 is normalized, ranges are sorted.
    profile = immo(
        opening_hours={
            "mon": [
                {"open": "14:00", "close": "18:00"},
                {"open": "8:00", "close": "12:00"},
            ]
        }
    )
    assert [r.open for r in profile.opening_hours["mon"]] == ["08:00", "14:00"]
    # A partially invalid stored card keeps its valid fields.
    kept = parse_profile(
        {"name": "Ivoire Immo", "timezone": "Nowhere/Land", "phone": "+225"}
    )
    assert (
        kept.name == "Ivoire Immo" and kept.phone == "+225" and kept.timezone == "UTC"
    )
    assert parse_profile(None).name == ""


def test_opening_status():
    profile = immo()
    # Friday 20/11/2026
    assert (
        opening_status(profile, at(2026, 11, 20, 10))
        == "Ouvert en ce moment, jusqu'à 12:00."
    )
    assert (
        opening_status(profile, at(2026, 11, 20, 12, 30))
        == "Fermé en ce moment. Réouverture aujourd'hui à 14:00."
    )
    assert (
        opening_status(profile, at(2026, 11, 20, 19))
        == "Fermé en ce moment. Réouverture demain à 09:00."
    )
    assert (
        opening_status(profile, at(2026, 11, 21, 14))
        == "Fermé en ce moment. Réouverture lundi 23 novembre à 08:00."
    )
    # Christmas is a Friday: closed all day, back on Saturday.
    assert (
        opening_status(profile, at(2026, 12, 25, 10))
        == "Fermé en ce moment (Noël). Réouverture demain à 09:00."
    )
    # Computed in the company's time zone, whatever the server's.
    assert opening_status(profile, datetime(2026, 11, 20, 10, tzinfo=UTC)).startswith(
        "Ouvert"
    )
    assert opening_status(immo(opening_hours={})) is None


def test_prompt_section():
    prompt = render_business_prompt(immo(), at(2026, 11, 20, 10))
    for expected in (
        "## Votre entreprise : Ivoire Immo",
        "(agence immobilière)",
        "utilisez le prénom Sarah",
        "Adresse : Rue des Jardins, Riviera 3, Abidjan, Côte d'Ivoire.",
        "En face de la pharmacie",
        "- lundi : 08:00–12:00, 14:00–18:00",
        "- dimanche : fermé",
        "Fermetures exceptionnelles : 25/12/2026 (Noël).",
        "Maintenant : Ouvert en ce moment, jusqu'à 12:00.",
        "- 3 pièces Riviera 3 [Location] — 240 000 FCFA / mois",
        "- Q : Frais d'agence ?\n  R : Un mois de loyer.",
        "- Visites : Sur rendez-vous uniquement.",
        "Consignes de l'entreprise : Ne promettez jamais de remise.",
        "N'inventez jamais",
    ):
        assert expected in prompt, expected
    # Skills on by default are present, the others are not.
    assert "prenez un message" in prompt
    assert "réservez-le" not in prompt
    assert render_business_prompt(immo(enabled=False)) is None
    assert render_business_prompt(BusinessProfile()) is None
    assert business_variables(immo())["name"] == "Ivoire Immo"


def test_composer_appends_card_unless_placed():
    definition, _ = build_agent_definition(TEMPLATES["general"], immo())
    graph = WorkflowGraph(ReactFlowDTO.model_validate(definition))
    node = graph.nodes[graph.start_node_id]
    composed = compose_system_prompt_for_node(
        node=node,
        workflow=graph,
        format_prompt=lambda t: t,
        has_recordings=False,
        business_profile="## Votre entreprise : X",
        customer_memory="Client connu : Awa",
    )
    text = composed.text
    assert "## Votre entreprise : X" in text
    assert text.index("Votre entreprise") < text.index("Client connu")
    node.prompt = "Lisez ceci : {{business_profile}}"
    placed = compose_system_prompt_for_node(
        node=node,
        workflow=graph,
        format_prompt=lambda t: t,
        has_recordings=False,
        business_profile="## Votre entreprise : X",
    )
    assert placed.text.count("Votre entreprise") == 0  # the prompt renders it itself


@pytest.mark.parametrize("template_id", sorted(TEMPLATES))
def test_every_template_builds_a_valid_agent(template_id):
    template = TEMPLATES[template_id]
    definition, configurations = build_agent_definition(
        template, immo(), tool_uuids=["t-1"]
    )
    graph = WorkflowGraph(ReactFlowDTO.model_validate(definition))
    start = graph.nodes[graph.start_node_id]
    assert (
        start.greeting
        == "Bonjour, Ivoire Immo, Sarah à votre écoute. Comment puis-je vous aider ?"
    )
    assert start.tool_uuids == ["t-1"]
    names = [v.name for v in start.extraction_variables]
    assert names and all(n.isidentifier() and n.islower() for n in names)
    validated = WorkflowConfigurations.model_validate(configurations)
    codes = [d.code for d in validated.call_dispositions]
    assert len(codes) == len(set(codes)) and "transfere" in codes
    assert validated.use_business_profile is True
    summary = template.summary()
    assert summary["skills"] and summary["collects"]
    # Example content is itself a valid card.
    apply_template_to_profile(BusinessProfile(name="X"), template, with_examples=True)


def test_apply_template_sets_trade_and_keeps_own_content():
    profile = apply_template_to_profile(
        immo(faq=[], skills={"collect_feedback": True}),
        TEMPLATES["clinic"],
        with_examples=True,
    )
    assert profile.industry == "clinic"
    assert profile.activity == "agence immobilière"  # kept: set by the company
    assert profile.skills.book_appointment is True
    assert profile.skills.collect_feedback is False  # the trade's skill set
    assert profile.offers[0].name == "3 pièces Riviera 3"  # never overwritten
    assert profile.faq[0].question.startswith("Acceptez-vous")  # was empty
    anonymous = build_agent_definition(TEMPLATES["clinic"], BusinessProfile())[0]
    assert (
        anonymous["nodes"][1]["data"]["greeting"]
        == "Bonjour et bienvenue chez notre entreprise. Comment puis-je vous aider ?"
    )


# ------------------------------------------------------------- with the DB


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


async def test_profile_routes_templates_and_isolation(db_session, test_client_factory):
    user, org = await _new_org(db_session)
    other, other_org = await _new_org(db_session)
    # The other company has a booking tool; ours does not yet.
    await db_session.create_tool(
        organization_id=other_org.id,
        user_id=other.id,
        name="Agenda",
        category="book_appointment",
        definition={"schema_version": 1, "type": "book_appointment", "config": {}},
    )
    async with test_client_factory(user) as client:
        empty = (await client.get("/api/v1/business/profile")).json()
        assert empty["name"] == "" and empty["enabled"] is True
        saved = await client.put(
            "/api/v1/business/profile", json=immo().model_dump(mode="json")
        )
        assert saved.status_code == 200
        bad = await client.put(
            "/api/v1/business/profile",
            json={"opening_hours": {"mon": [{"open": "25:00", "close": "26:00"}]}},
        )
        assert bad.status_code == 422
        preview = (
            await client.post(
                "/api/v1/business/profile/preview", json=immo().model_dump(mode="json")
            )
        ).json()
        assert (
            preview["prompt"].startswith("## Votre entreprise : Ivoire Immo")
            and preview["characters"] > 300
        )
        assert {
            t["id"] for t in (await client.get("/api/v1/business/templates")).json()
        } == set(TEMPLATES)
        assert len((await client.get("/api/v1/business/skills")).json()) == 8

        applied = (
            await client.post(
                "/api/v1/business/templates/hospitality/apply",
                json={"with_examples": True},
            )
        ).json()
        assert applied["industry"] == "hospitality" and applied["name"] == "Ivoire Immo"
        assert applied["skills"]["collect_feedback"] is True

        created = (
            await client.post("/api/v1/business/templates/real_estate/agent", json={})
        ).json()
        assert created["name"] == "Immobilier — Ivoire Immo"
        assert created["missing_tools"] == [
            "book_appointment",
            "send_message",
            "schedule_callback",
        ]
        assert (
            await client.post("/api/v1/business/templates/nope/agent", json={})
        ).status_code == 404

    workflow = await db_session.get_workflow(
        created["workflow_id"], organization_id=org.id
    )
    start = next(
        n for n in workflow.workflow_definition["nodes"] if n["type"] == "startCall"
    )
    assert "tool_uuids" not in start["data"]  # never the other company's tool
    assert workflow.workflow_configurations["use_business_profile"] is True
    assert (
        workflow.workflow_configurations["call_dispositions"][0]["code"]
        == "visite_planifiee"
    )

    async with test_client_factory(other) as client:
        assert (await client.get("/api/v1/business/profile")).json()["name"] == ""
        made = (
            await client.post(
                "/api/v1/business/templates/clinic/agent", json={"name": "Secrétariat"}
            )
        ).json()
        assert (
            made["name"] == "Secrétariat"
            and "book_appointment" not in made["missing_tools"]
        )
    theirs = await db_session.get_workflow(
        made["workflow_id"], organization_id=other_org.id
    )
    start = next(
        n for n in theirs.workflow_definition["nodes"] if n["type"] == "startCall"
    )
    assert len(start["data"]["tool_uuids"]) == 1


async def test_runtime_context_and_agent_opt_out(db_session):
    user, org = await _new_org(db_session)
    assert await business_service.load_business_context(org.id, None) == {}
    from api.services.business.profile import save_business_profile

    await save_business_profile(org.id, immo())
    context = await business_service.load_business_context(org.id, None)
    assert context["business_profile"].startswith("## Votre entreprise : Ivoire Immo")
    assert context["business"]["assistant_name"] == "Sarah"

    workflow = await db_session.create_workflow(
        "Sans fiche",
        {"nodes": [], "edges": []},
        user.id,
        org.id,
        workflow_configurations={"use_business_profile": False},
    )
    run = await db_session.create_workflow_run(
        "r",
        workflow.id,
        "textchat",
        user.id,
        organization_id=org.id,
        definition_id=workflow.released_definition_id,
    )
    assert await business_service.load_business_context(org.id, run.id) == {}
    assert await business_service.business_prompt_for_definition(
        org.id, {"use_business_profile": False}
    ) == (None, {})
    section, values = await business_service.business_prompt_for_definition(org.id, {})
    assert section and values["name"] == "Ivoire Immo"


async def test_engine_renders_business_variables():
    from api.services.workflow.pipecat_engine import PipecatEngine

    engine = PipecatEngine.__new__(PipecatEngine)
    engine._call_context_vars = {"customer_name": "Awa"}
    engine._business_context = {"business": {"name": "Ivoire Immo"}}
    assert (
        engine._format_prompt("{{customer_name}} chez {{business.name}}")
        == "Awa chez Ivoire Immo"
    )
    # The run's own context is never modified (it is persisted for text chats).
    assert engine._call_context_vars == {"customer_name": "Awa"}
    engine._business_context = {}
    assert engine._format_prompt("chez {{business.name}}") == "chez "


async def test_card_reaches_every_node_prompt_in_a_running_agent(
    monkeypatch, three_node_workflow
):
    """Real engine + pipeline: the card is in the system prompt of each node."""
    from api.tests.test_pipecat_engine_context_update import (
        run_pipeline_and_capture_context,
    )
    from pipecat.tests import MockLLMService

    async def fake_load(organization_id, workflow_run_id):
        assert (organization_id, workflow_run_id) == (1, 1)
        return {
            "business_profile": "## Votre entreprise : Ivoire Immo",
            "business": {"name": "Ivoire Immo"},
        }

    monkeypatch.setattr(business_service, "load_business_context", fake_load)
    steps = [
        MockLLMService.create_function_call_chunks(
            function_name="collect_info", arguments={}, tool_call_id="c1"
        ),
        MockLLMService.create_function_call_chunks(
            function_name="end_call", arguments={}, tool_call_id="c2"
        ),
        MockLLMService.create_text_chunks("Au revoir !"),
    ]
    llm, _ = await run_pipeline_and_capture_context(
        workflow=three_node_workflow, mock_steps=steps
    )
    assert llm.get_current_step() == 3
    for step in range(3):
        assert "## Votre entreprise : Ivoire Immo" in llm.get_system_prompt_at_step(
            step
        )


async def test_agent_still_runs_when_the_card_fails(monkeypatch, three_node_workflow):
    from api.tests.test_pipecat_engine_context_update import (
        run_pipeline_and_capture_context,
    )
    from pipecat.tests import MockLLMService

    async def broken(organization_id, workflow_run_id):
        raise RuntimeError("db down")

    monkeypatch.setattr(business_service, "load_business_context", broken)
    steps = [
        MockLLMService.create_function_call_chunks(
            function_name="collect_info", arguments={}, tool_call_id="c1"
        ),
        MockLLMService.create_function_call_chunks(
            function_name="end_call", arguments={}, tool_call_id="c2"
        ),
        MockLLMService.create_text_chunks("Au revoir !"),
    ]
    llm, _ = await run_pipeline_and_capture_context(
        workflow=three_node_workflow, mock_steps=steps
    )
    assert llm.get_current_step() == 3
    assert "Votre entreprise" not in llm.get_system_prompt_at_step(0)


# ------------------------------------------------- strategic industries


def test_catalogue_is_consistent():
    from typing import get_args

    from api.services.business.industries.model import SECTORS
    from api.services.business.profile import INDUSTRY_IDS, Industry

    assert set(TEMPLATES) == set(INDUSTRY_IDS) == set(get_args(Industry))
    assert len(TEMPLATES) >= 25
    for template in TEMPLATES.values():
        assert template.sector in SECTORS, template.id
        # Every sector is represented.
    assert {t.sector for t in TEMPLATES.values()} == set(SECTORS)


@pytest.mark.parametrize(
    ("template_id", "must_contain"),
    [
        ("bank", ["code PIN", "OTP", "perte, un vol"]),
        ("microfinance", ["code secret Mobile Money", "changement de carte SIM"]),
        (
            "investment",
            ["conseil d'investissement personnalisé", "performances passées"],
        ),
        ("insurance", ["prise en charge"]),
        ("telecom", ["changement de carte SIM", "PUK"]),
        ("it_support", ["mot de passe", "rançongiciel"]),
        ("energy", ["odeur de gaz", "câble électrique tombé", "technicien agréé"]),
        ("water", ["voie publique"]),
        ("clinic", ["urgence vitale", "diagnostic", "Secret médical"]),
        ("hospital", ["urgence vitale", "numéro de chambre"]),
        ("pharmacy", ["posologie", "centre antipoison"]),
        ("mining", ["Accident, blessé", "plainte de riverain", "confidentielle"]),
        ("industry", ["machine en fonctionnement"]),
        ("construction", ["prix ferme"]),
        ("security", ["code d'alarme", "planning des agents"]),
        ("cybersecurity", ["sans les éteindre", "ne pas payer de rançon"]),
        ("public_service", ["neutre"]),
        ("transport", ["secours"]),
        ("logistics", ["marchandises interdites"]),
    ],
)
def test_trade_rules_reach_the_agent_before_the_method(template_id, must_contain):
    definition, _ = build_agent_definition(TEMPLATES[template_id], immo())
    global_prompt = next(n for n in definition["nodes"] if n["type"] == "globalNode")[
        "data"
    ]["prompt"]
    assert global_prompt.index("Règles impératives") < global_prompt.index("Méthode :")
    for text in must_contain:
        assert text in global_prompt, (template_id, text)


def test_examples_never_carry_phone_numbers():
    """An example number left in place could send someone to a wrong emergency line."""
    import re

    phone = re.compile(r"(\+\d{2,3}[\s\d]{6,}|\b\d{2}[ .]\d{2}[ .]\d{2}[ .]\d{2}\b)")
    for template in TEMPLATES.values():
        for item in [
            *template.example_offers,
            *template.example_faq,
            *template.example_policies,
        ]:
            for value in item.values():
                assert not phone.search(value), (template.id, value)


def test_emergency_contacts_in_card():
    profile = immo(
        emergency_contacts=[
            {"label": "Dépannage 24 h/24", "number": "+225 27 21 00 00 00"}
        ]
    )
    prompt = render_business_prompt(profile, at(2026, 11, 20, 10))
    assert "Numéros d'urgence (à donner en priorité" in prompt
    assert "Dépannage 24 h/24 : +225 27 21 00 00 00" in prompt
    with pytest.raises(ValidationError):
        immo(emergency_contacts=[{"label": "", "number": "1"}])


async def test_strategic_template_summaries_in_api(db_session, test_client_factory):
    user, _ = await _new_org(db_session)
    async with test_client_factory(user) as client:
        templates = {
            t["id"]: t for t in (await client.get("/api/v1/business/templates")).json()
        }
        bank = templates["bank"]
        assert (
            bank["sector"] == "finance"
            and bank["sector_label"] == "Banque, finance et assurance"
        )
        assert any("PCI" in r for r in bank["recommendations"])
        assert any("code PIN" in r for r in bank["rules"])
        applied = (
            await client.post("/api/v1/business/templates/energy/apply", json={})
        ).json()
        assert applied["industry"] == "energy"
        created = (
            await client.post("/api/v1/business/templates/mining/agent", json={})
        ).json()
        assert created["name"] == "Mines et carrières"
