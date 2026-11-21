"""Call groups, per-extension forwards and no-answer handling, conference
rooms with live participant control."""

import uuid

import pytest

from api.services.pbx import client as client_module
from api.services.pbx import conferences, forwards, groups, ivr, numbers
from api.services.pbx import service as pbx
from api.tests.pbx_fake import TENANT, FakePbx, install

BASE = "https://pbx.ivoire-immo.ci"
STASIS = "nimbora_ab12cd34ef56"


@pytest.fixture(autouse=True)
def _clear_tokens():
    client_module._TOKENS.clear()
    yield


async def _setup(db, monkeypatch, fake):
    user = await db.create_user_with_email(
        email=f"{uuid.uuid4().hex[:10]}@example.com", password_hash="x"
    )
    org, _ = await db.get_or_create_organization_by_provider_id(
        org_provider_id=f"org_{uuid.uuid4().hex}", user_id=user.id
    )
    await db.add_user_to_organization(user.id, org.id)
    await db.update_user_selected_organization(user.id, org.id)
    user.selected_organization_id = org.id
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
            "ari_configuration_id": config.id,
            "webhook_token": pbx.new_webhook_token(),
        },
    )
    return user, org, workflow


# --------------------------------------------------------------- groups


def test_group_labels_become_ascii():
    assert (
        groups.ascii_label("Équipe d'accueil — Abidjan") == "Equipe d accueil Abidjan"
    )
    assert groups.ascii_label("  ") == ""


async def test_call_group_with_ordered_members_and_ai_fallback(db_session, monkeypatch):
    fake = FakePbx()
    _, org, workflow = await _setup(db_session, monkeypatch, fake)
    created = await groups.create_group(
        org.id,
        groups.NewGroup(
            label="Équipe accueil",
            extension="4001",
            strategy="linear",
            ring_seconds=15,
            user_uuids=["u-2", "u-1"],
            fallback=ivr.MenuAction(type="ai", target_id=workflow.id),
        ),
    )
    group = fake.groups[0]
    assert group["label"] == "Equipe accueil" and group["ring_strategy"] == "linear"
    assert group["user_timeout"] == 15 and group["timeout"] == 30  # in turn: 2 × 15 s
    assert [u["uuid"] for u in group["members"]["users"]] == ["u-2", "u-1"]
    assert group["extensions"][0]["exten"] == "4001"
    key = f"nimbora-g{created['id']}"
    assert group["fallbacks"]["noanswer_destination"] == {
        "type": "custom",
        "command": f"Stasis({STASIS},inbound,called={key})",
    }
    row = await db_session.find_active_phone_number_for_inbound(org.id, key, "ari")
    assert row.inbound_workflow_id == workflow.id

    listed = await groups.list_groups(org.id)
    assert listed[0]["members"][0]["name"] == "Aya Diallo"
    assert listed[0]["fallback"] == {
        "type": "ai",
        "target_id": workflow.id,
        "workflow_name": "Accueil IA",
    }

    await groups.set_group_members(org.id, created["uuid"], ["u-1"])
    assert [u["uuid"] for u in group["members"]["users"]] == ["u-1"]
    await groups.set_group_fallback(
        org.id, created["uuid"], ivr.MenuAction(type="voicemail", target_id=1)
    )
    assert group["fallbacks"]["noanswer_destination"] == {
        "type": "voicemail",
        "voicemail_id": 1,
    }
    assert (
        await db_session.find_active_phone_number_for_inbound(org.id, key, "ari")
        is None
    )
    assert (await groups.list_groups(org.id))[0]["fallback"] == {
        "type": "voicemail",
        "target_id": 1,
    }

    # A number and a voice menu key can lead to the group.
    await numbers.set_number_destination(
        org.id, "+22527000055", ivr.MenuAction(type="group", target_id=created["id"])
    )
    incall = next(
        i
        for i in fake.incalls
        if i["extensions"] and i["extensions"][0]["exten"] == "+22527000055"
    )
    assert incall["destination"] == {"type": "group", "group_id": created["id"]}

    for bad in (
        groups.NewGroup(label="!!!", extension="4002"),
        groups.NewGroup(label="X", extension="4001"),  # number taken
        groups.NewGroup(label="X", extension="4003", strategy="loto"),
        groups.NewGroup(label="X", extension="4004", user_uuids=["u-9"]),
        groups.NewGroup(label="X", extension="4005", user_uuids=["u-1", "u-1"]),
    ):
        with pytest.raises(pbx.PbxRouteError):
            await groups.create_group(org.id, bad)
    await groups.delete_group(org.id, created["uuid"])
    assert fake.groups == [] and not any(e["exten"] == "4001" for e in fake.extensions)


