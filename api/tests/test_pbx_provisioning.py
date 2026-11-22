"""Shared PBX of the operator: one tenant per company created by NIMBORA,
plans (shared / dedicated PBX) and human seats capped by the plan."""

import json
import re
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

from api import constants
from api.routes import pbx as pbx_routes
from api.services.pbx import admin, provisioning
from api.services.pbx import client as client_module
from api.services.pbx import service as pbx
from api.services.pbx.client import PROVISIONING_ACL, REQUIRED_ACL, PbxError
from api.services.pbx.service import PbxRouteError
from api.tests.pbx_fake import TENANT, FakePbx, install

OPERATOR = "https://pbx.operateur.example"
KIT = Path(__file__).parents[2] / "deploy/pbx"


@pytest.fixture(autouse=True)
def _operator(monkeypatch):
    client_module._TOKENS.clear()
    monkeypatch.setattr(constants, "PBX_PROVISIONING_URL", OPERATOR)
    monkeypatch.setattr(constants, "PBX_PROVISIONING_USERNAME", "nimbora-provisioning")
    monkeypatch.setattr(constants, "PBX_PROVISIONING_PASSWORD", "operator-secret")
    monkeypatch.setattr(constants, "PBX_PROVISIONING_ARI_ENDPOINT", "")
    yield


def _fake() -> FakePbx:
    return FakePbx(username="nimbora-provisioning", password="operator-secret")


class _Accept(FakePbx):
    """A PBX accepting the provisioning account and every company account."""

    def handle(self, request):
        import base64

        auth = request.headers.get("authorization", "")
        if request.url.path == "/api/auth/0.1/token" and auth.startswith("Basic "):
            user, _, password = base64.b64decode(auth[6:]).decode().partition(":")
            account = next((a for a in self.auth_users if a["username"] == user), None)
            if account and account["password"] == password:
                self.username, self.password = user, password
        return super().handle(request)


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


def _pattern(acl: str) -> str:
    return re.sub(r"\{[a-z_]+\}", "*", acl)


# -------------------------------------------------------------- policies


def test_provisioning_policy_grants_exactly_what_provisioning_needs():
    policy = json.loads((KIT / "provisioning-policy.json").read_text())
    assert set(policy["acl"]) == {_pattern(a) for a in PROVISIONING_ACL.values()}
    assert all("#" not in p for p in policy["acl"])


def test_company_service_account_gets_the_integration_policy():
    """The policy NIMBORA creates in each tenant = the kit's integration policy."""
    kit = json.loads((KIT / "integration-policy.json").read_text())
    assert set(provisioning.integration_acl()) == set(kit["acl"])
    assert {_pattern(a) for a in REQUIRED_ACL.values()} == set(
        provisioning.integration_acl()
    )


def test_kit_builds_the_provisioner_policy_as_a_superset(tmp_path):
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "create_service_account", KIT / "scripts/create_service_account.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    args = SimpleNamespace(
        provisioner=True,
        policy_file=str(KIT / "integration-policy.json"),
        provisioning_policy_file=str(KIT / "provisioning-policy.json"),
    )
    policy = module.build_policy(args)
    integration = json.loads((KIT / "integration-policy.json").read_text())["acl"]
    extra = json.loads((KIT / "provisioning-policy.json").read_text())["acl"]
    assert policy["name"] == "nimbora-provisioning"
    assert set(policy["acl"]) == set(integration) | set(extra)
    args.provisioner = False
    assert module.build_policy(args)["name"] == "nimbora-integration"


def test_install_kit_knows_the_operator_option():
    script = (KIT / "install.sh").read_text()
    assert "--operator) OPERATOR=1" in script
    assert "--provisioner" in script
    assert "PROVISIONING_PASSWORD" in script


# --------------------------------------------------------------- plans


def test_plans_saved_before_the_flags_keep_their_own_pbx():
    starter = SimpleNamespace(code="starter")
    custom = SimpleNamespace(code="sur-mesure")
    assert provisioning._legacy_feature(starter, "pbx_dedicated") is True
    assert provisioning._legacy_feature(starter, "pbx_shared") is True
    assert provisioning._legacy_feature(custom, "pbx_shared") is False


async def test_access_outside_saas_allows_everything(monkeypatch):
    monkeypatch.setattr(constants, "SAAS_MODE", False)
    access = await provisioning.pbx_access(1)
    assert access.shared and access.dedicated and access.shared_available
    assert access.seats_limit is None


