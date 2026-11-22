"""The operator's shared PBX: one tenant per company, created by NIMBORA.

Two ways for a company to get an enterprise PBX, chosen by its plan:

* **shared** (``pbx_shared``): NIMBORA creates the company's tenant on the
  operator's PBX — dialplan contexts, a least-privilege service account, the
  AI agents' ARI link — and connects it. The company never sees credentials.
* **dedicated** (``pbx_dedicated``): the company (or the operator for it)
  installs its own PBX with deploy/pbx and connects it from the console.

Provisioning is idempotent: every step looks for what a previous, possibly
interrupted, run already created and only creates what is missing. Nothing is
rolled back on failure; the next run picks up where the last one stopped.

Human seats: one seat = one agent of the built-in contact center or one
extension of the PBX, capped by the plan's ``max_human_seats``.
"""

from __future__ import annotations

import re
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from api import constants
from api.services.pbx.client import REQUIRED_ACL, PbxClient, PbxError, PbxSettings
from api.services.pbx.service import PbxRouteError, new_webhook_token
from loguru import logger

POLICY_NAME = "nimbora-integration"
_RANGE = re.compile(r"^\s*(\d+)\s*-\s*(\d+)\s*$")


class ProvisioningUnavailable(Exception):
    """No shared PBX is configured on this platform."""


# ------------------------------------------------------------------ plan


def _legacy_feature(plan, key: str) -> bool:
    """Plans saved before the PBX flags existed keep working as before.

    Until then any company could connect its own PBX: a plan without the flag
    keeps that right. The shared PBX did not exist: a plan without the flag
    gets the default of the plan of the same code, if any.
    """
    from api.services.saas.plans import DEFAULT_PLANS, FEATURE_PBX_DEDICATED

    if key == FEATURE_PBX_DEDICATED:
        return True
    defaults = DEFAULT_PLANS.get(getattr(plan, "code", "") or "", {})
    return bool((defaults.get("features") or {}).get(key, False))


@dataclass
class PbxAccess:
    shared: bool
    dedicated: bool
    shared_available: bool  # the operator has configured a shared PBX
    seats_limit: int | None
    plan_name: str | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "shared": self.shared,
            "dedicated": self.dedicated,
            "shared_available": self.shared_available,
            "seats_limit": self.seats_limit,
            "plan_name": self.plan_name,
        }


async def pbx_access(organization_id: int) -> PbxAccess:
    shared_available = bool(
        constants.PBX_PROVISIONING_URL and constants.PBX_PROVISIONING_PASSWORD
    )
    if not constants.SAAS_MODE:
        return PbxAccess(True, True, shared_available, None, None)
    from api.services.saas.plans import FEATURE_PBX_DEDICATED, FEATURE_PBX_SHARED
    from api.services.saas.subscription_service import (
        effective_limits,
        ensure_organization_subscription,
    )

    subscription = await ensure_organization_subscription(organization_id)
    plan = subscription.plan
    features = dict(plan.features or {})
    features.update((subscription.limit_overrides or {}).get("features") or {})

    def allowed(key: str) -> bool:
        if key in features:
            return bool(features[key])
        return _legacy_feature(plan, key)

    limits = effective_limits(plan, subscription.limit_overrides)
    return PbxAccess(
        shared=allowed(FEATURE_PBX_SHARED),
        dedicated=allowed(FEATURE_PBX_DEDICATED),
        shared_available=shared_available,
        seats_limit=limits.get("max_human_seats"),
        plan_name=plan.name,
    )


async def assert_dedicated_allowed(organization_id: int) -> None:
    access = await pbx_access(organization_id)
    if not access.dedicated:
        raise PbxRouteError(
            f"Votre offre ({access.plan_name}) ne permet pas de connecter votre propre "
            "PBX. Activez la téléphonie de la plateforme ou changez d'offre.",
            403,
        )


# ----------------------------------------------------------------- seats


async def seats_in_use(organization_id: int, pbx_users: int) -> int:
    from api.db import db_client

    return pbx_users + await db_client.count_contact_center_agents(organization_id)


