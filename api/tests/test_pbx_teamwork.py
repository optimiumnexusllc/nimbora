"""Call pickup groups, parking lots, intercoms and outbound route schedules."""

import pytest

from api.services.pbx import teamwork
from api.services.pbx.service import PbxRouteError
from api.tests.pbx_fake import FakePbx
from api.tests.test_pbx_admin import _setup


async def test_pickup_group_members_pick_up_each_other(
    db_session, monkeypatch, test_client_factory
):
    fake = FakePbx()
    user, _, _ = await _setup(db_session, monkeypatch, fake)
    async with test_client_factory(user) as client:
        created = await client.post(
            "/api/v1/pbx/pickup-groups",
            json={"name": "Accueil", "members": ["u-1", "u-2"]},
        )
        listed = await client.get("/api/v1/pbx/pickup-groups")
    assert created.status_code == 201
    assert created.json()["code"] == "*8"
    (group,) = fake.callpickups
    for role in ("interceptors", "targets"):
        assert [u["uuid"] for u in group[role]["users"]] == ["u-1", "u-2"]
    (shown,) = listed.json()
    assert [(m["name"], m["extension"]) for m in shown["members"]] == [
        ("Koffi Yao", "1001"),
        ("Aya Diallo", "1002"),
    ]


async def test_pickup_group_needs_two_known_extensions(db_session, monkeypatch):
    fake = FakePbx()
    _, org, _ = await _setup(db_session, monkeypatch, fake)
    with pytest.raises(PbxRouteError):
        await teamwork.create_pickup_group(
            org.id, teamwork.NewPickupGroup("A", ["u-1"])
        )
    with pytest.raises(PbxRouteError) as error:
        await teamwork.create_pickup_group(
            org.id, teamwork.NewPickupGroup("A", ["u-1", "u-404"])
        )
    assert error.value.status == 422
    assert fake.callpickups == []


async def test_parking_lot_with_its_number_and_slots(
    db_session, monkeypatch, test_client_factory
):
    fake = FakePbx()
    user, org, _ = await _setup(db_session, monkeypatch, fake)
    async with test_client_factory(user) as client:
        bad = await client.post(
            "/api/v1/pbx/parking-lots",
            json={"extension": "705", "slots_start": "701", "slots_end": "720"},
        )
        created = await client.post(
            "/api/v1/pbx/parking-lots",
            json={
                "extension": "700",
                "slots_start": "701",
                "slots_end": "720",
                "timeout": 60,
            },
        )
        listed = (await client.get("/api/v1/pbx/parking-lots")).json()
    assert bad.status_code == 422  # the lot's number inside its slots
    assert created.status_code == 201
    assert listed == [
        {
            "id": created.json()["id"],
            "name": "Parking 700",
            "extension": "700",
            "slots_start": "701",
            "slots_end": "720",
            "timeout": 60,
        }
    ]
    # The Softphone offers it in « Parquer ».
    from api.services.pbx import client as client_module
    from api.tests.pbx_fake import TENANT

    async with client_module.PbxClient(
        client_module.PbxSettings(
            base_url="https://pbx.example",
            username="nimbora",
            password="secret",
            tenant_uuid=TENANT,
        ),
        transport=fake.transport,
    ) as engine:
        assert await teamwork.parking_extensions(engine) == [
            {"name": "Parking 700", "extension": "700"}
        ]
    # Deleting frees the number.
    await teamwork.delete_parking_lot(org.id, created.json()["id"])
    assert fake.parkinglots == []
    assert not [e for e in fake.extensions if e["exten"] == "700"]


async def test_intercom_and_announcement(db_session, monkeypatch, test_client_factory):
    fake = FakePbx()
    user, _, _ = await _setup(db_session, monkeypatch, fake)
    async with test_client_factory(user) as client:
        intercom = await client.post(
            "/api/v1/pbx/pagings",
            json={
                "name": "Bureau du directeur",
                "number": "1",
                "members": ["u-2"],
                "callers": ["u-1"],
            },
        )
        announcement = await client.post(
            "/api/v1/pbx/pagings",
            json={
                "name": "Tout le monde",
                "number": "9",
                "members": ["u-1", "u-2"],
                "duplex": False,
            },
        )
        duplicate = await client.post(
            "/api/v1/pbx/pagings",
            json={"name": "Doublon", "number": "1", "members": ["u-1"]},
        )
        listed = (await client.get("/api/v1/pbx/pagings")).json()
    assert intercom.json()["dial"] == "*111"
    assert announcement.status_code == 201
    assert duplicate.status_code == 409
    # The engine only lets listed callers page: « everyone » is every extension.
    by_number = {p["number"]: p for p in fake.pagings}
    assert [u["uuid"] for u in by_number["1"]["callers"]["users"]] == ["u-1"]
    assert sorted(u["uuid"] for u in by_number["9"]["callers"]["users"]) == sorted(
        u["uuid"] for u in fake.users
    )
    assert [p["callers"] for p in listed if p["number"] == "9"] == [[]]
    kinds = {
        p["number"]: (
            p["kind"],
            [m["extension"] for m in p["members"]],
            [c["extension"] for c in p["callers"]],
        )
        for p in listed
    }
    assert kinds == {
        "1": ("intercom", ["1002"], ["1001"]),
        "9": ("announcement", ["1001", "1002"], []),
    }


