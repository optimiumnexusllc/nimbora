"""Voice menus with spoken prompts, public numbers, operator lines and
outbound routes on the enterprise PBX."""

import io
import uuid
import wave

import numpy as np
import pytest

from api.services.pbx import client as client_module
from api.services.pbx import ivr, numbers, prompts, trunks
from api.services.pbx import service as pbx
from api.tests.pbx_fake import TENANT, FakePbx, install

BASE = "https://pbx.ivoire-immo.ci"
STASIS = "nimbora_ab12cd34ef56"


def _wav(rate=24000, seconds=0.5, channels=1) -> bytes:
    t = np.linspace(0, seconds, int(rate * seconds), endpoint=False)
    tone = (np.sin(2 * np.pi * 440 * t) * 8000).astype("<i2")
    if channels == 2:
        tone = np.repeat(tone, 2)
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(tone.tobytes())
    return out.getvalue()


@pytest.fixture(autouse=True)
def _clear_tokens():
    client_module._TOKENS.clear()
    yield


@pytest.fixture
def spoken(monkeypatch):
    """Record what would be spoken, return a real PBX-format WAV."""
    said: list[tuple[str, int | None]] = []

    async def fake(organization_id, text, *, voice_workflow_id=None):
        said.append((text, voice_workflow_id))
        return prompts.to_pbx_wav(_wav())

    monkeypatch.setattr(prompts, "synthesize_prompt", fake)
    return said


async def _setup(db, monkeypatch, fake, *, ari=True):
    user = await db.create_user_with_email(
        email=f"{uuid.uuid4().hex[:10]}@example.com", password_hash="x"
    )
    org, _ = await db.get_or_create_organization_by_provider_id(
        org_provider_id=f"org_{uuid.uuid4().hex}", user_id=user.id
    )
    await db.add_user_to_organization(user.id, org.id)
    await db.update_user_selected_organization(user.id, org.id)
    user.selected_organization_id = org.id
    config = None
    if ari:
        config = await db.create_telephony_configuration(
            organization_id=org.id,
            name="PBX (ARI)",
            provider="ari",
            credentials={
                "ari_endpoint": "http://pbx:5039",
                "app_name": "xivo",
                "app_password": "x",
                "stasis_app_name": STASIS,
            },
        )
    workflow = await db.create_workflow(
        "Accueil IA", {"nodes": [], "edges": []}, user.id, org.id
    )
    install(monkeypatch, fake)
    await db.save_pbx_connection(
        org.id,
        {
            "base_url": BASE,
            "username": "nimbora",
            "password": "secret",
            "tenant_uuid": TENANT,
            "ari_configuration_id": config.id if config else None,
            "webhook_token": pbx.new_webhook_token(),
        },
    )
    return user, org, workflow


def _spec(workflow_id, **extra) -> ivr.MenuSpec:
    return ivr.MenuSpec.model_validate(
        {
            "greeting_text": "Bienvenue chez Ivoire Immo.",
            "choices": [
                {
                    "digit": "1",
                    "label": "Le service commercial",
                    "type": "queue",
                    "target_id": 1,
                },
                {
                    "digit": "2",
                    "label": "Notre assistante",
                    "type": "ai",
                    "target_id": workflow_id,
                },
                {
                    "digit": "#",
                    "label": "La messagerie",
                    "type": "voicemail",
                    "target_id": 1,
                },
            ],
            "fallback": {"type": "ai", "target_id": workflow_id},
            **extra,
        }
    )


# ------------------------------------------------------------- prompts


def test_prompts_are_converted_to_the_pbx_format():
    for source in (_wav(24000), _wav(16000, channels=2), _wav(8000)):
        out = prompts.to_pbx_wav(source)
        with wave.open(io.BytesIO(out), "rb") as w:
            assert (w.getframerate(), w.getnchannels(), w.getsampwidth()) == (
                8000,
                1,
                2,
            )
        assert abs(prompts.wav_duration(out) - 0.5) < 0.01