async def assert_seats_available(
    organization_id: int, *, pbx_users: int, adding: int = 1
) -> None:
    """Refuse to create ``adding`` more PBX extensions beyond the plan."""
    if not constants.SAAS_MODE:
        return
    access = await pbx_access(organization_id)
    if access.seats_limit is None:
        return
    used = await seats_in_use(organization_id, pbx_users)
    if used + adding > access.seats_limit:
        left = max(access.seats_limit - used, 0)
        raise PbxRouteError(
            f"Votre offre ({access.plan_name}) comprend {access.seats_limit} postes "
            f"humains ; {used} sont utilisés"
            + (f", il en reste {left}." if left else ".")
            + " Changez d'offre pour en ajouter.",
            403,
        )


async def seats_left(organization_id: int, **client_kwargs) -> int | None:
    """Extensions the plan still allows (None = unlimited)."""
    if not constants.SAAS_MODE:
        return None
    access = await pbx_access(organization_id)
    if access.seats_limit is None:
        return None
    from api.services.pbx import service

    connection = await service._connection(organization_id)
    async with service.client_for(connection, **client_kwargs) as client:
        pbx_users = len(await client.users())
    return max(access.seats_limit - await seats_in_use(organization_id, pbx_users), 0)


# ---------------------------------------------------------- provisioning


def tenant_slug(organization_id: int) -> str:
    # The engine caps tenant slugs at 10 characters ([A-Za-z0-9_]).
    return f"org{organization_id}"[:10]


def service_username(organization_id: int) -> str:
    return f"nimbora-org{organization_id}"


def integration_acl() -> list[str]:
    """The service account's ACL, derived from what the client calls."""
    acl = {re.sub(r"\{[a-z_]+\}", "*", value) for value in REQUIRED_ACL.values()}
    return sorted(acl)


def _range(value: str) -> list[dict[str, str]]:
    match = _RANGE.match(value or "")
    if not match:
        return []
    start, end = match.groups()
    return [{"start": start, "end": end}]


def _operator_settings(tenant_uuid: str | None = None) -> PbxSettings:
    if not (constants.PBX_PROVISIONING_URL and constants.PBX_PROVISIONING_PASSWORD):
        raise ProvisioningUnavailable()
    return PbxSettings(
        base_url=constants.PBX_PROVISIONING_URL,
        username=constants.PBX_PROVISIONING_USERNAME,
        password=constants.PBX_PROVISIONING_PASSWORD,
        tenant_uuid=tenant_uuid,
        verify_tls=constants.PBX_PROVISIONING_VERIFY_TLS,
    )


async def _company_name(organization_id: int) -> str:
    try:
        from api.services.business.profile import get_business_profile

        name = (await get_business_profile(organization_id)).name.strip()
    except Exception:  # noqa: BLE001 - the name is cosmetic
        name = ""
    return name or f"Entreprise {organization_id}"


async def _ensure_tenant(client: PbxClient, slug: str, name: str) -> dict:
    for tenant in await client.tenants(search=slug):
        if tenant.get("slug") == slug:
            return tenant
    return await client.create_tenant(name=f"{name} (#{slug})"[:128], slug=slug)


def desired_contexts(slug: str, name: str) -> dict[str, dict]:
    """The tenant's three contexts, as validated on a real engine (26.11).

    Same shapes as deploy/pbx/scripts/ensure_tenant_contexts.py: explicit
    names (unique across tenants), and one inbound range per number length
    because the engine wants start and end of the same length.
    """
    return {
        "outcall": {
            "name": f"{slug}-outcall",
            "label": f"{name} — appels sortants"[:128],
            "type": "outcall",
            "enabled": True,
        },
        "incall": {
            "name": f"{slug}-incall",
            "label": f"{name} — appels entrants"[:128],
            "type": "incall",
            "incall_ranges": [
                {"start": "0" * n, "end": "9" * n, "did_length": n}
                for n in range(4, 16)
            ],
            "enabled": True,
        },
        "internal": {
            "name": f"{slug}-internal",
            "label": f"{name} — postes, files et groupes"[:128],
            "type": "internal",
            "user_ranges": _range(constants.PBX_PROVISIONING_USER_RANGE),
            "group_ranges": _range(constants.PBX_PROVISIONING_GROUP_RANGE),
            "queue_ranges": _range(constants.PBX_PROVISIONING_QUEUE_RANGE),
            "conference_room_ranges": _range(
                constants.PBX_PROVISIONING_CONFERENCE_RANGE
            ),
            "enabled": True,
        },
    }


