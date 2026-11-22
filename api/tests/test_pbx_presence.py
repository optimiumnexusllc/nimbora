"""Presence of the company's employees, and service accounts kept up to date."""

import pytest

from api import constants
from api.services.pbx import client as client_module
from api.services.pbx import presence, provisioning
from api.tests.pbx_fake import FakePbx, install
from api.tests.test_pbx_provisioning import _Accept, _org
from api.tests.test_softphone import _setup


@pytest.mark.parametrize(
    ("item", "state"),
    [
        ({"line_state": "talking", "do_not_disturb": True}, "on_call"),
        ({"line_state": "holding"}, "on_call"),
        ({"line_state": "ringing"}, "ringing"),
        ({"line_state": "progressing"}, "ringing"),
        ({"line_state": "available", "do_not_disturb": True}, "dnd"),
        ({"line_state": "available", "state": "away"}, "away"),
        ({"line_state": "available", "state": "invisible"}, "offline"),
        # Seen on the lab engine: registered phones whose user never set a chat
        # presence have state "unavailable" — they are reachable, not offline.
        ({"line_state": "available", "state": "unavailable", "connected": False}, "available"),
        ({"line_state": "unavailable", "state": "unavailable", "connected": False}, "offline"),
        (
            {"line_state": "unavailable", "state": "available", "connected": False},
            "offline",
        ),
        (
            {"line_state": "unavailable", "state": "available", "mobile": True},
            "available",
        ),
        (
            {"line_state": "available", "state": "available", "connected": True},
            "available",
        ),
    ],
)
def test_one_state_per_person_in_the_order_colleagues_care_about(item, state):
    assert presence.from_engine(item) == state


def test_calls_in_progress_give_on_call_and_ringing():
    calls = [
        {"user_uuid": "a", "status": "Up", "answer_time": "2026-11-22T09:00:00"},
        {"user_uuid": "b", "status": "Ringing"},
        {"user_uuid": "a", "status": "Ringing"},  # second call while talking
        {"status": "Up"},  # trunk leg, nobody
    ]
    assert presence.from_calls(calls) == {"a": "on_call", "b": "ringing"}


async def test_console_shows_the_presence_of_each_extension(
    db_session, monkeypatch, test_client_factory
):
    fake = FakePbx()
    user, _ = await _setup(db_session, monkeypatch, fake)
    fake.presences[1]["do_not_disturb"] = True
    async with test_client_factory(user) as client:
        response = await client.get("/api/v1/pbx/presence")
    assert response.status_code == 200
    body = response.json()
    assert body["live"] is True
    assert body["extensions"]["1001"]["state"] == "on_call"
    assert body["extensions"]["1002"] == {
        "state": "dnd",
        "label": "Ne pas déranger",
        "status": "",
    }


async def _provisioned(db_session, monkeypatch):
    monkeypatch.setattr(
        constants, "PBX_PROVISIONING_URL", "https://pbx.operateur.example"
    )
    monkeypatch.setattr(constants, "PBX_PROVISIONING_USERNAME", "nimbora-provisioning")
    monkeypatch.setattr(constants, "PBX_PROVISIONING_PASSWORD", "operator-secret")
    monkeypatch.setattr(constants, "PBX_PROVISIONING_ARI_ENDPOINT", "")
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
    policy = next(
        p for p in fake.auth_policies if p["name"] == provisioning.POLICY_NAME
    )
    return fake, org, policy


async def test_reprovisioning_brings_an_old_company_policy_up_to_date(
    db_session, monkeypatch
):
    fake, org, policy = await _provisioned(db_session, monkeypatch)
    # Made by an older NIMBORA: no presence rights.
    policy["acl"] = [a for a in policy["acl"] if not a.startswith("chatd.")]

    fake.username, fake.password = "nimbora-provisioning", "operator-secret"
    client_module._TOKENS.clear()
    await provisioning.provision_organization(org.id, transport=fake.transport)

    assert "chatd.users.presences.read" in policy["acl"]
    assert set(policy["acl"]) == set(provisioning.integration_acl())


async def test_an_operator_account_without_the_new_rights_does_not_block(
    db_session, monkeypatch
):
    fake, org, policy = await _provisioned(db_session, monkeypatch)
    policy["acl"] = [a for a in policy["acl"] if not a.startswith("chatd.")]

    original = fake.handle

    def refuse_policy_updates(request):
        if request.method == "PUT" and "/auth/0.1/policies/" in request.url.path:
            import httpx

            return httpx.Response(401, json={"message": "Unauthorized"})
        return original(request)

    fake.handle = refuse_policy_updates
    fake.username, fake.password = "nimbora-provisioning", "operator-secret"
    client_module._TOKENS.clear()
    connection = await provisioning.provision_organization(
        org.id, transport=fake.transport
    )
    assert connection.status == "ok"
    assert "chatd.users.presences.read" not in policy["acl"]