# -------------------------------------------------------- provisioning


async def test_provisioning_creates_tenant_contexts_and_service_account(
    db_session, monkeypatch
):
    monkeypatch.setattr(constants, "SAAS_MODE", False)
    fake = _Accept(username="nimbora-provisioning", password="operator-secret")
    fake.auth_users.append(
        {
            "username": "nimbora-provisioning",
            "password": "operator-secret",
            "uuid": "op",
            "tenant_uuid": None,
            "policies": [],
        }
    )
    install(monkeypatch, fake)
    _, org = await _org(db_session)

    connection = await provisioning.provision_organization(
        org.id, transport=fake.transport
    )

    slug = f"org{org.id}"
    assert [t["slug"] for t in fake.auth_tenants] == [slug]
    tenant = fake.auth_tenants[0]
    assert connection.managed is True
    assert connection.tenant_uuid == tenant["uuid"]
    assert connection.base_url == OPERATOR
    assert connection.username == f"nimbora-org{org.id}"
    assert connection.provisioning["tenant_slug"] == slug

    contexts = [c for c in fake.contexts if c.get("tenant_uuid") == tenant["uuid"]]
    assert sorted(c["type"] for c in contexts) == ["incall", "internal", "outcall"]
    internal = next(c for c in contexts if c["type"] == "internal")
    assert internal["name"] == f"{slug}-internal"
    incall_ranges = next(c for c in contexts if c["type"] == "incall")["incall_ranges"]
    assert all(
        len(r["start"]) == len(r["end"]) == r["did_length"] for r in incall_ranges
    )
    outcall = next(c for c in contexts if c["type"] == "outcall")
    assert internal["user_ranges"] == [{"start": "1000", "end": "1999"}]
    assert internal["contexts"] == [{"id": outcall["id"]}]
    incall = next(c for c in contexts if c["type"] == "incall")
    assert connection.incall_context == incall["name"]

    policy = next(p for p in fake.auth_policies if p["tenant_uuid"] == tenant["uuid"])
    assert set(policy["acl"]) == set(provisioning.integration_acl())
    account = next(u for u in fake.auth_users if u["username"] == connection.username)
    assert account["tenant_uuid"] == tenant["uuid"]
    assert account["purpose"] == "external_api"
    assert account["policies"] == [policy["uuid"]]
    assert account["password"] == connection.password
    # The company's account works: the connection was checked with it.
    assert connection.status == "ok", connection.last_error


async def test_provisioning_twice_completes_without_duplicates(db_session, monkeypatch):
    monkeypatch.setattr(constants, "SAAS_MODE", False)
    fake = _Accept(username="nimbora-provisioning", password="operator-secret")
    fake.auth_users.append(
        {
            "username": "nimbora-provisioning",
            "password": "operator-secret",
            "uuid": "op",
            "tenant_uuid": None,
            "policies": [],
        }
    )
    install(monkeypatch, fake)
    _, org = await _org(db_session)

    first = await provisioning.provision_organization(org.id, transport=fake.transport)
    first_password, first_token = first.password, first.webhook_token
    fake.username, fake.password = "nimbora-provisioning", "operator-secret"
    client_module._TOKENS.clear()
    second = await provisioning.provision_organization(org.id, transport=fake.transport)

    assert len(fake.auth_tenants) == 1
    tenant = fake.auth_tenants[0]["uuid"]
    assert len([c for c in fake.contexts if c.get("tenant_uuid") == tenant]) == 3
    assert len([p for p in fake.auth_policies if p["tenant_uuid"] == tenant]) == 1
    accounts = [u for u in fake.auth_users if u["username"] == second.username]
    assert len(accounts) == 1
    assert second.password != first_password  # rotated, the old one is gone
    assert second.webhook_token == first_token


