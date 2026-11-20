"""Customer memory: phone matching, prompt injection, post-call recording."""

import uuid
from types import SimpleNamespace

from api.services.customer_memory import service as memory


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


def test_phone_normalization_and_direction():
    assert memory.normalize_phone("+227 90-12.34.56") == "+22790123456"
    assert memory.normalize_phone("0033 6 12 34 56 78") == "+33612345678"
    assert memory.normalize_phone("sip:+22790123456@carrier") == "+22790123456"
    assert memory.normalize_phone("123") is None
    assert memory.normalize_phone(None) is None
    assert memory.phone_suffix("+33612345678") == memory.phone_suffix("0612345678")

    inbound = {
        "direction": "inbound",
        "caller_number": "+22790000001",
        "phone_number": "+1",
    }
    assert memory.customer_phone_from_context(inbound) == "+22790000001"
    # Outbound: our own DID is in caller_number; the customer is the callee.
    outbound = {
        "direction": "outbound",
        "caller_number": "+33100000000",
        "phone_number": "+22790000002",
    }
    assert memory.customer_phone_from_context(outbound) == "+22790000002"


def test_memory_section_respects_prompt_placement():
    ctx = {"customer_memory": "## Mémoire client\n- Nom : Awa"}
    assert (
        memory.memory_section_for_prompt(ctx, "Tu es un agent.")
        == ctx["customer_memory"]
    )
    assert (
        memory.memory_section_for_prompt(ctx, "Contexte: {{customer_memory}}") is None
    )
    assert memory.memory_section_for_prompt({}, "x") is None


async def test_unknown_then_known_caller_with_local_vs_international_format(db_session):
    _, org = await _new_org(db_session)
    ctx = {"direction": "inbound", "caller_number": "+33612345678"}
    assert await memory.load_memory_context(org.id, ctx) == {"customer_known": False}

    profile = await db_session.get_or_create_customer_profile(
        org.id, "+33612345678", memory.phone_suffix("+33612345678")
    )
    await db_session.update_customer_profile(
        org.id,
        profile.id,
        {
            "name": "Awa Diallo",
            "notes": "Cliente VIP",
            "tags": ["vip"],
            "attributes": {"ville": "Niamey"},
        },
    )
    await db_session.record_customer_interaction(
        org.id,
        profile.id,
        workflow_run_id=None,
        fields={
            "summary": "A demandé le suivi de la commande 42.",
            "sentiment": "neutral",
        },
    )
    # Same person dialing with the national format.
    loaded = await memory.load_memory_context(
        org.id, {"direction": "inbound", "caller_number": "06 12 34 56 78"}
    )
    assert loaded["customer_known"] is True and loaded["customer_name"] == "Awa Diallo"
    assert loaded["customer_total_calls"] == 1
    prompt = loaded["customer_memory"]
    assert (
        "Awa Diallo" in prompt and "Cliente VIP" in prompt and "commande 42" in prompt
    )
    assert "ville : Niamey" in prompt


async def test_memory_is_isolated_per_organization_and_can_be_disabled(db_session):
    _, org_a = await _new_org(db_session)
    _, org_b = await _new_org(db_session)
    await db_session.get_or_create_customer_profile(
        org_a.id, "+22790000003", "790000003"
    )
    ctx = {"direction": "inbound", "caller_number": "+22790000003"}
    assert (await memory.load_memory_context(org_b.id, ctx)) == {
        "customer_known": False
    }
    assert (await memory.load_memory_context(org_a.id, ctx))["customer_known"] is True

    await db_session.upsert_configuration(
        org_a.id, memory.SETTING_KEY, {"enabled": False}
    )
    assert await memory.load_memory_context(org_a.id, ctx) == {}


def _run(run_id, *, phone="+22790000004", gathered=None, annotations=None, duration=42):
    return SimpleNamespace(
        id=run_id,
        initial_context={"direction": "inbound", "caller_number": phone},
        gathered_context=gathered or {},
        annotations=annotations or {},
        usage_info={"call_duration_seconds": duration},
        logs={},
        workflow=SimpleNamespace(name="Accueil", organization_id=None),
        definition=None,
    )


