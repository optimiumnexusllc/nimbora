"""AI calls out through the PBX's lines, call restrictions per extension, and
the organization's blocked numbers on every channel."""

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from api.services.pbx import client as client_module
from api.services.pbx import outbound, permissions, trunks
from api.services.pbx import service as pbx
from api.services.telephony import blocklist
from api.services.telephony.providers.ari.dial_string import format_dialled_number
from api.tests.pbx_fake import TENANT, FakePbx, install

BASE = "https://pbx.ivoire-immo.ci"


@pytest.fixture(autouse=True)
def _clear_tokens():
    client_module._TOKENS.clear()
    yield


async def _org(db):
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


async def _setup(db, monkeypatch, fake):
    user, org = await _org(db)
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
    return user, org, config


# ------------------------------------------------- dialled number format


def test_dialled_number_formats():
    assert format_dialled_number("+2250707112233", "as_is") == "+2250707112233"
    assert format_dialled_number("+33612345678", "international_00") == "0033612345678"
    # Côte d'Ivoire: the national number already starts with 0.
    assert (
        format_dialled_number("+2250707112233", "national", "225", "") == "0707112233"
    )
    # France: national prefix 0 in front.
    assert format_dialled_number("+33612345678", "national", "33", "0") == "0612345678"
    # Another country in national mode → international 00.
    assert (
        format_dialled_number("+33612345678", "national", "225", "") == "0033612345678"
    )
    # Already written for the dialplan: untouched.
    assert format_dialled_number("0707112233", "national", "225", "") == "0707112233"
    assert format_dialled_number("PJSIP/1001", "international_00") == "PJSIP/1001"


async def test_ari_provider_dials_the_formatted_number(monkeypatch):
    from api.services.telephony.providers.ari import _config_loader
    from api.services.telephony.providers.ari import provider as ari_provider

    config = _config_loader(
        {
            "ari_endpoint": "http://pbx:5039",
            "app_name": "a",
            "app_password": "p",
            "stasis_app_name": "s",
            "dial_string_template": "Local/{number}@to-extern",
            "dial_number_format": "national",
            "dial_country_code": "225",
        }
    )
    provider = ari_provider.ARIProvider(config)
    sent = {}

    class _Response:
        status = 200

        async def text(self):
            return '{"state": "Down", "name": "Local/x"}'

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return None

    class _Session:
        def post(self, url, params, auth):
            sent.update(params)
            return _Response()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return None

    async def _noop(*args, **kwargs):
        return None

    monkeypatch.setattr(ari_provider.aiohttp, "ClientSession", _Session)
    monkeypatch.setattr(ari_provider, "register_channel", _noop)
    await provider.initiate_call("+2250707112233", "http://x", workflow_run_id=1)
    assert sent["endpoint"] == "Local/0707112233@to-extern"


# -------------------------------------------------------- AI outbound


async def test_ai_calls_go_out_through_the_pbx(db_session, monkeypatch):
    fake = FakePbx()
    _, org, config = await _setup(db_session, monkeypatch, fake)
    with pytest.raises(pbx.PbxRouteError, match="route sortante"):
        await outbound.configure(org.id, mode="routes")

    line = await trunks.create_trunk(
        org.id, trunks.NewTrunk(label="Orange", host="sip.orange.ci", register=False)
    )
    await trunks.create_outbound_route(
        org.id,
        trunks.NewOutboundRoute(
            name="National",
            trunk_ids=[line["id"]],
            rules=[trunks.DialRule("_0XXXXXXXXX")],
        ),
    )
    settings = await outbound.configure(
        org.id,
        mode="routes",
        number_format="national",
        country_code="+225",
        caller_id="+225 27 22 00 00 00",
    )
    assert settings["mode"] == "routes"
    assert settings["dial_string_template"] == "Local/{number}@to-extern"
    assert settings["example"]["dial_string"] == "Local/0707112233@to-extern"
    assert settings["caller_id"] == "+2252722000000"
    stored = await db_session.get_telephony_configuration_for_org(config.id, org.id)
    assert stored.credentials["stasis_app_name"] == "nimbora_ab12cd34ef56"  # kept
    assert stored.credentials["dial_country_code"] == "225"
    default = await db_session.get_default_caller_id(config.id)
    assert default.address_normalized == "+2252722000000"

    endpoint_name = fake.trunks[0]["endpoint_sip"]["name"]
    settings = await outbound.configure(
        org.id, mode="trunk", trunk_id=line["id"], number_format="international_00"
    )
    assert settings["dial_string_template"] == f"PJSIP/{{number}}@{endpoint_name}"
    assert settings["trunk_id"] == line["id"]
    assert (
        settings["example"]["dial_string"] == f"PJSIP/002250707112233@{endpoint_name}"
    )
    assert settings["caller_id"] == "+2252722000000"  # unchanged when not given

    for bad in (
        {"mode": "trunk"},
        {"mode": "routes", "number_format": "national"},
        {"mode": "routes", "caller_id": "standard"},
        {"mode": "routes", "national_prefix": "x"},
    ):
        with pytest.raises(pbx.PbxRouteError):
            await outbound.configure(org.id, **bad)


