"""Administer the enterprise PBX: extensions, CSV import, queues, overflow, hours."""

import uuid

import pytest

from api.services.business.profile import BusinessProfile, save_business_profile
from api.services.pbx import admin
from api.services.pbx import client as client_module
from api.services.pbx import service as pbx
from api.tests.pbx_fake import TENANT, FakePbx, install

BASE = "https://pbx.ivoire-immo.ci"


@pytest.fixture(autouse=True)
def _clear_tokens():
    client_module._TOKENS.clear()
    yield


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
                "stasis_app_name": "nimbora_ab12cd34ef56",
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


async def test_create_extension_in_one_call(db_session, monkeypatch):
    fake = FakePbx()
    _, org, _ = await _setup(db_session, monkeypatch, fake)
    result = await admin.create_extension(
        org.id,
        admin.NewExtension(
            firstname="Aminata",
            lastname="Koné",
            extension="1010",
            email="aminata@ivoire-immo.ci",
            line="webrtc",
            agent=True,
        ),
    )
    body = fake.created_users[-1]
    line = body["lines"][0]
    assert line["context"] == "default"  # the PBX's internal context
    assert line["extensions"] == [{"exten": "1010", "context": "default"}]
    assert [t["uuid"] for t in line["endpoint_sip"]["templates"]] == [
        "tpl-webrtc",
        "tpl-global",
    ]
    creds = result["credentials"]
    assert ["password", creds["sip_password"]] in line["endpoint_sip"][
        "auth_section_options"
    ]
    assert len(creds["sip_password"]) == 20 and len(creds["login_password"]) == 14
    assert body["auth"] == {
        "username": "aminata@ivoire-immo.ci",
        "password": creds["login_password"],
        "enabled": True,
        "purpose": "user",
        "email_address": "aminata@ivoire-immo.ci",
    }
    assert (
        body["voicemail"]["number"] == "1010"
        and body["voicemail"]["password"] == creds["voicemail_pin"]
    )
    assert body["voicemail"]["attach_audio"] is True and body["language"] == "fr_FR"
    assert result["agent_id"] and any(a["number"] == "1010" for a in fake.agents)

    # A desk phone: no WebRTC template, no voicemail, login from the extension.
    desk = await admin.create_extension(
        org.id,
        admin.NewExtension(firstname="Accueil", extension="1011", voicemail=False),
    )
    assert [
        t["uuid"]
        for t in fake.created_users[-1]["lines"][0]["endpoint_sip"]["templates"]
    ] == ["tpl-global"]
    assert (
        "voicemail" not in fake.created_users[-1]
        and desk["credentials"]["login"] == "poste1011"
    )

    with pytest.raises(pbx.PbxRouteError) as taken:
        await admin.create_extension(
            org.id, admin.NewExtension(firstname="X", extension="1010")
        )
    assert taken.value.status == 409
    with pytest.raises(pbx.PbxRouteError) as invalid:
        await admin.create_extension(
            org.id, admin.NewExtension(firstname="", extension="12a", email="nope")
        )
    assert (
        invalid.value.status == 422
        and "Prénom" in str(invalid.value)
        and "E-mail" in str(invalid.value)
    )


async def test_failed_agent_leaves_nothing_half_made(db_session, monkeypatch):
    fake = FakePbx()
    _, org, _ = await _setup(db_session, monkeypatch, fake)
    fake.fail_agent_creation = True
    with pytest.raises(client_module.PbxError):
        await admin.create_extension(
            org.id, admin.NewExtension(firstname="Yao", extension="1020", agent=True)
        )
    assert not any(u.get("extension") == "1020" for u in fake.users)
    assert not any(e["exten"] == "1020" for e in fake.extensions)


async def test_csv_import_preview_and_partial_success(db_session, monkeypatch):
    fake = FakePbx()
    _, org, _ = await _setup(db_session, monkeypatch, fake)
    content = (
        "﻿Prénom;Nom;Poste;Email;Ligne;Messagerie;Agent\n"
        "Awa;Diallo;1030;awa@ivoire-immo.ci;navigateur;oui;oui\n"
        "Koffi;Yao;1001;;sip;non;non\n"
        "Moussa;Traoré;1030;;sip;oui;non\n"
        ";Sans prénom;1031;;sip;oui;non\n"
        "\n"
        "Ines;N'Guessan;1032;ines@ivoire-immo.ci;sip;;\n"
    )
    preview = await admin.preview_import(org.id, content)
    assert [r["line"] for r in preview] == [2, 3, 4, 5, 6]
    assert (
        preview[0]["type"] == "webrtc"
        and preview[0]["agent"] is True
        and preview[0]["errors"] == []
    )
    assert preview[1]["errors"] == ["Le poste 1001 existe déjà"]
    assert preview[2]["errors"] == ["Poste en double (ligne 2)"]
    assert preview[3]["errors"] == ["Prénom manquant"]
    assert preview[4]["voicemail"] is True and preview[4]["errors"] == []

    result = await admin.run_import(org.id, content)
    assert [c["extension"] for c in result["created"]] == ["1030", "1032"]
    assert len(result["failed"]) == 3
    sheet = admin.credentials_csv(result["created"])
    assert sheet.splitlines()[0].startswith("nom;poste;identifiant")
    assert "awa@ivoire-immo.ci" in sheet and "1032" in sheet
    # Comma-separated files work too.
    rows = admin.parse_csv("prenom,nom,poste\nZié,Coulibaly,1040\n")
    assert rows[0].firstname == "Zié" and rows[0].line == "sip"


