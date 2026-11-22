"""NIMBORA Softphone: pairing with a one-time code, device tokens, live SIP
configuration from the PBX, directory, history, status, revocation."""

import uuid

import pytest

from api.services.pbx import admin, softphone
from api.services.pbx import client as client_module
from api.services.pbx import service as pbx
from api.tests.pbx_fake import TENANT, FakePbx, install

BASE = "https://pbx.ivoire-immo.ci"
REAL_THROTTLE = softphone._too_many_attempts


@pytest.fixture(autouse=True)
def _clear_tokens(monkeypatch):
    client_module._TOKENS.clear()

    async def no_throttle(client_key):
        return False

    monkeypatch.setattr(softphone, "_too_many_attempts", no_throttle)
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
    install(monkeypatch, fake)
    await db.save_pbx_connection(
        org.id,
        {
            "base_url": BASE,
            "username": "nimbora",
            "password": "secret",
            "tenant_uuid": TENANT,
            "webhook_token": pbx.new_webhook_token(),
        },
    )
    return user, org


def test_codes_are_readable_and_tokens_prefixed():
    code = softphone.new_code()
    assert len(code) == 8 and not set(code) & set("01OIL")
    assert softphone.format_code("ABCD2345") == "ABCD-2345"
    assert softphone.normalize_code(" abcd-2345 ") == "ABCD2345"
    assert softphone.new_token().startswith("nsp_")


async def test_pairing_and_live_configuration(db_session, monkeypatch):
    fake = FakePbx()
    # Managed lines: the endpoint name (SIP identity) differs from the auth username.
    fake.user_endpoints["sip-u1"]["name"] = "k0ff1y40"
    user, org = await _setup(db_session, monkeypatch, fake)
    activation = await softphone.create_activation(org.id, "u-1", created_by=user.id)
    assert (
        activation["display_name"] == "Koffi Yao" and activation["extension"] == "1001"
    )
    assert activation["link"].startswith("nimbora-softphone://activate?")
    assert activation["code"][4] == "-"

    paired = await softphone.activate(
        activation["code"].lower(),
        device_name="PC de Koffi",
        platform="windows",
        app_version="1.0.0",
        client_key="1.2.3.4",
    )
    token = paired["token"]
    config = paired["config"]
    assert config["account"] == {
        "display_name": "Koffi Yao",
        "extension": "1001",
        "sip_identity": "k0ff1y40",
        "username": "koffi1001",
        "password": "Sip-Secret-1001",
        "wss_url": "wss://pbx.ivoire-immo.ci/api/asterisk/ws",
        "sip_domain": "pbx.ivoire-immo.ci",
    }
    assert config["brand"]["name"] == "NIMBORA"
    assert config["device"]["platform"] == "windows"
    assert config["ice_servers"][0]["urls"][0].startswith("stun:")

    # The code works once.
    with pytest.raises(softphone.SoftphoneAuthError):
        await softphone.activate(
            activation["code"],
            device_name="x",
            platform="web",
            app_version=None,
            client_key="x",
        )
    with pytest.raises(softphone.SoftphoneAuthError):
        await softphone.activate(
            "ZZZZ-ZZZZ",
            device_name="x",
            platform="web",
            app_version=None,
            client_key="x",
        )

    # Only a hash of the token is stored; the token finds the device.
    devices = await db_session.list_softphone_devices(org.id)
    assert devices[0].token_hash != token and len(devices[0].token_hash) == 64
    # Pairing counts as the first connection.
    assert devices[0].last_seen_at is not None
    device = await softphone.device_for_token(token)
    assert device.pbx_user_uuid == "u-1"
    for bad in (None, "", "Bearer x", "nsp_unknown"):
        with pytest.raises(softphone.SoftphoneAuthError):
            await softphone.device_for_token(bad)

    # A new SIP secret on the PBX reaches the app on its next start.
    fake.user_endpoints["sip-u1"]["auth_section_options"][1][1] = "Rotated-Secret"
    assert (await softphone.device_config(device))["account"][
        "password"
    ] == "Rotated-Secret"

    # Overrides for the WebSocket address and SIP domain.
    await db_session.save_pbx_connection(
        org.id,
        {
            "softphone_settings": {
                "wss_url": "wss://voix.ivoire-immo.ci/ws",
                "sip_domain": "ivoire-immo.ci",
            }
        },
    )
    account = (await softphone.device_config(device))["account"]
    assert account["wss_url"] == "wss://voix.ivoire-immo.ci/ws"
    assert account["sip_domain"] == "ivoire-immo.ci"

    listed = await softphone.list_devices(org.id)
    assert (
        listed[0]["extension_name"] == "Koffi Yao (1001)"
        and listed[0]["platform"] == "windows"
    )
    assert "token" not in str(listed).lower().replace("token_", "")


async def test_desk_phone_lines_cannot_pair(db_session, monkeypatch):
    fake = FakePbx()
    user, org = await _setup(db_session, monkeypatch, fake)
    with pytest.raises(pbx.PbxRouteError, match="WebRTC"):
        await softphone.create_activation(org.id, "u-2", created_by=user.id)


