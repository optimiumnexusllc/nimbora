"""Resellers: one level (platform → resellers → companies).

The platform creates a reseller and invites its administrator; the reseller
builds its own offers on the platform's plans (limits never higher, price never
lower), creates its client companies and invites their owners; each reseller
only ever sees its own companies and offers.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, update

from api.db.models import InvitationModel
from api.services.saas import invitations, subscription_service


@pytest.fixture
def saas_on(monkeypatch):
    monkeypatch.setattr(subscription_service, "SAAS_MODE", True)
    monkeypatch.setattr(subscription_service, "SAAS_TRIAL_DAYS", 14)
    monkeypatch.setattr(subscription_service, "SAAS_DEFAULT_PLAN", "starter")
    from api.routes import auth as auth_routes
    from api.routes import reseller as reseller_routes
    from api.routes import saas as saas_routes
    from api.services.saas import limits

    for module in (limits, saas_routes, reseller_routes, auth_routes):
        monkeypatch.setattr(module, "SAAS_MODE", True)
    monkeypatch.setattr(auth_routes, "ENABLE_SIGNUP", True)


async def _user(db, *, superuser=False):
    user = await db.create_user_with_email(
        email=f"{uuid.uuid4().hex[:10]}@example.com", password_hash="x"
    )
    if superuser:
        user.is_superuser = True
    return user


@pytest.fixture
def as_user(test_client_factory):
    """A client for ``user``; for a superuser, the admin routes accept it too
    (get_superuser calls get_user directly, not through Depends)."""
    from contextlib import asynccontextmanager

    from fastapi import HTTPException

    from api.app import app
    from api.services.auth.depends import get_superuser

    @asynccontextmanager
    async def client_for(user):
        async with test_client_factory(user) as client:

            def superuser_or_403():
                if not user.is_superuser:
                    raise HTTPException(status_code=403, detail="Superuser only")
                return user

            app.dependency_overrides[get_superuser] = superuser_or_403
            try:
                yield client
            finally:
                app.dependency_overrides.pop(get_superuser, None)

    return client_for


def _token(url: str) -> str:
    return url.rsplit("/", 1)[1]


async def _reseller(client, name="Acme Télécom", commission=20):
    response = await client.post(
        "/api/v1/saas/admin/resellers",
        json={
            "name": name,
            "contact_email": "contact@acme.example",
            "commission_percent": commission,
            "admin_email": f"{uuid.uuid4().hex[:8]}@acme.example",
            "admin_name": "Awa Koné",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _accept(client, url: str, password="motdepasse-solide", name=None):
    return await client.post(
        f"/api/v1/auth/invitations/{_token(url)}/accept",
        json={"password": password, **({"name": name} if name else {})},
    )


async def _admin_of_new_reseller(db, as_user, **kwargs):
    root = await _user(db, superuser=True)
    async with as_user(root) as client:
        created = await _reseller(client, **kwargs)
        accepted = await _accept(client, created["invitation_url"])
    assert accepted.status_code == 200, accepted.text
    admin = await db.get_user_by_id(accepted.json()["user"]["id"])
    return created["reseller"], admin


# ------------------------------------------------------------- the platform


async def test_platform_creates_a_reseller_and_invites_its_admin(
    db_session, saas_on, as_user
):
    root = await _user(db_session, superuser=True)
    async with as_user(root) as client:
        created = await _reseller(client, commission=17.5)
        assert created["reseller"]["commission_percent"] == 17.5
        assert created["invitation_url"].startswith("http")
        token = _token(created["invitation_url"])

        seen = (await client.get(f"/api/v1/auth/invitations/{token}")).json()
        assert seen["kind"] == "reseller_admin"
        assert seen["target_name"] == "Acme Télécom"
        assert seen["existing_account"] is False

        accepted = await _accept(client, created["invitation_url"], name="Awa")
        assert accepted.status_code == 200
        assert accepted.json()["token"]
        # One use only.
        again = await _accept(client, created["invitation_url"])
        assert again.status_code == 410

        listed = (await client.get("/api/v1/saas/admin/resellers")).json()
        assert [r["name"] for r in listed] == ["Acme Télécom"]
        assert listed[0]["companies"] == 0

        patched = await client.patch(
            f"/api/v1/saas/admin/resellers/{created['reseller']['id']}",
            json={"commission_percent": 25, "is_active": True},
        )
        assert patched.json()["commission_percent"] == 25

    # Only the token's hash is stored.
    async with db_session.async_session() as session:
        rows = (await session.execute(select(InvitationModel))).scalars().all()
    assert rows and all(token != r.token_hash for r in rows)


@pytest.mark.parametrize("commission", [-1, 100.5])
async def test_commission_is_a_percentage(db_session, saas_on, as_user, commission):
    root = await _user(db_session, superuser=True)
    async with as_user(root) as client:
        response = await client.post(
            "/api/v1/saas/admin/resellers",
            json={
                "name": "X",
                "commission_percent": commission,
                "admin_email": "a@x.example",
            },
        )
    assert response.status_code == 422


async def test_only_the_platform_manages_resellers(db_session, saas_on, as_user):
    user = await _user(db_session)
    async with as_user(user) as client:
        assert (await client.get("/api/v1/saas/admin/resellers")).status_code == 403
        assert (await client.get("/api/v1/reseller")).status_code == 403


# ------------------------------------------------------------ their offers


async def test_reseller_offers_stay_within_the_platform_plan(
    db_session, saas_on, as_user
):
    reseller, admin = await _admin_of_new_reseller(db_session, as_user)
    await subscription_service.ensure_default_plans()
    async with as_user(admin) as client:
        me = (await client.get("/api/v1/reseller")).json()
        assert me["name"] == "Acme Télécom" and me["commission_percent"] == 20
        bases = (await client.get("/api/v1/reseller/base-plans")).json()
        assert {"starter", "business"} <= {b["code"] for b in bases}

        offer = {
            "base_plan_code": "starter",
            "name": "Acme Essentiel",
            "description": "Pour les TPE",
            "monthly_price_cents": 12900,
            "limits": {"included_minutes": 800},
            "features": {},
        }
        created = await client.post("/api/v1/reseller/plans", json=offer)
        assert created.status_code == 201, created.text
        plan = created.json()
        assert plan["name"] == "Acme Essentiel" and plan["is_public"] is False
        assert plan["included_minutes"] == 800
        assert plan["code"].startswith(f"r{reseller['id']}-")

        too_cheap = await client.post(
            "/api/v1/reseller/plans", json={**offer, "monthly_price_cents": 100}
        )
        assert too_cheap.status_code == 422
        too_much = await client.post(
            "/api/v1/reseller/plans",
            json={**offer, "limits": {"included_minutes": 999999}},
        )
        assert too_much.status_code == 422
        unlimited = await client.post(
            "/api/v1/reseller/plans",
            json={**offer, "limits": {"included_minutes": None}},
        )
        assert unlimited.status_code == 422
        extra_feature = await client.post(
            "/api/v1/reseller/plans",
            json={**offer, "features": {"pbx_dedicated": True}},
        )
        assert extra_feature.status_code == 422

        updated = await client.put(
            f"/api/v1/reseller/plans/{plan['code']}",
            json={**offer, "name": "Acme Essentiel+", "monthly_price_cents": 14900},
        )
        assert (
            updated.status_code == 200 and updated.json()["name"] == "Acme Essentiel+"
        )
        mine = (await client.get("/api/v1/reseller/plans")).json()
        assert [p["code"] for p in mine] == [plan["code"]]

    # Never in the public price list.
    async with as_user(await _user(db_session)) as client:
        public = (await client.get("/api/v1/saas/plans")).json()
    assert plan["code"] not in {p["code"] for p in public}


# ---------------------------------------------------------- their companies


async def _offer(client, base="starter"):
    response = await client.post(
        "/api/v1/reseller/plans",
        json={
            "base_plan_code": base,
            "name": f"Offre {uuid.uuid4().hex[:4]}",
            "monthly_price_cents": 50000,
            "limits": {},
            "features": {},
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["code"]


async def test_reseller_creates_a_company_and_its_owner_joins(
    db_session, saas_on, as_user
):
    await subscription_service.ensure_default_plans()
    reseller, admin = await _admin_of_new_reseller(db_session, as_user)
    async with as_user(admin) as client:
        code = await _offer(client)
        created = await client.post(
            "/api/v1/reseller/companies",
            json={
                "company_name": "Boulangerie Diallo",
                "owner_email": "fatou@diallo.example",
                "owner_name": "Fatou Diallo",
                "plan_code": code,
            },
        )
        assert created.status_code == 201, created.text
        company = created.json()["company"]
        assert company["plan_code"] == code and company["status"] == "trialing"
        url = created.json()["invitation_url"]

        listed = (await client.get("/api/v1/reseller/companies")).json()
        assert [c["company_name"] for c in listed] == ["Boulangerie Diallo"]

    async with as_user(admin) as client:
        accepted = await _accept(client, url, name="Fatou")
    assert accepted.status_code == 200, accepted.text
    owner = await db_session.get_user_by_id(accepted.json()["user"]["id"])
    org_id = company["organization_id"]
    assert accepted.json()["user"]["organization_id"] == org_id
    assert await db_session.is_user_member_of_organization(owner.id, org_id)
    org = await db_session.get_organization_by_id(org_id)
    assert org.reseller_id == reseller["id"]

    # The owner's company cannot pay the platform directly.
    owner.selected_organization_id = org_id
    async with as_user(owner) as client:
        checkout = await client.post(
            "/api/v1/saas/checkout", json={"plan_code": "business"}
        )
    assert checkout.status_code == 409
    assert "revendeur" in checkout.json()["detail"]


async def test_reseller_changes_plan_and_suspends_its_company(
    db_session, saas_on, as_user
):
    await subscription_service.ensure_default_plans()
    _, admin = await _admin_of_new_reseller(db_session, as_user)
    async with as_user(admin) as client:
        first, second = await _offer(client), await _offer(client, "business")
        company = (
            await client.post(
                "/api/v1/reseller/companies",
                json={
                    "company_name": "Garage Koffi",
                    "owner_email": "koffi@garage.example",
                    "plan_code": first,
                },
            )
        ).json()["company"]
        org_id = company["organization_id"]
        moved = await client.patch(
            f"/api/v1/reseller/companies/{org_id}",
            json={"plan_code": second, "status": "suspended"},
        )
        assert moved.status_code == 200, moved.text
        assert moved.json()["plan_code"] == second
        assert moved.json()["status"] == "suspended"
        # Never a platform plan: that would leave the reseller's billing.
        platform = await client.patch(
            f"/api/v1/reseller/companies/{org_id}", json={"plan_code": "enterprise"}
        )
        assert platform.status_code == 404


async def test_resellers_never_see_each_other(db_session, saas_on, as_user):
    await subscription_service.ensure_default_plans()
    _, admin_a = await _admin_of_new_reseller(db_session, as_user, name="A")
    _, admin_b = await _admin_of_new_reseller(db_session, as_user, name="B")
    async with as_user(admin_a) as client:
        code_a = await _offer(client)
        org_a = (
            await client.post(
                "/api/v1/reseller/companies",
                json={
                    "company_name": "Client de A",
                    "owner_email": "x@a.example",
                    "plan_code": code_a,
                },
            )
        ).json()["company"]["organization_id"]
    async with as_user(admin_b) as client:
        assert (await client.get("/api/v1/reseller/companies")).json() == []
        assert (await client.get("/api/v1/reseller/plans")).json() == []
        assert (
            await client.patch(
                f"/api/v1/reseller/companies/{org_a}", json={"status": "suspended"}
            )
        ).status_code == 404
        assert (
            await client.put(
                f"/api/v1/reseller/plans/{code_a}",
                json={
                    "base_plan_code": "starter",
                    "name": "volé",
                    "monthly_price_cents": 99999,
                    "limits": {},
                    "features": {},
                },
            )
        ).status_code == 404
        # B cannot put its company on A's offer either.
        stolen = await client.post(
            "/api/v1/reseller/companies",
            json={
                "company_name": "Client de B",
                "owner_email": "y@b.example",
                "plan_code": code_a,
            },
        )
        assert stolen.status_code == 404


async def test_an_inactive_reseller_loses_its_console(db_session, saas_on, as_user):
    reseller, admin = await _admin_of_new_reseller(db_session, as_user)
    root = await _user(db_session, superuser=True)
    async with as_user(root) as client:
        await client.patch(
            f"/api/v1/saas/admin/resellers/{reseller['id']}",
            json={"is_active": False},
        )
    async with as_user(admin) as client:
        assert (await client.get("/api/v1/reseller")).status_code == 403


# -------------------------------------------------------------- invitations


async def test_invitation_expires_and_existing_accounts_prove_their_password(
    db_session, saas_on, as_user
):
    from api.utils.auth import hash_password

    root = await _user(db_session, superuser=True)
    existing = await db_session.create_user_with_email(
        email="deja@client.example", password_hash=hash_password("ancien-mot-de-passe")
    )
    async with as_user(root) as client:
        created = await _reseller(client)
        invite = await client.post(
            f"/api/v1/saas/admin/resellers/{created['reseller']['id']}/invitations",
            json={"email": "deja@client.example"},
        )
        url = invite.json()["invitation_url"]
        seen = (await client.get(f"/api/v1/auth/invitations/{_token(url)}")).json()
        assert seen["existing_account"] is True
        wrong = await _accept(client, url, password="pas-le-bon")
        assert wrong.status_code == 401
        right = await _accept(client, url, password="ancien-mot-de-passe")
        assert right.status_code == 200
        assert right.json()["user"]["id"] == existing.id

        expired = await client.post(
            f"/api/v1/saas/admin/resellers/{created['reseller']['id']}/invitations",
            json={"email": "tard@client.example"},
        )
        async with db_session.async_session() as session:
            await session.execute(
                update(InvitationModel)
                .where(
                    InvitationModel.token_hash
                    == invitations.digest(_token(expired.json()["invitation_url"]))
                )
                .values(expires_at=datetime.now(UTC) - timedelta(minutes=1))
            )
            await session.commit()
        late = await _accept(client, expired.json()["invitation_url"])
        assert late.status_code == 410
        unknown = await client.get("/api/v1/auth/invitations/nimporte-quoi")
        assert unknown.status_code == 404


def test_tokens_are_hashed_and_long():
    token, digest = invitations.new_token()
    assert len(token) >= 40 and digest == invitations.digest(token)
    assert token not in digest
    assert InvitationModel.__tablename__ == "invitations"
    assert invitations.EXPIRY == timedelta(days=7)
    assert datetime.now(UTC) + invitations.EXPIRY > datetime.now(UTC)