async def test_ai_outbound_needs_ari(db_session, monkeypatch):
    fake = FakePbx()
    _, org = await _org(db_session)
    install(monkeypatch, fake)
    await db_session.save_pbx_connection(
        org.id,
        {
            "base_url": BASE,
            "username": "nimbora",
            "password": "secret",
            "tenant_uuid": TENANT,
            "webhook_token": pbx.new_webhook_token(),
        },
    )
    with pytest.raises(pbx.PbxRouteError, match="ARI"):
        await outbound.read_settings(org.id)


# --------------------------------------------------- call restrictions


async def test_call_restrictions_per_extension(db_session, monkeypatch):
    fake = FakePbx()
    _, org, _ = await _setup(db_session, monkeypatch, fake)
    created = await permissions.create_restriction(
        org.id,
        permissions.NewRestriction(
            name="Accueil : pas d'international",
            patterns=["_00.", "_+X."],
            user_ids=[1],
            pin="4321",
        ),
    )
    assert created["mode"] == "deny" and created["has_pin"]
    assert created["patterns"] == ["_00.", "_+X."]
    assert [u["name"] for u in created["users"]] == ["Koffi Yao"]
    assert fake.call_permissions[0]["password"] == "4321"

    updated = await permissions.set_restriction_users(org.id, created["id"], [2])
    assert [u["uuid"] for u in updated["users"]] == ["u-2"]
    listed = await permissions.list_restrictions(org.id)
    assert listed[0]["name"] == "Accueil : pas d'international"
    assert "4321" not in str(listed)  # the PIN never comes back

    for bad in (
        permissions.NewRestriction(name="", patterns=["_00."]),
        permissions.NewRestriction(name="X", patterns=["00;rm"]),
        permissions.NewRestriction(name="X", patterns=["_00."], pin="12ab"),
        permissions.NewRestriction(name="X", patterns=["_00."], user_ids=[999]),
    ):
        with pytest.raises(pbx.PbxRouteError):
            await permissions.create_restriction(org.id, bad)
    with pytest.raises(pbx.PbxRouteError):
        await permissions.set_restriction_users(org.id, created["id"], [999])
    await permissions.delete_restriction(org.id, created["id"])
    assert fake.call_permissions == []


# ------------------------------------------------------ blocked numbers


async def test_blocked_numbers_by_direction_and_expiry(db_session):
    _, org = await _org(db_session)
    _, other = await _org(db_session)
    await blocklist.block(
        org.id, blocklist.BlockRequest("+225 07 07-11.22.33", "inbound", "Harcèlement")
    )
    await blocklist.block(org.id, blocklist.BlockRequest("0022505050505", "outbound"))
    await blocklist.block(
        org.id,
        blocklist.BlockRequest(
            "+22501010101", "both", expires_at=datetime.now(UTC) - timedelta(days=1)
        ),
    )
    assert await blocklist.find_block(org.id, "+2250707112233", "inbound")
    assert await blocklist.find_block(org.id, "2250707112233", "inbound")  # no +
    assert not await blocklist.find_block(org.id, "+2250707112233", "outbound")
    assert await blocklist.find_block(org.id, "+22505050505", "outbound")
    assert not await blocklist.find_block(org.id, "+22501010101", "inbound")  # expired
    assert not await blocklist.find_block(other.id, "+2250707112233", "inbound")
    assert not await blocklist.find_block(org.id, None, "inbound")
    with pytest.raises(blocklist.CallBlocked):
        await blocklist.assert_may_call(org.id, "+22505050505")
    await blocklist.assert_may_call(org.id, "+2250707112233")

    rows = await db_session.list_blocked_numbers(org.id)
    hit = next(r for r in rows if r.number == "+2250707112233")
    assert hit.hits == 2 and hit.last_hit_at is not None
    # Blocking again updates the entry, never duplicates it.
    await blocklist.block(org.id, blocklist.BlockRequest("+2250707112233", "both"))
    assert await db_session.count_blocked_numbers(org.id) == 3
    with pytest.raises(blocklist.BlockedNumberError):
        await blocklist.block(org.id, blocklist.BlockRequest("abc"))