async def test_queue_with_members_and_overflow_to_an_ai_agent(db_session, monkeypatch):
    fake = FakePbx()
    _, org, workflow = await _setup(db_session, monkeypatch, fake)
    queue = await admin.create_queue(
        org.id,
        admin.NewQueue(
            label="Service client",
            extension="3005",
            strategy="rrmemory",
            agent_ids=[7],
            overflow_workflow_id=workflow.id,
            overflow_after_seconds=90,
        ),
    )
    created = next(q for q in fake.queues if q["id"] == queue["id"])
    assert created["label"] == "Service client" and created["name"].startswith(
        "serviceclient"
    )
    assert ["strategy", "rrmemory"] in created["options"]
    assert created["extensions"][0]["exten"] == "3005"
    assert created["members"]["agents"] == [{"id": 7, "penalty": 0}]
    command = f"Stasis(nimbora_ab12cd34ef56,inbound,called=nimbora-q{queue['id']})"
    assert created["wait_time_threshold"] == 90
    assert created["wait_time_destination"] == {"type": "custom", "command": command}
    assert fake.fallbacks[queue["id"]]["noanswer_destination"]["command"] == command
    # NIMBORA routes that key to the agent through the ARI inbound path.
    row = await db_session.find_active_phone_number_for_inbound(
        org.id, f"nimbora-q{queue['id']}", "ari"
    )
    assert row.inbound_workflow_id == workflow.id

    inventory = await pbx.inventory(org.id)
    shown = next(q for q in inventory["queues"] if q["id"] == queue["id"])
    assert shown["overflow"] == {
        "workflow_id": workflow.id,
        "workflow_name": "Accueil IA",
    }
    assert shown["agent_ids"] == [7]

    await admin.set_queue_member(org.id, queue["id"], 7, False)
    assert created["members"]["agents"] == []
    await admin.set_queue_overflow(org.id, queue["id"], None)
    assert (
        created["wait_time_destination"] is None and fake.fallbacks[queue["id"]] == {}
    )
    assert (
        await db_session.find_active_phone_number_for_inbound(
            org.id, f"nimbora-q{queue['id']}", "ari"
        )
        is None
    )

    with pytest.raises(pbx.PbxRouteError):
        await admin.create_queue(
            org.id, admin.NewQueue(label="Doublon", extension="3005")
        )
    with pytest.raises(pbx.PbxRouteError):
        await admin.create_queue(
            org.id, admin.NewQueue(label="X", extension="3006", strategy="loto")
        )
    await admin.delete_queue(org.id, queue["id"])
    assert not any(q["id"] == queue["id"] for q in fake.queues)


async def test_overflow_needs_ai_access(db_session, monkeypatch):
    fake = FakePbx()
    _, org, workflow = await _setup(db_session, monkeypatch, fake, ari=False)
    with pytest.raises(pbx.PbxRouteError) as error:
        await admin.set_queue_overflow(org.id, 1, workflow.id)
    assert error.value.status == 409