async def test_new_browser_extension_pairs_and_deleting_it_revokes(
    db_session, monkeypatch
):
    fake = FakePbx()
    user, org = await _setup(db_session, monkeypatch, fake)
    created = await admin.create_extension(
        org.id,
        admin.NewExtension(
            firstname="Mariam", lastname="Traoré", extension="1030", line="webrtc"
        ),
    )
    activation = await softphone.create_activation(
        org.id, created["uuid"], created_by=user.id
    )
    paired = await softphone.activate(
        activation["code"],
        device_name="iPhone",
        platform="ios",
        app_version="1.0.0",
        client_key="k",
    )
    assert paired["config"]["account"]["extension"] == "1030"
    assert (
        paired["config"]["account"]["password"]
        == created["credentials"]["sip_password"]
    )
    await admin.delete_extension(org.id, created["uuid"])
    with pytest.raises(softphone.SoftphoneAuthError):
        await softphone.device_for_token(paired["token"])


async def test_directory_history_and_status(db_session, monkeypatch):
    fake = FakePbx()
    user, org = await _setup(db_session, monkeypatch, fake)
    activation = await softphone.create_activation(org.id, "u-1", created_by=user.id)
    paired = await softphone.activate(
        activation["code"],
        device_name="Android",
        platform="android",
        app_version="1",
        client_key="k",
    )
    device = await softphone.device_for_token(paired["token"])

    found = await softphone.directory(device)
    me = next(p for p in found["people"] if p["extension"] == "1001")
    assert (me["name"], me["me"], me["presence"]["state"]) == (
        "Koffi Yao",
        True,
        "on_call",
    )
    assert found["services"] == [
        {"name": "Ventes", "extension": "3001", "kind": "queue"}
    ]

    fake.cdr = [
        {
            "id": 1,
            "start": "2026-11-21T08:00:00+00:00",
            "answered": True,
            "duration": 65.0,
            "source_extension": "+2250700112233",
            "source_name": "Awa",
            "destination_extension": "1001",
            "destination_user_uuid": "u-1",
        },
        {
            "id": 2,
            "start": "2026-11-21T09:00:00+00:00",
            "answered": False,
            "duration": 0,
            "source_extension": "1001",
            "source_user_uuid": "u-1",
            "destination_extension": "0707445566",
            "destination_name": "",
        },
        {
            "id": 3,
            "start": "2026-11-21T09:30:00+00:00",
            "answered": True,
            "duration": 5,
            "source_extension": "1002",
            "destination_extension": "3001",
        },
    ]
    calls = await softphone.history(device)
    assert [(c["direction"], c["number"], c["answered"]) for c in calls] == [
        ("incoming", "+2250700112233", True),
        ("outgoing", "0707445566", False),
    ]
    assert calls[0]["name"] == "Awa" and calls[0]["duration"] == 65

    status = await softphone.save_status(
        device, dnd=True, forward_enabled=True, forward_to="+225 07 07 11 22 33"
    )
    assert status == {
        "dnd": True,
        "forward": {"enabled": True, "destination": "+2250707112233"},
    }
    assert fake.user_services[1]["dnd"] == {"enabled": True}
    assert await softphone.read_status(device) == status


async def test_routes(db_session, monkeypatch, test_client_factory):
    fake = FakePbx()
    user, org = await _setup(db_session, monkeypatch, fake)
    async with test_client_factory(user) as client:
        created = await client.post("/api/v1/pbx/extensions/u-1/softphone")
        assert created.status_code == 201
        code = created.json()["code"]
        assert (
            await client.post("/api/v1/pbx/extensions/u-2/softphone")
        ).status_code == 409

        activated = await client.post(
            "/api/v1/softphone/activate",
            json={
                "code": code,
                "device_name": "MacBook",
                "platform": "macos",
                "app_version": "1.0.0",
            },
        )
        assert activated.status_code == 200
        token = activated.json()["token"]
        headers = {"Authorization": f"Bearer {token}", "X-App-Version": "1.0.1"}
        assert (
            await client.post("/api/v1/softphone/activate", json={"code": code})
        ).status_code == 401
        config = await client.get("/api/v1/softphone/config", headers=headers)
        assert config.json()["account"]["username"] == "koffi1001"
        assert (await client.get("/api/v1/softphone/config")).status_code == 401
        assert (
            await client.get("/api/v1/softphone/directory", headers=headers)
        ).status_code == 200
        assert (
            await client.get("/api/v1/softphone/history", headers=headers)
        ).status_code == 200
        status = await client.put(
            "/api/v1/softphone/status", headers=headers, json={"dnd": True}
        )
        assert status.json()["dnd"] is True

        devices = (await client.get("/api/v1/pbx/softphone/devices")).json()
        assert devices[0]["name"] == "MacBook" and devices[0]["app_version"] == "1.0.1"
        settings = await client.put(
            "/api/v1/pbx/softphone/settings",
            json={"wss_url": "https://bad", "sip_domain": ""},
        )
        assert settings.status_code == 422
        settings = await client.put(
            "/api/v1/pbx/softphone/settings", json={"wss_url": "wss://voix.example/ws"}
        )
        assert settings.json()["wss_url"] == "wss://voix.example/ws"
        assert (await client.get("/api/v1/pbx/softphone/settings")).json()[
            "sip_domain"
        ] == "pbx.ivoire-immo.ci"

        # The app signs out; then an admin cannot revoke it twice.
        assert (
            await client.delete("/api/v1/softphone/device", headers=headers)
        ).status_code == 204
        assert (
            await client.get("/api/v1/softphone/config", headers=headers)
        ).status_code == 401
        assert (
            await client.delete(f"/api/v1/pbx/softphone/devices/{devices[0]['id']}")
        ).status_code == 404