def test_import_parsing():
    requests, errors = blocklist.parse_import(
        "numero;motif;sens\n"
        "+2250707112233;Démarchage;entrant\n"
        "0033612345678;;sortant\n"
        "+2250707112233;doublon;\n"
        "pas-un-numero;x;\n"
        "+22501010101;x;parfois\n"
    )
    assert [(r.number, r.direction, r.reason) for r in requests] == [
        ("+2250707112233", "inbound", "Démarchage"),
        ("+33612345678", "outbound", ""),
    ]
    assert [e["line"] for e in errors] == [4, 5]


async def test_opt_out_disposition_blocks_outbound(db_session):
    _, org = await _org(db_session)
    run = SimpleNamespace(
        id=77,
        gathered_context={
            "mapped_call_disposition": "DNC",
            "call_disposition": "do_not_call",
        },
        initial_context={"direction": "outbound", "phone_number": "+2250707990000"},
    )
    assert await blocklist.block_on_opt_out(run, org.id)
    entry = (await db_session.list_blocked_numbers(org.id))[0]
    assert entry.direction == "outbound" and entry.source == "caller_request"
    assert "n°77" in entry.reason
    assert not await blocklist.block_on_opt_out(run, org.id)  # already there
    # An inbound-only entry is widened to both, never narrowed.
    await blocklist.block(org.id, blocklist.BlockRequest("+2250707880000", "inbound"))
    run.initial_context = {"direction": "inbound", "caller_number": "+2250707880000"}
    assert await blocklist.block_on_opt_out(run, org.id)
    rows = {
        r.number: r.direction for r in await db_session.list_blocked_numbers(org.id)
    }
    assert rows["+2250707880000"] == "both"
    run.gathered_context = {"call_disposition": "qualified"}
    run.initial_context = {"direction": "inbound", "caller_number": "+2250707770000"}
    assert not await blocklist.block_on_opt_out(run, org.id)


async def test_blocked_callbacks_are_never_dialled(db_session, monkeypatch):
    from api.services.contact_center import callbacks as cb

    user, org = await _org(db_session)
    workflow = await db_session.create_workflow(
        "Rappel", {"nodes": [], "edges": []}, user.id, org.id
    )
    now = datetime.now(UTC)
    callback = await cb.create_or_update_callback(
        org.id,
        phone="+22790000099",
        scheduled_at=now - timedelta(minutes=1),
        source="manual",
        assign_to="ai",
        workflow_id=workflow.id,
    )
    await blocklist.block(org.id, blocklist.BlockRequest("+22790000099", "outbound"))
    placed = []

    async def fake_place(c):
        placed.append(c.id)

    monkeypatch.setattr(cb, "_place_ai_callback", fake_place)
    await cb.dispatch_due_ai_callbacks(now)
    assert callback.id not in placed
    stored = await db_session.get_callback_request(org.id, callback.id)
    assert stored.status == "failed" and "bloqué" in stored.outcome
    with pytest.raises(cb.CallbackError, match="bloqué"):
        monkeypatch.setattr("api.constants.ASTERISK_ARI_PASSWORD", "x")
        await cb.dial_callback_for_agent(stored, SimpleNamespace(sip_username="a1"))


