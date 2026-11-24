"""Resellers' rules: their offers and their client companies.

An offer is built on a platform plan: its own name, description and price,
limits and features never above the base (the platform's costs follow the
base), price never below it (the platform is paid a share of the price).
A company belongs to one reseller and can only be on that reseller's offers.
"""

from __future__ import annotations

import re
import secrets
import uuid
from datetime import timedelta
from typing import Any

from api.db import db_client
from api.db.models import ResellerModel, SubscriptionPlanModel, UserModel
from api.services.saas import invitations, subscription_service
from api.services.saas.plans import ALL_FEATURES, LIMIT_FIELDS

COMPANY_STATUSES = ("trialing", "active", "suspended")


class ResellerError(Exception):
    def __init__(self, message: str, status: int):
        super().__init__(message)
        self.status = status


def percent_to_bps(percent: float) -> int:
    return round(percent * 100)


def bps_to_percent(bps: int) -> float:
    return bps / 100


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:24] or "offre"


# ---------------------------------------------------------------- offers


def _offer_fields(
    base: SubscriptionPlanModel,
    *,
    name: str,
    description: str | None,
    monthly_price_cents: int,
    limits: dict[str, Any],
    features: dict[str, bool],
) -> dict[str, Any]:
    if monthly_price_cents < base.monthly_price_cents:
        raise ResellerError(
            f"Prix trop bas : au moins {base.monthly_price_cents / 100:.2f} "
            f"{base.currency.upper()} par mois (offre « {base.name} »)",
            422,
        )
    fields: dict[str, Any] = {
        "name": name.strip()[:128],
        "description": description,
        "currency": base.currency,
        "monthly_price_cents": monthly_price_cents,
        "overage_price_cents_per_minute": base.overage_price_cents_per_minute,
        "human_overage_price_cents_per_minute": base.human_overage_price_cents_per_minute,
        "base_plan_id": base.id,
    }
    for field in LIMIT_FIELDS:
        ceiling = getattr(base, field)
        value = limits.get(field, ceiling)
        if ceiling is not None and (value is None or value > ceiling):
            raise ResellerError(
                f"{field} : au plus {ceiling} avec l'offre « {base.name} »", 422
            )
        if value is not None and value < 0:
            raise ResellerError(f"{field} : valeur négative", 422)
        fields[field] = value
    # The base's features, switched on or off one by one; never one it lacks.
    allowed = {f for f in ALL_FEATURES if (base.features or {}).get(f)}
    wanted = set(allowed)
    for feature, on in features.items():
        if feature not in ALL_FEATURES:
            raise ResellerError(f"Fonction inconnue : {feature}", 422)
        if on:
            wanted.add(feature)
        else:
            wanted.discard(feature)
    if wanted - allowed:
        raise ResellerError(
            "Fonctions absentes de l'offre de base : "
            + ", ".join(sorted(wanted - allowed)),
            422,
        )
    fields["features"] = {f: f in wanted for f in ALL_FEATURES}
    return fields


async def _base_plan(code: str) -> SubscriptionPlanModel:
    plan = await db_client.get_subscription_plan_by_code(code)
    if plan is None or plan.reseller_id is not None or not plan.is_active:
        raise ResellerError("Offre de base introuvable", 404)
    return plan


async def create_offer(
    reseller: ResellerModel, spec: dict[str, Any]
) -> SubscriptionPlanModel:
    base = await _base_plan(spec["base_plan_code"])
    fields = _offer_fields(
        base,
        name=spec["name"],
        description=spec.get("description"),
        monthly_price_cents=spec["monthly_price_cents"],
        limits=spec.get("limits") or {},
        features=spec.get("features") or {},
    )
    code = f"r{reseller.id}-{_slug(spec['name'])}-{secrets.token_hex(2)}"
    return await db_client.create_reseller_plan(reseller.id, code, fields)


async def update_offer(
    reseller: ResellerModel, code: str, spec: dict[str, Any]
) -> SubscriptionPlanModel:
    if await db_client.get_reseller_plan(reseller.id, code) is None:
        raise ResellerError("Offre introuvable", 404)
    base = await _base_plan(spec["base_plan_code"])
    fields = _offer_fields(
        base,
        name=spec["name"],
        description=spec.get("description"),
        monthly_price_cents=spec["monthly_price_cents"],
        limits=spec.get("limits") or {},
        features=spec.get("features") or {},
    )
    plan = await db_client.update_reseller_plan(reseller.id, code, fields)
    assert plan is not None
    return plan


async def _offer_of(reseller: ResellerModel, code: str) -> SubscriptionPlanModel:
    plan = await db_client.get_reseller_plan(reseller.id, code)
    if plan is None or not plan.is_active:
        raise ResellerError("Offre introuvable", 404)
    return plan


# -------------------------------------------------------------- companies


async def create_company(
    reseller: ResellerModel,
    admin: UserModel,
    *,
    company_name: str,
    owner_email: str,
    owner_name: str | None,
    plan_code: str,
) -> tuple[int, str]:
    """The company (trial on the offer) and the link for its owner."""
    plan = await _offer_of(reseller, plan_code)
    organization, _ = await db_client.get_or_create_organization_by_provider_id(
        org_provider_id=f"reseller_{reseller.id}_{uuid.uuid4().hex}",
        user_id=admin.id,
    )
    await db_client.set_organization_reseller(organization.id, reseller.id)
    now = subscription_service.utcnow()
    trial_days = subscription_service.SAAS_TRIAL_DAYS
    trial_ends_at = now + timedelta(days=trial_days) if trial_days else None
    await db_client.create_organization_subscription_if_missing(
        organization_id=organization.id,
        plan_id=plan.id,
        status="trialing" if trial_ends_at else "active",
        current_period_start=now,
        current_period_end=subscription_service.add_months(now, 1),
        trial_ends_at=trial_ends_at,
        billing_email=owner_email,
    )
    await db_client.update_organization_subscription(
        organization.id, {"company_name": company_name.strip()[:255]}
    )
    subscription = await db_client.get_organization_subscription(organization.id)
    await subscription_service.sync_concurrency_limit(organization.id, subscription)
    url = await invitations.invite(
        kind="company_owner",
        email=owner_email,
        name=owner_name,
        organization_id=organization.id,
        reseller_id=reseller.id,
        created_by=admin.id,
    )
    return organization.id, url


async def company_of(reseller: ResellerModel, organization_id: int) -> int:
    if await db_client.get_reseller_company(reseller.id, organization_id) is None:
        raise ResellerError("Entreprise introuvable", 404)
    return organization_id


async def update_company(
    reseller: ResellerModel,
    organization_id: int,
    *,
    plan_code: str | None = None,
    status: str | None = None,
) -> None:
    await company_of(reseller, organization_id)
    fields: dict[str, Any] = {}
    if plan_code is not None:
        fields["plan_id"] = (await _offer_of(reseller, plan_code)).id
    if status is not None:
        if status not in COMPANY_STATUSES:
            raise ResellerError("Statut inconnu", 422)
        fields["status"] = status
    if fields:
        await db_client.update_organization_subscription(organization_id, fields)
        subscription = await db_client.get_organization_subscription(organization_id)
        await subscription_service.sync_concurrency_limit(organization_id, subscription)


async def reseller_of(user: UserModel) -> ResellerModel:
    reseller = await db_client.get_active_reseller_of_user(user.id)
    if reseller is None:
        raise ResellerError("Réservé aux revendeurs", 403)
    return reseller