async def test_prompt_synthesis_uses_the_organization_voice(monkeypatch):
    from api.services.pipecat import service_factory, speech_synthesis

    seen = {}

    async def voice(organization_id, voice_workflow_id):
        seen["voice"] = (organization_id, voice_workflow_id)
        return "config"

    def make_tts(user_config, audio_config, **kwargs):
        seen["tts"] = (user_config, audio_config.pipeline_sample_rate, kwargs)
        return "tts"

    async def speak(tts, text, *, sample_rate, max_duration):
        seen["speak"] = (tts, text, sample_rate)
        return _wav(sample_rate)

    monkeypatch.setattr(prompts, "_effective_voice", voice)
    monkeypatch.setattr(service_factory, "create_tts_service", make_tts)
    monkeypatch.setattr(speech_synthesis, "synthesize_speech", speak)
    audio = await prompts.synthesize_prompt(3, "  Bonjour.  ", voice_workflow_id=9)
    assert seen["voice"] == (3, 9)
    assert seen["tts"] == ("config", 8000, {"organization_id": 3})
    assert seen["speak"] == ("tts", "Bonjour.", 8000)
    assert audio[:4] == b"RIFF"
    with pytest.raises(pbx.PbxRouteError):
        await prompts.synthesize_prompt(3, "   ")
    with pytest.raises(pbx.PbxRouteError):
        await prompts.synthesize_prompt(3, "x" * 801)

    async def broken(*args, **kwargs):
        raise RuntimeError("quota")

    monkeypatch.setattr(speech_synthesis, "synthesize_speech", broken)
    with pytest.raises(pbx.PbxRouteError) as error:
        await prompts.synthesize_prompt(3, "Bonjour.")
    assert error.value.status == 502


# ---------------------------------------------------------------- menus


def test_menu_spec_validation_and_spoken_text():
    spec = _spec(4)
    assert spec.spoken_menu() == (
        "Pour le service commercial, tapez 1. Pour notre assistante, tapez 2. "
        "Pour la messagerie, tapez dièse."
    )
    assert ivr.menu_key(3, "*") == "nimbora-m3-star"
    with pytest.raises(ValueError, match="deux fois"):
        ivr.MenuSpec.model_validate(
            {"choices": [{"digit": "1", "label": "A"}, {"digit": "1", "label": "B"}]}
        )
    with pytest.raises(ValueError):
        ivr.MenuSpec.model_validate({"choices": [{"digit": "12", "label": "A"}]})
    with pytest.raises(ValueError, match="destination"):
        ivr.MenuSpec.model_validate(
            {"choices": [{"digit": "1", "label": "A", "type": "queue"}]}
        )
    assert _spec(4).fingerprint() == _spec(4).fingerprint() != _spec(5).fingerprint()