# ------------------------------------------------------------- forwards


async def test_forwards_dnd_and_ai_when_unanswered(db_session, monkeypatch):
    fake = FakePbx()
    _, org, workflow = await _setup(db_session, monkeypatch, fake)
    settings = await forwards.read_user_settings(org.id, 1)
    assert settings["name"] == "Koffi Yao" and settings["dnd"] is False
    assert settings["forwards"]["unconditional"] == {
        "enabled": False,
        "destination": "",
    }

    saved = await forwards.save_user_settings(
        org.id,
        1,
        forwards.UserCallSettings(
            unconditional={"enabled": False, "destination": ""},
            noanswer={"enabled": True, "destination": "+225 07 07 11 22 33"},
            dnd=True,
            unanswered=ivr.MenuAction(type="ai", target_id=workflow.id),
        ),
    )
    assert fake.user_forwards[1]["noanswer"] == {
        "enabled": True,
        "destination": "+2250707112233",
    }
    assert fake.user_services[1]["dnd"] == {"enabled": True}
    command = f"Stasis({STASIS},inbound,called=nimbora-u1)"
    assert fake.user_fallbacks[1]["busy_destination"]["command"] == command
    assert saved["dnd"] and saved["unanswered"]["workflow_name"] == "Accueil IA"
    assert saved["forwards"]["noanswer"]["destination"] == "+2250707112233"

    # Keep the no-answer destination while changing forwards only.
    await forwards.save_user_settings(
        org.id, 1, forwards.UserCallSettings(dnd=False, unanswered_mode="keep")
    )
    assert fake.user_fallbacks[1]["noanswer_destination"]["command"] == command
    # Back to voicemail: the AI hand-off is removed.
    await forwards.save_user_settings(
        org.id,
        1,
        forwards.UserCallSettings(
            unanswered=ivr.MenuAction(type="voicemail", target_id=1)
        ),
    )
    assert fake.user_fallbacks[1]["noanswer_destination"] == {
        "type": "voicemail",
        "voicemail_id": 1,
    }
    assert (
        await db_session.find_active_phone_number_for_inbound(
            org.id, "nimbora-u1", "ari"
        )
        is None
    )

    with pytest.raises(ValueError):
        forwards.Forward(enabled=True, destination="appelle-moi")
    with pytest.raises(pbx.PbxRouteError):
        await forwards.save_user_settings(
            org.id,
            1,
            forwards.UserCallSettings(busy={"enabled": True, "destination": ""}),
        )
    with pytest.raises(pbx.PbxRouteError):
        await forwards.read_user_settings(org.id, 999)


# ---------------------------------------------------------- conferences