async def test_post_call_recording_is_idempotent_and_keeps_manual_name(
    db_session, monkeypatch
):
    _, org = await _new_org(db_session)
    monkeypatch.setattr(memory, "_transcript", lambda run: "Client: bonjour")

    async def fake_summary(run, transcript):
        return {
            "summary": "Demande de devis.",
            "customer_name": "Moussa",
            "sentiment": "positive",
            "reason": None,
            "next_step": None,
        }

    monkeypatch.setattr(memory, "_summarize_call", fake_summary)
    run = _run(
        None,
        gathered={
            "budget": "5000",
            "call_disposition": "interested",
            "mps_correlation_id": "x",
        },
    )
    assert await memory.record_call_in_memory(run, org.id) is True

    profile = await db_session.find_customer_profile(
        org.id, "+22790000004", "790000004"
    )
    assert profile.name == "Moussa" and profile.total_calls == 1
    assert profile.attributes == {"budget": "5000"}
    assert profile.last_summary == "Demande de devis."
    (interaction,) = await db_session.list_customer_interactions(org.id, profile.id)
    assert interaction.outcome == "interested" and interaction.sentiment == "positive"

    # Team renames the customer by hand: later calls never overwrite it.
    await db_session.update_customer_profile(
        org.id, profile.id, {"name": "M. Moussa Traoré"}
    )
    assert await memory.record_call_in_memory(_run(None), org.id) is True
    profile = await db_session.get_customer_profile(org.id, profile.id)
    assert profile.name == "M. Moussa Traoré" and profile.total_calls == 2


async def test_qa_summary_preferred_and_silent_calls_skipped(db_session, monkeypatch):
    _, org = await _new_org(db_session)
    monkeypatch.setattr(memory, "_transcript", lambda run: "")
    run = _run(None, phone="+22790000005", duration=0)
    assert await memory.record_call_in_memory(run, org.id) is False

    monkeypatch.setattr(memory, "_transcript", lambda run: "Client: allo")

    async def no_llm(run, transcript):
        raise RuntimeError("LLM down")

    monkeypatch.setattr(memory, "_summarize_call", no_llm)
    run = _run(
        None,
        phone="+22790000005",
        annotations={"qa_1": {"node_results": {"n": {"summary": "Résumé QA."}}}},
    )
    assert await memory.record_call_in_memory(run, org.id) is True
    profile = await db_session.find_customer_profile(
        org.id, "+22790000005", "790000005"
    )
    assert profile.last_summary == "Résumé QA."


async def test_customer_routes_and_right_to_be_forgotten(
    db_session, test_client_factory
):
    user, org = await _new_org(db_session)
    other, _ = await _new_org(db_session)
    async with test_client_factory(user) as client:
        created = await client.post(
            "/api/v1/customers",
            json={
                "phone": "+227 90 00 00 06",
                "name": "Fatou",
                "tags": ["vip", "vip", " pro "],
            },
        )
        assert created.status_code == 201, created.text
        body = created.json()
        assert body["phone"] == "+22790000006" and body["tags"] == ["vip", "pro"]
        cid = body["id"]

        listed = (await client.get("/api/v1/customers?q=fatou")).json()
        assert listed["total"] == 1 and listed["memory_enabled"] is True
        patched = await client.patch(
            f"/api/v1/customers/{cid}", json={"notes": "Préfère le soir"}
        )
        assert patched.json()["notes"] == "Préfère le soir"
        assert (
            await client.put("/api/v1/customers/settings", json={"enabled": False})
        ).json() == {"enabled": False}
        assert (await client.get("/api/v1/customers/settings")).json() == {
            "enabled": False
        }

    async with test_client_factory(other) as client:
        assert (await client.get(f"/api/v1/customers/{cid}")).status_code == 404
        assert (await client.delete(f"/api/v1/customers/{cid}")).status_code == 404

    async with test_client_factory(user) as client:
        assert (await client.delete(f"/api/v1/customers/{cid}")).status_code == 204
        assert (await client.get(f"/api/v1/customers/{cid}")).status_code == 404


def test_composer_appends_memory_section():
    from api.services.workflow.pipecat_engine_context_composer import (
        compose_system_prompt_for_node,
    )

    node = SimpleNamespace(id="n1", prompt="Tu es l'accueil.", add_global_prompt=False)
    workflow = SimpleNamespace(global_node_id=None, nodes={"n1": node})
    composed = compose_system_prompt_for_node(
        node=node,
        workflow=workflow,
        format_prompt=lambda t: t,
        has_recordings=False,
        customer_memory="## Mémoire client\n- Nom : Awa",
    )
    assert composed.text.endswith("## Mémoire client\n- Nom : Awa")
    plain = compose_system_prompt_for_node(
        node=node,
        workflow=workflow,
        format_prompt=lambda t: t,
        has_recordings=False,
    )
    assert "Mémoire client" not in plain.text