async def test_publish_menu_speaks_uploads_and_routes_to_ai(
    db_session, monkeypatch, spoken
):
    fake = FakePbx()
    _, org, workflow = await _setup(db_session, monkeypatch, fake)
    row = await ivr.create_menu(org.id, "Accueil", _spec(workflow.id))
    published = await ivr.publish_menu(org.id, row.id)

    assert [t for t, _ in spoken] == [
        (
            "Pour le service commercial, tapez 1. Pour notre assistante, tapez 2. "
            "Pour la messagerie, tapez dièse."
        ),
        "Bienvenue chez Ivoire Immo.",
        "Ce choix n'est pas valide.",
    ]
    files = fake.sound_categories[ivr.SOUND_CATEGORY]
    assert set(files) == {
        f"menu-{row.id}-menu",
        f"menu-{row.id}-greeting",
        f"menu-{row.id}-invalid",
    }
    assert all(f[:4] == b"RIFF" for f in files.values())
    # PBX menu: prompts played from the uploaded sounds (no extension).
    menu = fake.ivrs[0]
    assert menu["menu_sound"].endswith(f"/menus-vocaux/menu-{row.id}-menu")
    assert menu["timeout"] == 5 and menu["max_tries"] == 3
    choices = {c["exten"]: c["destination"] for c in menu["choices"]}
    assert choices["1"] == {"type": "queue", "queue_id": 1}
    assert choices["#"] == {"type": "voicemail", "voicemail_id": 1}
    key = f"nimbora-m{row.id}-2"
    assert choices["2"] == {
        "type": "custom",
        "command": f"Stasis({STASIS},inbound,called={key})",
    }
    assert menu["timeout_destination"]["command"].endswith(
        f"called=nimbora-m{row.id}-fallback)"
    )
    hit = await db_session.find_active_phone_number_for_inbound(org.id, key, "ari")
    assert hit.inbound_workflow_id == workflow.id
    assert published["up_to_date"] and published["pbx_ivr_id"] == menu["id"]

    # Edit: no greeting, AI choice replaced by a hang-up → stale prompt and
    # stale AI hand-off are cleaned up; the same PBX menu is replaced.
    spec = _spec(workflow.id, greeting_text="").model_dump()
    spec["choices"][1] = {"digit": "2", "label": "Raccrocher", "type": "hangup"}
    row = await ivr.update_menu(
        org.id, row.id, "Accueil", ivr.MenuSpec.model_validate(spec)
    )
    assert not ivr.serialize(row)["up_to_date"]
    await ivr.publish_menu(org.id, row.id)
    assert len(fake.ivrs) == 1 and fake.ivrs[0]["greeting_sound"] is None
    assert f"menu-{row.id}-greeting" not in files
    assert (
        await db_session.find_active_phone_number_for_inbound(org.id, key, "ari")
        is None
    )
    fallback_key = f"nimbora-m{row.id}-fallback"
    assert await db_session.find_active_phone_number_for_inbound(
        org.id, fallback_key, "ari"
    )

    # Deleted on the PBX side by someone else: publishing recreates it.
    fake.ivrs.clear()
    await ivr.publish_menu(org.id, row.id)
    assert len(fake.ivrs) == 1


async def test_sub_menus_and_safe_deletion(db_session, monkeypatch, spoken):
    fake = FakePbx()
    _, org, workflow = await _setup(db_session, monkeypatch, fake)
    child = await ivr.create_menu(
        org.id,
        "Location",
        ivr.MenuSpec.model_validate(
            {
                "choices": [
                    {
                        "digit": "1",
                        "label": "Un agent",
                        "type": "ai",
                        "target_id": workflow.id,
                    }
                ]
            }
        ),
    )
    parent = await ivr.create_menu(
        org.id,
        "Accueil",
        ivr.MenuSpec.model_validate(
            {
                "choices": [
                    {
                        "digit": "3",
                        "label": "La location",
                        "type": "menu",
                        "target_id": child.id,
                    }
                ]
            }
        ),
    )
    with pytest.raises(pbx.PbxRouteError, match="Publiez d'abord"):
        await ivr.publish_menu(org.id, parent.id)
    child_pub = await ivr.publish_menu(org.id, child.id)
    await ivr.publish_menu(org.id, parent.id)
    parent_ivr = next(i for i in fake.ivrs if i["name"] == "Accueil")
    assert parent_ivr["choices"][0]["destination"] == {
        "type": "ivr",
        "ivr_id": child_pub["pbx_ivr_id"],
    }
    with pytest.raises(pbx.PbxRouteError, match="lui-même"):
        await ivr.update_menu(
            org.id,
            child.id,
            "Location",
            ivr.MenuSpec.model_validate(
                {
                    "choices": [
                        {
                            "digit": "1",
                            "label": "Boucle",
                            "type": "menu",
                            "target_id": child.id,
                        }
                    ]
                }
            ),
        )
    with pytest.raises(pbx.PbxRouteError, match="renvoie vers celui-ci"):
        await ivr.delete_menu(org.id, child.id)

    # A number rings the parent menu: it cannot disappear under it.
    await numbers.set_number_destination(
        org.id, "+22527000099", ivr.MenuAction(type="menu", target_id=parent.id)
    )
    with pytest.raises(pbx.PbxRouteError, match="Des numéros"):
        await ivr.delete_menu(org.id, parent.id)
    await numbers.remove_number(org.id, "+22527000099")
    await ivr.delete_menu(org.id, parent.id)
    await ivr.delete_menu(org.id, child.id)
    assert fake.ivrs == [] and fake.sound_categories[ivr.SOUND_CATEGORY] == {}
    assert (
        await db_session.find_active_phone_number_for_inbound(
            org.id, f"nimbora-m{child.id}-1", "ari"
        )
        is None
    )