def missing_ranges(context: dict, desired: dict) -> dict[str, list]:
    """Numbering ranges the desired context has and the existing one lacks."""
    return {
        key: value
        for key, value in desired.items()
        if key.endswith("_ranges") and value and not context.get(key)
    }


async def _ensure_contexts(client: PbxClient, slug: str, name: str) -> dict[str, dict]:
    existing: dict[str, dict] = {}
    for context in await client.contexts():
        existing.setdefault(context.get("type"), context)
    for kind, body in desired_contexts(slug, name).items():
        if kind not in existing:
            existing[kind] = await client.create_context(body)
            continue
        # The engine creates default contexts with the tenant, without numbering
        # ranges (seen on 26.11: incall_ranges []). Fill the empty ones only:
        # ranges an operator set by hand are kept.
        missing = missing_ranges(existing[kind], body)
        if missing:
            context = existing[kind]
            await client.update_context(
                context["id"],
                {
                    "name": context.get("name"),
                    "label": context.get("label") or body["label"],
                    "type": context.get("type"),
                    "enabled": context.get("enabled", True),
                    **missing,
                },
            )
            existing[kind] = {**context, **missing}
    # Extensions may dial out: internal includes outcall (keeping other includes).
    internal, outcall = existing["internal"], existing["outcall"]
    includes = [c["id"] for c in internal.get("contexts") or []]
    if outcall["id"] not in includes:
        await client.set_context_includes(internal["id"], [*includes, outcall["id"]])
    return existing


async def _ensure_service_account(client: PbxClient, username: str) -> tuple[str, str]:
    """A fresh password every run: the previous one is never stored readable."""
    policy = next(
        (
            p
            for p in await client.policies(search=POLICY_NAME)
            if p.get("name") == POLICY_NAME
        ),
        None,
    )
    if policy is None:
        policy = await client.create_policy(
            {
                "name": POLICY_NAME,
                "description": "NIMBORA: administration et événements de l'entreprise",
                "acl": integration_acl(),
            }
        )
    for user in await client.auth_users(search=username):
        if user.get("username") == username:
            # Left by an interrupted run: its password is unknown, start over.
            await client.delete_auth_user(user["uuid"])
    password = secrets.token_urlsafe(24)
    user = await client.create_auth_user(
        {
            "username": username,
            "password": password,
            "purpose": "external_api",
            "enabled": True,
        }
    )
    await client.set_auth_user_policy(user["uuid"], policy["uuid"])
    return username, password


async def _ensure_ai_link(organization_id: int, connection, outcall_context: str):
    """ARI configuration for the company's AI agents on the shared PBX."""
    from api.db import db_client
    from api.services.telephony.providers.ari import _preprocess_credentials_on_save

    if connection.ari_configuration_id or not constants.PBX_PROVISIONING_ARI_ENDPOINT:
        return connection.ari_configuration_id
    credentials = await _preprocess_credentials_on_save(
        {
            "ari_endpoint": constants.PBX_PROVISIONING_ARI_ENDPOINT,
            "app_name": constants.PBX_PROVISIONING_ARI_USER,
            "app_password": constants.PBX_PROVISIONING_ARI_PASSWORD,
            "ws_client_name": constants.PBX_PROVISIONING_ARI_WS_CLIENT,
            "dial_string_template": f"Local/{{number}}@{outcall_context}",
            "dial_number_format": "as_is",
        }
    )
    row = await db_client.create_telephony_configuration(
        organization_id,
        name="PBX de la plateforme (agents IA)",
        provider="ari",
        credentials=credentials,
    )
    return row.id