async def test_opening_hours_follow_the_business_card(db_session, monkeypatch):
    fake = FakePbx()
    _, org, workflow = await _setup(db_session, monkeypatch, fake)
    with pytest.raises(pbx.PbxRouteError):
        await admin.sync_opening_hours(
            org.id, [5], "ai_agent", workflow.id
        )  # no hours yet
    await save_business_profile(
        org.id,
        BusinessProfile.model_validate(
            {
                "name": "Ivoire Immo",
                "timezone": "Africa/Abidjan",
                "opening_hours": {
                    "mon": [
                        {"open": "08:00", "close": "12:30"},
                        {"open": "14:00", "close": "18:00"},
                    ],
                    "sat": [{"open": "09:00", "close": "13:00"}],
                },
                "closures": [{"date": "2026-12-25", "label": "Noël"}],
            }
        ),
    )
    # The number already has another schedule: it is replaced, not stacked.
    fake.schedules.append({"id": 77, "name": "ancien"})
    fake.incalls[0]["schedules"] = [{"id": 77, "name": "ancien"}]

    result = await admin.sync_opening_hours(org.id, [5], "ai_agent", workflow.id)
    schedule = next(s for s in fake.schedules if s["id"] == result["schedule_id"])
    assert (
        schedule["name"] == f"nimbora-horaires-{org.id}"
        and schedule["timezone"] == "Africa/Abidjan"
    )
    assert schedule["open_periods"] == [
        {"hours_start": "08:00", "hours_end": "12:30", "week_days": [1]},
        {"hours_start": "14:00", "hours_end": "18:00", "week_days": [1]},
        {"hours_start": "09:00", "hours_end": "13:00", "week_days": [6]},
    ]
    closed = schedule["closed_destination"]
    assert closed == {
        "type": "custom",
        "command": f"Stasis(nimbora_ab12cd34ef56,inbound,called=nimbora-h{org.id})",
    }
    assert (
        schedule["exceptional_periods"][0]["month_days"] == [25]
        and schedule["exceptional_periods"][0]["destination"] == closed
    )
    assert fake.incalls[0]["schedules"] == [
        {"id": result["schedule_id"], "name": schedule["name"]}
    ]
    assert (
        await db_session.find_active_phone_number_for_inbound(
            org.id, f"nimbora-h{org.id}", "ari"
        )
    ).inbound_workflow_id == workflow.id

    # Hours changed in the card → one re-sync updates the same schedule.
    again = await admin.sync_opening_hours(org.id, [5], "voicemail", voicemail_id=1)
    assert (
        again["schedule_id"] == result["schedule_id"]
        and len([s for s in fake.schedules if s["name"].startswith("nimbora")]) == 1
    )
    assert schedule["closed_destination"] == {"type": "voicemail", "voicemail_id": 1}
    assert (
        await db_session.find_active_phone_number_for_inbound(
            org.id, f"nimbora-h{org.id}", "ari"
        )
        is None
    )


async def test_admin_routes(db_session, monkeypatch, test_client_factory):
    fake = FakePbx()
    user, org, workflow = await _setup(db_session, monkeypatch, fake)
    async with test_client_factory(user) as client:
        created = await client.post(
            "/api/v1/pbx/extensions",
            json={
                "firstname": "Awa",
                "lastname": "Diallo",
                "extension": "1050",
                "line": "webrtc",
            },
        )
        assert created.status_code == 200
        data = created.json()
        assert data["credentials"]["sip_password"] and data["line"] == "webrtc"
        assert (
            await client.post(
                "/api/v1/pbx/extensions", json={"firstname": "Awa", "extension": "1050"}
            )
        ).status_code == 409
        assert (
            await client.post(
                "/api/v1/pbx/extensions",
                json={"firstname": "Awa", "extension": "1050", "line": "fax"},
            )
        ).status_code == 422
        assert (
            await client.post(
                "/api/v1/pbx/extensions/password-reset",
                json={"login": "awa@ivoire-immo.ci"},
            )
        ).status_code == 204
        assert fake.reset_emails == ["awa@ivoire-immo.ci"]
        assert (
            await client.delete(f"/api/v1/pbx/extensions/{data['uuid']}")
        ).status_code == 204
        assert (
            await client.delete(f"/api/v1/pbx/extensions/{data['uuid']}")
        ).status_code == 404

        preview = (
            await client.post(
                "/api/v1/pbx/extensions/import/preview",
                json={
                    "content": "prenom;nom;poste\nKoffi;Yao;1001\nZié;Coulibaly;1060\n"
                },
            )
        ).json()
        assert [bool(r["errors"]) for r in preview] == [True, False]
        imported = (
            await client.post(
                "/api/v1/pbx/extensions/import",
                json={"content": "prenom;nom;poste\nZié;Coulibaly;1060\n"},
            )
        ).json()
        assert (
            imported["created"][0]["extension"] == "1060"
            and "1060" in imported["credentials_csv"]
        )

        assert "rrmemory" in (await client.get("/api/v1/pbx/strategies")).json()
        queue = (
            await client.post(
                "/api/v1/pbx/queues",
                json={"label": "Recouvrement", "extension": "3010"},
            )
        ).json()
        assert (
            await client.put(f"/api/v1/pbx/queues/{queue['id']}/members/7")
        ).status_code == 204
        assert (
            await client.put(f"/api/v1/pbx/queues/{queue['id']}/members/999")
        ).status_code == 404
        overflow = await client.put(
            f"/api/v1/pbx/queues/{queue['id']}/overflow",
            json={"workflow_id": workflow.id, "after_seconds": 45},
        )
        assert overflow.json()["overflow"] == {
            "workflow_id": workflow.id,
            "after_seconds": 45,
        }
        assert (await client.get("/api/v1/pbx/voicemails")).json()[0][
            "name"
        ] == "Accueil"
        no_hours = await client.put(
            "/api/v1/pbx/schedule", json={"incall_ids": [5], "closed": "hangup"}
        )
        assert no_hours.status_code == 409
        assert (
            await client.delete(f"/api/v1/pbx/queues/{queue['id']}")
        ).status_code == 204