async def test_menus_are_scoped_to_the_organization(db_session, monkeypatch, spoken):
    fake = FakePbx()
    _, org, workflow = await _setup(db_session, monkeypatch, fake)
    _, other, other_workflow = await _setup(db_session, monkeypatch, FakePbx())
    row = await ivr.create_menu(org.id, "Accueil", _spec(workflow.id))
    with pytest.raises(pbx.PbxRouteError):
        await ivr.publish_menu(other.id, row.id)
    with pytest.raises(pbx.PbxRouteError, match="Agent IA introuvable"):
        await ivr.create_menu(org.id, "Vol", _spec(other_workflow.id))
    with pytest.raises(pbx.PbxRouteError, match="Sous-menu"):
        await ivr.create_menu(
            other.id,
            "Vol",
            ivr.MenuSpec.model_validate(
                {
                    "choices": [
                        {
                            "digit": "1",
                            "label": "x",
                            "type": "menu",
                            "target_id": row.id,
                        }
                    ]
                }
            ),
        )


# -------------------------------------------------------------- numbers


async def test_number_destinations_and_ai_adoption(db_session, monkeypatch, spoken):
    fake = FakePbx()
    _, org, workflow = await _setup(db_session, monkeypatch, fake)
    # New number → queue.
    result = await numbers.set_number_destination(
        org.id, "+22527000077", ivr.MenuAction(type="queue", target_id=1)
    )
    incall = next(i for i in fake.incalls if i["id"] == result["incall_id"])
    assert incall["destination"] == {"type": "queue", "queue_id": 1}
    assert incall["extensions"][0]["context"] == "from-extern"

    # The existing standard number (with its schedule) is adopted by an AI
    # agent: the incall is kept, then given back its previous destination.
    fake.incalls[0]["schedules"] = [{"id": 1, "name": "horaires"}]
    adopted = await numbers.set_number_destination(
        org.id, "+22527000000", ivr.MenuAction(type="ai", target_id=workflow.id)
    )
    assert adopted["incall_id"] == 5
    assert fake.incalls[0]["destination"] == {
        "type": "custom",
        "command": f"Stasis({STASIS},inbound,called=+22527000000)",
    }
    assert fake.incalls[0]["description"] == "Standard"
    row = await db_session.find_active_phone_number_for_inbound(
        org.id, "+22527000000", "ari"
    )
    assert row.inbound_workflow_id == workflow.id
    inventory = await pbx.inventory(org.id)
    # The engine holds the DID without its "+"; the inventory shows it as held.
    shown = next(n for n in inventory["numbers"] if n["number"] == "22527000000")
    assert shown["destination_type"] == "ai" and shown["ai_workflow_id"] == workflow.id

    assert await pbx.unroute_number(org.id, "+22527000000")
    assert any(i["id"] == 5 for i in fake.incalls)  # never deleted
    assert fake.incalls[0]["destination"] == {"type": "queue", "queue_id": 1}
    assert any(e["exten"] == "22527000000" for e in fake.extensions)

    # AI → menu releases NIMBORA's route.
    await numbers.set_number_destination(
        org.id, "+22527000000", ivr.MenuAction(type="ai", target_id=workflow.id)
    )
    menu = await ivr.create_menu(org.id, "Accueil", _spec(workflow.id))
    with pytest.raises(pbx.PbxRouteError, match="Publiez"):
        await numbers.set_number_destination(
            org.id, "+22527000000", ivr.MenuAction(type="menu", target_id=menu.id)
        )
    published = await ivr.publish_menu(org.id, menu.id)
    await numbers.set_number_destination(
        org.id, "+22527000000", ivr.MenuAction(type="menu", target_id=menu.id)
    )
    assert fake.incalls[0]["destination"] == {
        "type": "ivr",
        "ivr_id": published["pbx_ivr_id"],
    }
    assert (
        await db_session.find_active_phone_number_for_inbound(
            org.id, "+22527000000", "ari"
        )
        is None
    )
    shown = next(
        n
        for n in (await pbx.inventory(org.id))["numbers"]
        if n["number"] == "22527000000"  # as the engine holds it, without "+"
    )
    assert shown["destination_type"] == "ivr"
    assert shown["destination_target_id"] == published["pbx_ivr_id"]

    with pytest.raises(pbx.PbxRouteError):
        await numbers.set_number_destination(org.id, "abc", ivr.MenuAction())
    assert await numbers.remove_number(org.id, "+22527000077")
    assert not await numbers.remove_number(org.id, "+22527000077")
    assert not any(
        e["exten"] in ("+22527000077", "22527000077") for e in fake.extensions
    )