async def provision_organization(
    organization_id: int, *, public_base_url: str | None = None, **client_kwargs
) -> Any:
    """Create (or complete) the company's tenant on the shared PBX."""
    from api.db import db_client
    from api.services.pbx import service

    existing = await db_client.get_pbx_connection(organization_id)
    if existing is not None and not existing.managed:
        raise PbxRouteError(
            "Un PBX est déjà connecté : retirez-le avant d'activer celui de la plateforme.",
            409,
        )
    access = await pbx_access(organization_id)
    if not access.shared:
        raise PbxRouteError(
            f"Votre offre ({access.plan_name}) ne comprend pas la téléphonie de la plateforme.",
            403,
        )
    operator = _operator_settings()
    slug = tenant_slug(organization_id)
    name = await _company_name(organization_id)

    async with PbxClient(operator, **client_kwargs) as client:
        tenant = await _ensure_tenant(client, slug, name)
    in_tenant = _operator_settings(tenant["uuid"])
    async with PbxClient(in_tenant, **client_kwargs) as client:
        contexts = await _ensure_contexts(client, slug, name)
        username, password = await _ensure_service_account(
            client, service_username(organization_id)
        )

    fields: dict[str, Any] = {
        "name": "PBX de la plateforme",
        "base_url": constants.PBX_PROVISIONING_URL,
        "username": username,
        "password": password,
        "tenant_uuid": tenant["uuid"],
        "verify_tls": constants.PBX_PROVISIONING_VERIFY_TLS,
        "incall_context": contexts["incall"].get("name"),
        "managed": True,
        "provisioning": {
            "tenant_slug": slug,
            "tenant_name": tenant.get("name"),
            "contexts": {k: v.get("name") for k, v in contexts.items()},
            "provisioned_at": datetime.now(UTC).isoformat(),
        },
    }
    if existing is None:
        fields["webhook_token"] = new_webhook_token()
    connection = await db_client.save_pbx_connection(organization_id, fields)

    ari_id = await _ensure_ai_link(
        organization_id, connection, contexts["outcall"].get("name") or ""
    )
    if ari_id and ari_id != connection.ari_configuration_id:
        connection = await db_client.save_pbx_connection(
            organization_id, {"ari_configuration_id": ari_id}
        )

    connection = await service.refresh_status(organization_id, **client_kwargs)
    if public_base_url:
        try:
            await service.ensure_webhook(
                organization_id, public_base_url, **client_kwargs
            )
        except PbxError as error:  # the console offers to retry
            logger.warning(
                "PBX events not connected for org {}: {}", organization_id, error
            )
    return await db_client.get_pbx_connection(organization_id)


async def deprovision_organization(organization_id: int, **client_kwargs) -> bool:
    """Delete the company's tenant from the shared PBX (operator action)."""
    from api.db import db_client

    connection = await db_client.get_pbx_connection(organization_id)
    if connection is None or not connection.managed:
        return False
    if connection.tenant_uuid:
        async with PbxClient(_operator_settings(), **client_kwargs) as client:
            try:
                await client.delete_tenant(connection.tenant_uuid)
            except PbxError as error:
                if error.status != 404:
                    raise
    if connection.ari_configuration_id:
        await db_client.delete_telephony_configuration(
            connection.ari_configuration_id, organization_id
        )
    await db_client.delete_pbx_connection(organization_id)
    await db_client.revoke_softphone_devices_for_organization(organization_id)
    return True


async def provision_pbx_tenant(ctx, organization_id: int) -> None:
    """ARQ task: provision right after signup, without slowing it down."""
    try:
        await provision_organization(
            organization_id, public_base_url=constants.BACKEND_API_ENDPOINT
        )
    except (ProvisioningUnavailable, PbxRouteError) as error:
        logger.info("Shared PBX not provisioned for org {}: {}", organization_id, error)
    except PbxError as error:
        logger.warning(
            "Shared PBX provisioning failed for org {}: {}", organization_id, error
        )