async def test_outbound_route_only_during_opening_hours(
    db_session, monkeypatch, test_client_factory
):
    fake = FakePbx()
    user, org, _ = await _setup(db_session, monkeypatch, fake)
    fake.outcalls.append({"id": 5, "name": "Sortie", "trunks": [], "extensions": []})
    async with test_client_factory(user) as client:
        no_hours = await client.put(
            "/api/v1/pbx/outbound-routes/5/hours", json={"opening_hours_only": True}
        )
    assert no_hours.status_code == 409  # « Mon entreprise » has no hours yet

    from api.services.business.profile import BusinessProfile, save_business_profile

    await save_business_profile(
        org.id,
        BusinessProfile(opening_hours={"mon": [{"open": "08:00", "close": "18:00"}]}),
    )
    async with test_client_factory(user) as client:
        on = await client.put(
            "/api/v1/pbx/outbound-routes/5/hours", json={"opening_hours_only": True}
        )
        again = await client.put(
            "/api/v1/pbx/outbound-routes/5/hours", json={"opening_hours_only": True}
        )
        routes = (await client.get("/api/v1/pbx/outbound-routes")).json()["routes"]
        off = await client.put(
            "/api/v1/pbx/outbound-routes/5/hours", json={"opening_hours_only": False}
        )
        missing = await client.put(
            "/api/v1/pbx/outbound-routes/404/hours", json={"opening_hours_only": False}
        )
    assert on.status_code == again.status_code == off.status_code == 200
    (schedule,) = [x for x in fake.schedules if x["name"].endswith(f"sortie-{org.id}")]
    # After hours an outgoing call is refused, never sent to the AI agent.
    assert schedule["closed_destination"] == {"type": "hangup", "cause": "congestion"}
    assert schedule["open_periods"]
    assert next(r for r in routes if r["id"] == 5)["opening_hours_only"] is True
    assert fake.outcalls[-1]["schedules"] == []
    assert missing.status_code == 404


async def test_parked_calls_of_the_company_only(
    db_session, monkeypatch, test_client_factory
):
    """Read from wazo-calld, lot by lot: only the company's own lots exist for
    its token (the AMI action is master-tenant only)."""
    from datetime import datetime, timedelta, timezone

    fake = FakePbx()
    user, org, _ = await _setup(db_session, monkeypatch, fake)
    lot = await teamwork.create_parking_lot(
        org.id, teamwork.NewParkingLot("Accueil", "700", "701", "720")
    )
    parked_at = datetime.now(timezone.utc) - timedelta(seconds=35)
    fake.parked += [
        {
            "lot_id": lot["id"],
            "call_id": "1795367056.124",
            "slot": "702",
            "caller_id_num": "+2250700112233",
            "caller_id_name": "Awa Koné",
            "parker_caller_id_num": "1004",
            "parker_caller_id_name": "Poste 1004",
            "parked_at": parked_at.isoformat(),
            "timeout_at": (parked_at + timedelta(seconds=120)).isoformat(),
        },
        {  # another company's lot: unknown to this tenant
            "lot_id": 999,
            "slot": "702",
            "caller_id_num": "+33100000000",
            "caller_id_name": "<unknown>",
            "parked_at": parked_at.isoformat(),
        },
    ]
    async with test_client_factory(user) as client:
        parked = (await client.get("/api/v1/pbx/parked-calls")).json()
    assert len(parked) == 1
    waiting = parked[0].pop("waiting_seconds")
    assert 34 <= waiting <= 37
    assert parked == [
        {
            "lot": "Accueil",
            "slot": "702",
            "number": "+2250700112233",
            "name": "Awa Koné",
            "parked_by": "1004",
        }
    ]