# ------------------------------------------------------- operator lines


async def test_trunk_with_registration(db_session, monkeypatch):
    fake = FakePbx()
    _, org, _ = await _setup(db_session, monkeypatch, fake)
    created = await trunks.create_trunk(
        org.id,
        trunks.NewTrunk(
            label="Orange CI",
            host="SIP.Orange.ci",
            username="2252700",
            password="s3cret-op",
        ),
    )
    endpoint = next(iter(fake.endpoints_sip.values()))
    assert endpoint["label"] == "Orange CI"
    assert endpoint["templates"] == [{"uuid": "tpl-global"}, {"uuid": "tpl-trunk"}]
    assert endpoint["transport"] == {"uuid": "tr-udp"}
    assert ["password", "s3cret-op"] in endpoint["auth_section_options"]
    assert ["client_uri", "sip:2252700@sip.orange.ci"] in endpoint[
        "registration_section_options"
    ]
    assert ["server_uri", "sip:sip.orange.ci"] in endpoint[
        "registration_section_options"
    ]
    assert ["match", "sip.orange.ci"] in endpoint["identify_section_options"]
    trunk = fake.trunks[0]
    assert (
        trunk["context"] == "from-extern"
        and trunk["endpoint_sip"]["uuid"] == endpoint["uuid"]
    )

    fake.trunk_status[created["id"]] = {"registered": True, "current_call_count": 2}
    listed = await trunks.list_trunks(org.id)
    assert listed["trunks"][0] == {
        "id": created["id"],
        "label": "Orange CI",
        "technology": "sip",
        "host": "sip.orange.ci",
        "username": "2252700",
        "registration": True,
        "registered": True,
        "current_calls": 2,
        "outcalls": [],
        "caller_id_format": "+E164",
    }
    assert "s3cret" not in str(listed)  # the password never comes back

    fake.down.add("calld")
    degraded = await trunks.list_trunks(org.id)
    assert degraded["status_error"] and degraded["trunks"][0]["registered"] is None


async def test_ip_trunk_and_rollback(db_session, monkeypatch):
    fake = FakePbx()
    _, org, _ = await _setup(db_session, monkeypatch, fake)
    await trunks.create_trunk(
        org.id,
        trunks.NewTrunk(
            label="SBC opérateur",
            host="10.20.0.5",
            port=5080,
            transport="tls",
            register=False,
        ),
    )
    endpoint = next(iter(fake.endpoints_sip.values()))
    assert "registration_section_options" not in endpoint
    assert endpoint["templates"] == [{"uuid": "tpl-global"}]
    assert ["contact", "sips:10.20.0.5:5080"] in endpoint["aor_section_options"]
    assert endpoint["transport"] == {"uuid": "tr-tls"}

    fake.fail_trunk_association = True
    with pytest.raises(client_module.PbxError):
        await trunks.create_trunk(
            org.id, trunks.NewTrunk(label="X", host="sip.x.ci", register=False)
        )
    assert len(fake.trunks) == 1 and len(fake.endpoints_sip) == 1

    for bad in (
        trunks.NewTrunk(label="", host="sip.x.ci"),
        trunks.NewTrunk(label="X", host="sip x;rm", register=False),
        trunks.NewTrunk(label="X", host="sip.x.ci"),  # registration needs credentials
        trunks.NewTrunk(label="X", host="sip.x.ci", username="a b", password="p"),
    ):
        with pytest.raises(pbx.PbxRouteError):
            await trunks.create_trunk(org.id, bad)