async def test_provisioning_links_the_ai_agents_with_their_own_stasis_app(
    db_session, monkeypatch
):
    monkeypatch.setattr(constants, "SAAS_MODE", False)
    monkeypatch.setattr(
        constants, "PBX_PROVISIONING_ARI_ENDPOINT", "http://10.0.0.5:5039"
    )
    monkeypatch.setattr(constants, "PBX_PROVISIONING_ARI_USER", "xivo")
    monkeypatch.setattr(constants, "PBX_PROVISIONING_ARI_PASSWORD", "ari-secret")
    monkeypatch.setattr(constants, "PBX_PROVISIONING_ARI_WS_CLIENT", "nimbora")
    fake = _Accept(username="nimbora-provisioning", password="operator-secret")
    fake.auth_users.append(
        {
            "username": "nimbora-provisioning",
            "password": "operator-secret",
            "uuid": "op",
            "tenant_uuid": None,
            "policies": [],
        }
    )
    install(monkeypatch, fake)
    _, org = await _org(db_session)
    _, other = await _org(db_session)

    connection = await provisioning.provision_organization(
        org.id, transport=fake.transport
    )
    fake.username, fake.password = "nimbora-provisioning", "operator-secret"
    client_module._TOKENS.clear()
    second = await provisioning.provision_organization(
        other.id, transport=fake.transport
    )

    ari = await db_session.get_telephony_configuration_for_org(
        connection.ari_configuration_id, org.id
    )
    ari2 = await db_session.get_telephony_configuration_for_org(
        second.ari_configuration_id, other.id
    )
    assert ari.provider == "ari"
    assert ari.credentials["ari_endpoint"] == "http://10.0.0.5:5039"
    outcall = connection.provisioning["contexts"]["outcall"]
    assert ari.credentials["dial_string_template"] == f"Local/{{number}}@{outcall}"
    # One Stasis application per company on the shared Asterisk.
    assert ari.credentials["stasis_app_name"].startswith("nimbora_")
    assert ari.credentials["stasis_app_name"] != ari2.credentials["stasis_app_name"]


async def test_plan_without_shared_pbx_is_refused(db_session, monkeypatch):
    _, org = await _org(db_session)

    async def no_shared(organization_id):
        return provisioning.PbxAccess(False, True, True, None, "Starter")

    monkeypatch.setattr(provisioning, "pbx_access", no_shared)
    with pytest.raises(PbxRouteError) as error:
        await provisioning.provision_organization(org.id)
    assert error.value.status == 403


async def test_own_pbx_already_connected_is_never_replaced(db_session, monkeypatch):
    monkeypatch.setattr(constants, "SAAS_MODE", False)
    _, org = await _org(db_session)
    await db_session.save_pbx_connection(
        org.id,
        {
            "base_url": "https://pbx.client.example",
            "username": "x",
            "password": "y",
            "webhook_token": pbx.new_webhook_token(),
        },
    )
    with pytest.raises(PbxRouteError) as error:
        await provisioning.provision_organization(org.id)
    assert error.value.status == 409


async def test_without_operator_pbx_provisioning_is_unavailable(
    db_session, monkeypatch
):
    monkeypatch.setattr(constants, "SAAS_MODE", False)
    monkeypatch.setattr(constants, "PBX_PROVISIONING_URL", "")
    _, org = await _org(db_session)
    with pytest.raises(provisioning.ProvisioningUnavailable):
        await provisioning.provision_organization(org.id)


async def test_managed_connection_is_read_only_for_the_company(db_session, monkeypatch):
    from fastapi import HTTPException

    monkeypatch.setattr(constants, "SAAS_MODE", False)
    user, org = await _org(db_session)
    await db_session.save_pbx_connection(
        org.id,
        {
            "base_url": OPERATOR,
            "username": "nimbora-org1",
            "password": "p",
            "tenant_uuid": TENANT,
            "managed": True,
            "webhook_token": pbx.new_webhook_token(),
        },
    )
    request = pbx_routes.ConnectionRequest(
        base_url="https://ailleurs.example", username="x", password="y"
    )
    with pytest.raises(HTTPException) as error:
        await pbx_routes.save_connection(request, user=user)
    assert error.value.status_code == 409
    with pytest.raises(HTTPException) as error:
        await pbx_routes.delete_connection(user=user)
    assert error.value.status_code == 409
    response = await pbx_routes.read_connection(user=user)
    assert response.managed is True


async def test_plan_without_own_pbx_cannot_connect_one(db_session, monkeypatch):
    from fastapi import HTTPException

    user, org = await _org(db_session)

    async def shared_only(organization_id):
        return provisioning.PbxAccess(True, False, True, None, "Starter")

    monkeypatch.setattr(provisioning, "pbx_access", shared_only)
    monkeypatch.setattr(pbx, "assert_pbx_url_allowed", lambda url: None)
    request = pbx_routes.ConnectionRequest(
        base_url="https://pbx.client.example", username="x", password="y"
    )
    with pytest.raises(HTTPException) as error:
        await pbx_routes.save_connection(request, user=user)
    assert error.value.status_code == 403
    assert await db_session.get_pbx_connection(org.id) is None