async def test_conference_rooms_and_live_participants(db_session, monkeypatch):
    fake = FakePbx()
    _, org, _ = await _setup(db_session, monkeypatch, fake)
    room = await conferences.create_conference(
        org.id,
        conferences.NewConference(
            name="Point hebdo",
            extension="5001",
            pin="2468",
            admin_pin="1357",
            max_users=12,
        ),
    )
    created = fake.conferences[0]
    assert created["pin"] == "2468" and created["max_users"] == 12
    assert created["extensions"][0]["exten"] == "5001"

    fake.participants[room["id"]] = [
        {
            "id": "p-1",
            "caller_id_name": "Koffi Yao",
            "caller_id_num": "1001",
            "muted": False,
            "admin": True,
            "join_time": "2026-11-21T09:00:00",
        },
        {
            "id": "p-2",
            "caller_id_name": "",
            "caller_id_num": "+2250707112233",
            "muted": False,
            "admin": False,
            "join_time": "2026-11-21T09:02:00",
        },
    ]
    listed = await conferences.list_conferences(org.id)
    shown = listed["conferences"][0]
    assert shown["has_pin"] and shown["has_admin_pin"] and "2468" not in str(listed)
    assert [p["name"] for p in shown["participants"]] == ["Koffi Yao", "+2250707112233"]

    await conferences.participant_action(org.id, room["id"], "p-2", "mute")
    assert fake.participants[room["id"]][1]["muted"] is True
    await conferences.participant_action(org.id, room["id"], "p-2", "kick")
    assert [p["id"] for p in fake.participants[room["id"]]] == ["p-1"]
    with pytest.raises(pbx.PbxRouteError):
        await conferences.participant_action(org.id, room["id"], "p-1", "explode")

    # A public number can lead straight to the room.
    await numbers.set_number_destination(
        org.id, "+22527000066", ivr.MenuAction(type="conference", target_id=room["id"])
    )
    for bad in (
        conferences.NewConference(name="", extension="5002"),
        conferences.NewConference(name="X", extension="5001"),
        conferences.NewConference(name="X", extension="5003", pin="12"),
        conferences.NewConference(
            name="X", extension="5004", pin="1234", admin_pin="1234"
        ),
        conferences.NewConference(name="X", extension="5005", max_users=900),
    ):
        with pytest.raises(pbx.PbxRouteError):
            await conferences.create_conference(org.id, bad)
    await conferences.delete_conference(org.id, room["id"])
    assert fake.conferences == [] and not any(
        e["exten"] == "5001" for e in fake.extensions
    )
    with pytest.raises(pbx.PbxRouteError):
        await conferences.delete_conference(org.id, room["id"])


# --------------------------------------------------------------- routes


async def test_routes(db_session, monkeypatch, test_client_factory):
    fake = FakePbx()
    user, org, workflow = await _setup(db_session, monkeypatch, fake)
    async with test_client_factory(user) as client:
        created = await client.post(
            "/api/v1/pbx/groups",
            json={
                "label": "Ventes",
                "extension": "4100",
                "user_uuids": ["u-1"],
                "fallback": {"type": "ai", "target_id": workflow.id},
            },
        )
        assert created.status_code == 201
        group_uuid = created.json()["uuid"]
        listed = (await client.get("/api/v1/pbx/groups")).json()
        assert (
            listed["groups"][0]["fallback"]["type"] == "ai"
            and "linear" in listed["strategies"]
        )
        assert (
            await client.put(
                f"/api/v1/pbx/groups/{group_uuid}/members", json={"user_uuids": ["u-2"]}
            )
        ).status_code == 204
        assert (
            await client.put(
                f"/api/v1/pbx/groups/{group_uuid}/fallback", json={"fallback": None}
            )
        ).status_code == 204
        assert fake.groups[0]["fallbacks"]["noanswer_destination"] is None
        assert (
            await client.delete(f"/api/v1/pbx/groups/{group_uuid}")
        ).status_code == 204

        settings = await client.put(
            "/api/v1/pbx/extensions/2/call-settings",
            json={
                "unconditional": {"enabled": True, "destination": "1001"},
                "unanswered": None,
            },
        )
        assert settings.status_code == 200
        assert settings.json()["forwards"]["unconditional"]["destination"] == "1001"
        bad = await client.put(
            "/api/v1/pbx/extensions/2/call-settings",
            json={"busy": {"enabled": True, "destination": "abc"}},
        )
        assert bad.status_code == 422
        assert (await client.get("/api/v1/pbx/extensions/2/call-settings")).json()[
            "user_id"
        ] == 2

        room = await client.post(
            "/api/v1/pbx/conferences",
            json={"name": "Codir", "extension": "5100", "pin": "9876"},
        )
        assert room.status_code == 201
        fake.participants[room.json()["id"]] = [
            {
                "id": "p-9",
                "caller_id_name": "Aya",
                "caller_id_num": "1002",
                "muted": True,
            }
        ]
        rooms = (await client.get("/api/v1/pbx/conferences")).json()
        assert rooms["conferences"][0]["participants"][0]["muted"] is True
        action = await client.post(
            f"/api/v1/pbx/conferences/{room.json()['id']}/participants/p-9/unmute"
        )
        assert action.status_code == 204
        assert (
            await client.post(
                f"/api/v1/pbx/conferences/{room.json()['id']}/participants/p-9/dance"
            )
        ).status_code == 422
        assert (
            await client.delete(f"/api/v1/pbx/conferences/{room.json()['id']}")
        ).status_code == 204