async def test_outbound_route_with_failover_and_caller_id(db_session, monkeypatch):
    fake = FakePbx()
    _, org, _ = await _setup(db_session, monkeypatch, fake)
    first = await trunks.create_trunk(
        org.id, trunks.NewTrunk(label="Orange", host="sip.orange.ci", register=False)
    )
    second = await trunks.create_trunk(
        org.id, trunks.NewTrunk(label="MTN", host="sip.mtn.ci", register=False)
    )
    route = await trunks.create_outbound_route(
        org.id,
        trunks.NewOutboundRoute(
            name="Sortie nationale",
            trunk_ids=[first["id"], second["id"]],
            rules=[
                trunks.DialRule(pattern="_0XXXXXXXXX", caller_id="+225 27 00 00 00 00"),
                trunks.DialRule(pattern="_00.", strip_digits=2, external_prefix="+"),
            ],
        ),
    )
    outcall = fake.outcalls[0]
    assert [t["id"] for t in outcall["trunks"]] == [first["id"], second["id"]]
    assert outcall["extensions"][0]["caller_id"] == "+2252700000000"
    assert outcall["extensions"][1]["strip_digits"] == 2
    assert all(e["context"] == "to-extern" for e in outcall["extensions"])

    listed = await trunks.list_outbound_routes(org.id)
    assert listed[0]["name"] == "Sortie nationale"
    assert [t["label"] for t in listed[0]["trunks"]] == ["Orange", "MTN"]
    assert listed[0]["rules"][1]["pattern"] == "_00."

    with pytest.raises(pbx.PbxRouteError, match="déjà utilisé"):
        await trunks.create_outbound_route(
            org.id,
            trunks.NewOutboundRoute(
                name="Doublon", trunk_ids=[first["id"]], rules=[trunks.DialRule("_00.")]
            ),
        )
    with pytest.raises(pbx.PbxRouteError, match="sortantes"):
        await trunks.delete_trunk(org.id, first["id"])
    await trunks.delete_outbound_route(org.id, route["id"])
    assert fake.outcalls == [] and not any(
        e["context"] == "to-extern" for e in fake.extensions
    )
    await trunks.delete_trunk(org.id, first["id"])
    assert len(fake.trunks) == 1 and len(fake.endpoints_sip) == 1

    for bad in (
        trunks.NewOutboundRoute(name="X", trunk_ids=[], rules=[trunks.DialRule("_0.")]),
        trunks.NewOutboundRoute(
            name="X", trunk_ids=[second["id"]], rules=[trunks.DialRule("0;rm")]
        ),
        trunks.NewOutboundRoute(
            name="X", trunk_ids=[999], rules=[trunks.DialRule("_0.")]
        ),
        trunks.NewOutboundRoute(
            name="X",
            trunk_ids=[second["id"]],
            rules=[trunks.DialRule("_0.", caller_id="abc")],
        ),
    ):
        with pytest.raises(pbx.PbxRouteError):
            await trunks.create_outbound_route(org.id, bad)


def test_dial_pattern_semantics():
    assert trunks.pattern_matches("_0XXXXXXXXX", "0707112233")
    assert not trunks.pattern_matches("_0XXXXXXXXX", "070711223")
    assert trunks.pattern_matches("_00.", "0033612345678")
    assert not trunks.pattern_matches("_00.", "00")
    assert trunks.pattern_matches("_N[1-3]XX", "5299")
    assert not trunks.pattern_matches("_N[1-3]XX", "5499")
    assert trunks.pattern_matches("3000", "3000")
    rule = trunks.DialRule("_00.", strip_digits=2, external_prefix="+")
    assert trunks.dialled_number(rule, "0033612345678") == "+33612345678"
    rule = trunks.DialRule("_9.", prefix="9", strip_digits=0)
    assert trunks.dialled_number(rule, "90707112233") == "0707112233"