async def test_deprovisioning_removes_the_tenant_and_the_connection(
    db_session, monkeypatch
):
    monkeypatch.setattr(constants, "SAAS_MODE", False)
    fake = _Accept(username="nimbora-provisioning", password="operator-secret")
    fake.auth_users.append(
        {
            "username": "nimbora-provisioning",
            "password": "operator-secret",
            "uuid": "op",
            "tenant_uuid": None,
            "policies": [],
        }
    )
    install(monkeypatch, fake)
    _, org = await _org(db_session)
    await provisioning.provision_organization(org.id, transport=fake.transport)
    fake.username, fake.password = "nimbora-provisioning", "operator-secret"
    client_module._TOKENS.clear()

    assert await provisioning.deprovision_organization(org.id, transport=fake.transport)
    assert fake.auth_tenants == []
    assert await db_session.get_pbx_connection(org.id) is None
    # Nothing to remove for a company whose own PBX is connected.
    assert not await provisioning.deprovision_organization(org.id)


# ---------------------------------------------------------------- seats


async def _connected(db, monkeypatch, fake):
    user, org = await _org(db)
    install(monkeypatch, fake)
    await db.save_pbx_connection(
        org.id,
        {
            "base_url": "https://pbx.ivoire-immo.ci",
            "username": "nimbora",
            "password": "secret",
            "tenant_uuid": TENANT,
            "webhook_token": pbx.new_webhook_token(),
        },
    )
    return user, org


def _limit(monkeypatch, seats):
    monkeypatch.setattr(constants, "SAAS_MODE", True)

    async def access(organization_id):
        return provisioning.PbxAccess(True, True, True, seats, "Starter")

    monkeypatch.setattr(provisioning, "pbx_access", access)


async def test_extension_beyond_the_plan_seats_is_refused(db_session, monkeypatch):
    fake = FakePbx()
    _, org = await _connected(db_session, monkeypatch, fake)
    existing = len(fake.users)
    _limit(monkeypatch, existing + 1)

    created = await admin.create_extension(
        org.id, admin.NewExtension(firstname="Awa", lastname="Koné", extension="1050")
    )
    assert created["extension"] == "1050"
    with pytest.raises(PbxRouteError) as error:
        await admin.create_extension(
            org.id, admin.NewExtension(firstname="Yao", lastname="K", extension="1051")
        )
    assert error.value.status == 403
    assert "postes" in str(error.value)


async def test_csv_import_fills_only_the_seats_left(db_session, monkeypatch):
    fake = FakePbx()
    _, org = await _connected(db_session, monkeypatch, fake)
    _limit(monkeypatch, len(fake.users) + 2)
    content = "prenom;nom;poste\nAwa;Koné;1060\nYao;Kouassi;1061\nAya;Bamba;1062\n"
    result = await admin.run_import(org.id, content)
    assert [c["extension"] for c in result["created"]] == ["1060", "1061"]
    assert result["failed"][0]["extension"] == "1062"
    assert "offre" in result["failed"][0]["errors"][0]


async def test_contact_center_agents_count_pbx_extensions(db_session, monkeypatch):
    from api.services.saas import limits, subscription_service

    fake = FakePbx()
    _, org = await _connected(db_session, monkeypatch, fake)
    monkeypatch.setattr(limits, "SAAS_MODE", True)
    seen = {}

    async def check_limit(organization_id, name, current):
        seen[name] = current

    monkeypatch.setattr(subscription_service, "check_limit", check_limit)
    await limits.enforce_human_seat_limit(org.id)
    assert seen["max_human_seats"] == len(fake.users)

    fake.down.add("confd")  # a PBX outage never blocks the contact center
    client_module._TOKENS.clear()
    await limits.enforce_human_seat_limit(org.id)
    assert seen["max_human_seats"] == 0