async def test_ari_inbound_hangs_up_blocked_callers(db_session, monkeypatch):
    from api.services.telephony.ari_manager import ARIConnection

    user, org = await _org(db_session)
    config = await db_session.create_telephony_configuration(
        organization_id=org.id,
        name="ARI",
        provider="ari",
        credentials={
            "ari_endpoint": "http://pbx:5039",
            "app_name": "a",
            "app_password": "p",
        },
    )
    workflow = await db_session.create_workflow(
        "Accueil", {"nodes": [], "edges": []}, user.id, org.id
    )
    await db_session.create_phone_number(
        organization_id=org.id,
        telephony_configuration_id=config.id,
        address="+22527000000",
        inbound_workflow_id=workflow.id,
    )
    await blocklist.block(org.id, blocklist.BlockRequest("+2250707112233", "inbound"))
    connection = ARIConnection(org.id, config.id, "http://pbx:5039", "a", "p")
    deleted = []

    async def fake_delete(channel_id):
        deleted.append(channel_id)

    async def must_not_run(*args, **kwargs):
        raise AssertionError("a blocked caller reached the agent")

    monkeypatch.setattr(connection, "_delete_channel", fake_delete)
    monkeypatch.setattr(
        "api.services.telephony.ari_manager.call_concurrency.acquire_org_slot",
        must_not_run,
    )
    await connection._handle_inbound_stasis_start(
        "chan-1",
        "Up",
        {
            "channel": {
                "caller": {"number": "+2250707112233"},
                "dialplan": {"exten": "s"},
            },
            "args": ["inbound", "called=+22527000000"],
        },
    )
    assert deleted == ["chan-1"]


async def test_blocked_number_routes(db_session, test_client_factory):
    user, org = await _org(db_session)
    async with test_client_factory(user) as client:
        added = await client.post(
            "/api/v1/blocked-numbers",
            json={
                "number": "+225 07 07 11 22 33",
                "direction": "inbound",
                "reason": "Spam",
            },
        )
        assert added.status_code == 201 and added.json()["number"] == "+2250707112233"
        assert (
            await client.post("/api/v1/blocked-numbers", json={"number": "abcd"})
        ).status_code == 422
        imported = await client.post(
            "/api/v1/blocked-numbers/import",
            json={"content": "+33612345678;Opposition;sortant\nxx;;\n"},
        )
        assert imported.json()["imported"] == 1 and len(imported.json()["errors"]) == 1
        listed = (await client.get("/api/v1/blocked-numbers")).json()
        assert listed["total"] == 2
        assert listed["stats"] == {"total": 2, "hits": 0, "caller_requests": 0}
        found = (
            await client.get("/api/v1/blocked-numbers", params={"search": "Spam"})
        ).json()
        assert [i["number"] for i in found["items"]] == ["+2250707112233"]
        entry = added.json()["id"]
        assert (
            await client.delete(f"/api/v1/blocked-numbers/{entry}")
        ).status_code == 204
        assert (
            await client.delete(f"/api/v1/blocked-numbers/{entry}")
        ).status_code == 404


async def test_pbx_routes_for_ai_outbound_and_restrictions(
    db_session, monkeypatch, test_client_factory
):
    fake = FakePbx()
    user, org, _ = await _setup(db_session, monkeypatch, fake)
    async with test_client_factory(user) as client:
        trunk = (
            await client.post(
                "/api/v1/pbx/trunks",
                json={
                    "label": "Orange",
                    "host": "sip.orange.ci",
                    "registration": False,
                },
            )
        ).json()
        saved = await client.put(
            "/api/v1/pbx/ai-outbound",
            json={
                "mode": "trunk",
                "trunk_id": trunk["id"],
                "caller_id": "+2252722000000",
            },
        )
        assert saved.status_code == 200 and saved.json()["mode"] == "trunk"
        assert (await client.get("/api/v1/pbx/ai-outbound")).json()[
            "trunk_id"
        ] == trunk["id"]
        created = await client.post(
            "/api/v1/pbx/restrictions",
            json={"name": "Stagiaires", "patterns": ["_00."], "user_ids": [1, 2]},
        )
        assert created.status_code == 201 and len(created.json()["users"]) == 2
        listed = (await client.get("/api/v1/pbx/restrictions")).json()
        assert listed["presets"] and listed["restrictions"][0]["name"] == "Stagiaires"
        users = await client.put(
            f"/api/v1/pbx/restrictions/{created.json()['id']}/users",
            json={"user_ids": []},
        )
        assert users.json()["users"] == []
        assert (
            await client.delete(f"/api/v1/pbx/restrictions/{created.json()['id']}")
        ).status_code == 204