async def test_activation_attempts_are_throttled(monkeypatch):
    calls = []

    class FakeRedis:
        def __init__(self):
            self.n = 0

        async def incr(self, key):
            self.n += 1
            calls.append(key)
            return self.n

        async def expire(self, key, seconds):
            calls.append(("expire", seconds))

    redis = FakeRedis()

    async def get_redis():
        return redis

    monkeypatch.setattr("api.services.supervision.live_calls.get_redis", get_redis)
    results = [await REAL_THROTTLE("9.9.9.9") for _ in range(11)]
    assert results[:10] == [False] * 10 and results[10] is True
    assert ("expire", 600) in calls


async def _paired(db_session, monkeypatch, fake):
    user, org = await _setup(db_session, monkeypatch, fake)
    activation = await softphone.create_activation(org.id, "u-1", created_by=user.id)
    paired = await softphone.activate(
        activation["code"],
        device_name="Android",
        platform="android",
        app_version="1",
        client_key="k",
    )
    return user, org, await softphone.device_for_token(paired["token"])


async def test_colleagues_show_their_presence(db_session, monkeypatch):
    fake = FakePbx()
    _, _, device = await _paired(db_session, monkeypatch, fake)
    fake.presences[1].update(state="away", status="En réunion jusqu'à 15 h")

    found = await softphone.directory(device)
    aya = next(p for p in found["people"] if p["extension"] == "1002")
    assert aya["presence"] == {
        "state": "away",
        "label": "Absent",
        "status": "En réunion jusqu'à 15 h",
    }
    assert found["presence_live"] is True

    # The employee says they are back; colleagues see it.
    saved = await softphone.save_presence(device, "available", "")
    assert saved["state"] == "available"
    assert fake.presences[0]["state"] == "available"
    with pytest.raises(ValueError):
        await softphone.save_presence(device, "on_call")

    # « Hors ligne » chosen in the app stays offline although the phone is
    # registered (sent as "invisible", lab step 10).
    await softphone.save_presence(device, "offline")
    assert fake.presences[0]["state"] == "invisible"
    fake.presences[0]["line_state"] = "available"
    me = next(p for p in (await softphone.directory(device))["people"] if p["me"])
    assert me["presence"]["state"] == "offline"


async def test_presence_without_presence_rights_falls_back_on_calls(
    db_session, monkeypatch
):
    fake = FakePbx()
    _, _, device = await _paired(db_session, monkeypatch, fake)
    fake.forbidden.add("chatd")  # an account made before NIMBORA asked for presence

    found = await softphone.directory(device)
    states = {p["extension"]: p["presence"]["state"] for p in found["people"]}
    assert states == {"1001": "on_call", "1002": "unknown"}
    assert found["presence_live"] is False


async def test_directory_includes_customers_when_memory_is_on(db_session, monkeypatch):
    fake = FakePbx()
    _, org, device = await _paired(db_session, monkeypatch, fake)
    await db_session.upsert_configuration(org.id, "CUSTOMER_MEMORY", {"enabled": False})
    assert (await softphone.directory(device))["customers"] is None  # memory off

    await db_session.upsert_configuration(org.id, "CUSTOMER_MEMORY", {"enabled": True})
    awa = await db_session.get_or_create_customer_profile(
        org.id, "+2250700112233", "700112233"
    )
    await db_session.update_customer_profile(
        org.id,
        awa.id,
        {
            "name": "Awa Koné",
            "tags": ["VIP"],
            "attributes": {"usual_advisor": {"extension": "1001", "name": "Koffi Yao"}},
        },
    )
    await db_session.get_or_create_customer_profile(
        org.id, "+2250500998877", "500998877"
    )

    everyone = (await softphone.directory(device))["customers"]
    assert len(everyone) == 2
    found = (await softphone.directory(device, query="koné"))["customers"]
    assert [(c["name"], c["number"], c["vip"], c["advisor"]) for c in found] == [
        ("Awa Koné", "+2250700112233", True, "Koffi Yao")
    ]
    by_number = (await softphone.directory(device, query="0500998877"[-6:]))[
        "customers"
    ]
    assert [c["number"] for c in by_number] == ["+2250500998877"]