# --------------------------------------------------------------- routes


async def test_routes(db_session, monkeypatch, test_client_factory, spoken):
    fake = FakePbx()
    user, _org, workflow = await _setup(db_session, monkeypatch, fake)
    async with test_client_factory(user) as client:
        spec = _spec(workflow.id).model_dump()
        created = await client.post(
            "/api/v1/pbx/menus", json={"name": "Accueil", "spec": spec}
        )
        assert created.status_code == 201
        menu = created.json()
        assert menu["up_to_date"] is False
        bad = await client.post(
            "/api/v1/pbx/menus",
            json={"name": "X", "spec": {**spec, "choices": []}},
        )
        assert bad.status_code == 422
        text = await client.post("/api/v1/pbx/menus/spoken-text", json=spec)
        assert text.json()["menu"].startswith("Pour le service commercial, tapez 1.")
        published = await client.post(f"/api/v1/pbx/menus/{menu['id']}/publish")
        assert published.status_code == 200 and published.json()["up_to_date"]
        listed = (await client.get("/api/v1/pbx/menus")).json()
        assert [m["name"] for m in listed] == ["Accueil"]
        renamed = await client.put(
            f"/api/v1/pbx/menus/{menu['id']}", json={"name": "Standard", "spec": spec}
        )
        assert renamed.json()["name"] == "Standard"

        audio = await client.post(
            "/api/v1/pbx/prompts/preview", json={"text": "Bonjour."}
        )
        assert (
            audio.headers["content-type"] == "audio/wav"
            and audio.content[:4] == b"RIFF"
        )

        number = await client.put(
            "/api/v1/pbx/numbers",
            json={
                "number": "+22527000088",
                "destination": {"type": "menu", "target_id": menu["id"]},
            },
        )
        assert number.status_code == 200
        assert (
            await client.delete(f"/api/v1/pbx/menus/{menu['id']}")
        ).status_code == 409
        assert (
            await client.delete("/api/v1/pbx/numbers/+22527000088")
        ).status_code == 204
        assert (
            await client.delete("/api/v1/pbx/numbers/+22527000088")
        ).status_code == 404
        assert (
            await client.delete(f"/api/v1/pbx/menus/{menu['id']}")
        ).status_code == 204

        trunk = await client.post(
            "/api/v1/pbx/trunks",
            json={
                "label": "Orange",
                "host": "sip.orange.ci",
                "username": "u1",
                "password": "p1",
            },
        )
        assert trunk.status_code == 201
        assert (await client.get("/api/v1/pbx/trunks")).json()["trunks"][0][
            "host"
        ] == "sip.orange.ci"
        assert (
            await client.post(
                "/api/v1/pbx/trunks",
                json={"label": "X", "host": "sip.x.ci", "registration": True},
            )
        ).status_code == 422
        route = await client.post(
            "/api/v1/pbx/outbound-routes",
            json={
                "name": "Sortie",
                "trunk_ids": [trunk.json()["id"]],
                "rules": [{"pattern": "_0XXXXXXXXX"}],
            },
        )
        assert route.status_code == 201
        routes = (await client.get("/api/v1/pbx/outbound-routes")).json()
        assert routes["routes"][0]["name"] == "Sortie" and routes["presets"]
        test = await client.post(
            "/api/v1/pbx/outbound-routes/test",
            json={
                "dialled": "0033612345678",
                "rules": [
                    {"pattern": "_0XXXXXXXXX"},
                    {"pattern": "_00.", "strip_digits": 2, "external_prefix": "+"},
                ],
            },
        )
        assert test.json() == {
            "matched": True,
            "rule_index": 1,
            "sent": "+33612345678",
            "caller_id": None,
        }
        assert (
            await client.delete(f"/api/v1/pbx/outbound-routes/{route.json()['id']}")
        ).status_code == 204
        assert (
            await client.delete(f"/api/v1/pbx/trunks/{trunk.json()['id']}")
        ).status_code == 204