def test_platform_and_kit_create_the_same_contexts():
    """deploy/pbx/scripts/ensure_tenant_contexts.py was validated on a real engine."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "ensure_tenant_contexts", KIT / "scripts/ensure_tenant_contexts.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    kit = {c["type"]: c for c in module.desired_contexts("org7")}
    ours = provisioning.desired_contexts("org7", "Ivoire Immo")
    assert set(kit) == set(ours)
    for kind, context in ours.items():
        assert context["name"] == kit[kind]["name"]
        assert context.get("incall_ranges") == kit[kind].get("incall_ranges")
        assert context["enabled"] is True
    assert ours["internal"]["user_ranges"] == kit["internal"]["user_ranges"]


async def test_logins_on_the_shared_pbx_carry_the_tenant_slug(db_session, monkeypatch):
    """The engine's logins are unique PBX-wide: two companies' "poste1001" collide.

    Seen on the lab engine (26.11): the second company's extension failed with
    "409 Conflict detected for url .../auth/0.1/users". A managed tenant prefixes
    its slug; a company's own PBX keeps "poste<number>".
    """
    fake = FakePbx()
    _, org = await _connected(db_session, monkeypatch, fake)
    own = await admin.create_extension(
        org.id, admin.NewExtension(firstname="Awa", lastname="Koné", extension="1050")
    )
    assert own["credentials"]["login"] == "poste1050"

    await db_session.save_pbx_connection(
        org.id, {"managed": True, "provisioning": {"tenant_slug": f"org{org.id}"}}
    )
    shared = await admin.create_extension(
        org.id, admin.NewExtension(firstname="Yao", lastname="K", extension="1051")
    )
    assert shared["credentials"]["login"] == f"org{org.id}-poste1051"
    # An e-mail address stays the login, slug or not.
    mailed = await admin.create_extension(
        org.id,
        admin.NewExtension(
            firstname="Aya", lastname="B", extension="1052", email="aya@example.com"
        ),
    )
    assert mailed["credentials"]["login"] == "aya@example.com"
    # The fake now refuses a duplicate login like the engine does.
    with pytest.raises(PbxError):
        fake.users.append({"auth": {"username": f"org{org.id}-poste1053"}, "lines": []})
        await admin.create_extension(
            org.id, admin.NewExtension(firstname="Dup", lastname="L", extension="1053")
        )


class _EngineDefaults(_Accept):
    """Like the 26.11 engine: a new tenant comes with its own default contexts,
    without numbering ranges (incall_ranges [])."""

    def handle(self, request):
        response = super().handle(request)
        if request.url.path == "/api/auth/0.1/tenants" and request.method == "POST":
            tenant = response.json()["uuid"]
            for kind, extra in (
                ("internal", {"user_ranges": [{"start": "1000", "end": "1099"}]}),
                ("incall", {"incall_ranges": []}),
                ("outcall", {}),
            ):
                self.contexts.append(
                    {
                        "id": self._id(),
                        "name": f"ctx-default-{kind}-{tenant[:8]}",
                        "label": f"Default {kind}",
                        "type": kind,
                        "enabled": True,
                        "tenant_uuid": tenant,
                        **extra,
                    }
                )
        return response


async def test_engine_default_contexts_get_their_missing_ranges(db_session, monkeypatch):
    monkeypatch.setattr(constants, "SAAS_MODE", False)
    fake = _EngineDefaults(username="nimbora-provisioning", password="operator-secret")
    fake.auth_users.append(
        {
            "username": "nimbora-provisioning",
            "password": "operator-secret",
            "uuid": "op",
            "tenant_uuid": None,
            "policies": [],
        }
    )
    install(monkeypatch, fake)
    _, org = await _org(db_session)

    await provisioning.provision_organization(org.id, transport=fake.transport)

    tenant = fake.auth_tenants[0]["uuid"]
    mine = {c["type"]: c for c in fake.contexts if c.get("tenant_uuid") == tenant}
    assert len([c for c in fake.contexts if c.get("tenant_uuid") == tenant]) == 3
    # Inbound numbers of 4 to 15 digits can now be routed.
    assert [r["did_length"] for r in mine["incall"]["incall_ranges"]] == list(range(4, 16))
    # A range already set on the engine is kept; the empty ones are filled.
    assert mine["internal"]["user_ranges"] == [{"start": "1000", "end": "1099"}]
    assert mine["internal"]["queue_ranges"]
    assert mine["outcall"]["id"] in [c["id"] for c in mine["internal"]["contexts"]]


def test_missing_ranges_never_overwrites_existing_ones():
    desired = provisioning.desired_contexts("org9", "Entreprise 9")["internal"]
    existing = {"user_ranges": [{"start": "5000", "end": "5999"}], "group_ranges": []}
    missing = provisioning.missing_ranges(existing, desired)
    assert "user_ranges" not in missing
    assert set(missing) == {"group_ranges", "queue_ranges", "conference_room_ranges"}
