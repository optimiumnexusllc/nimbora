"""Subscription and billing endpoints for SaaS operator mode.

Tenant endpoints act on the caller's selected organization only. Admin
endpoints require a superuser. Everything returns 404 unless SAAS_MODE is on,
so a plain self-hosted install exposes nothing new.
"""

from datetime import datetime
from typing import Any, Literal

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from loguru import logger
from pydantic import BaseModel, EmailStr, Field

from api.constants import SAAS_MODE, SAAS_PLATFORM_NAME, UI_APP_URL
from api.db import db_client
from api.db.models import SUBSCRIPTION_STATUSES, SubscriptionPlanModel, UserModel
from api.services.auth.depends import get_superuser, get_user
from api.services.saas import (
    invitations,
    resellers,
    stripe_billing,
    subscription_service,
)
from api.services.saas.plans import ALL_FEATURES, LIMIT_FIELDS


async def require_saas_mode() -> None:
    if not SAAS_MODE:
        raise HTTPException(status_code=404, detail="Not found")


router = APIRouter(
    prefix="/saas", tags=["saas"], dependencies=[Depends(require_saas_mode)]
)


# --------------------------------------------------------------------- schemas
class PlanResponse(BaseModel):
    code: str
    name: str
    description: str | None
    currency: str
    monthly_price_cents: int
    included_minutes: int | None
    overage_price_cents_per_minute: int | None
    included_human_minutes: int | None = None
    human_overage_price_cents_per_minute: int | None = None
    max_concurrent_calls: int | None
    max_agents: int | None
    max_human_seats: int | None
    max_campaigns: int | None
    features: dict[str, bool]
    purchasable: bool
    is_public: bool
    is_active: bool


class SubscriptionResponse(BaseModel):
    platform_name: str
    organization_id: int
    plan_code: str
    plan_name: str
    status: str
    period_start: datetime
    period_end: datetime
    trial_ends_at: datetime | None
    used_minutes: float
    included_minutes: int | None
    remaining_minutes: float | None
    overage_minutes: float
    estimated_overage_cents: int
    human_used_minutes: float = 0.0
    human_included_minutes: int | None = None
    human_remaining_minutes: float | None = None
    human_overage_minutes: float = 0.0
    estimated_human_overage_cents: int = 0
    limits: dict[str, Any]
    features: dict[str, bool]
    usable: bool
    blocked_reason: str | None
    can_manage_billing: bool


class CheckoutRequest(BaseModel):
    plan_code: str


class RedirectResponse(BaseModel):
    url: str


class PlanUpdateRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    monthly_price_cents: int | None = Field(default=None, ge=0)
    included_minutes: int | None = Field(default=None, ge=0)
    overage_price_cents_per_minute: int | None = Field(default=None, ge=0)
    included_human_minutes: int | None = Field(default=None, ge=0)
    human_overage_price_cents_per_minute: int | None = Field(default=None, ge=0)
    max_concurrent_calls: int | None = Field(default=None, ge=1)
    max_agents: int | None = Field(default=None, ge=0)
    max_human_seats: int | None = Field(default=None, ge=0)
    max_campaigns: int | None = Field(default=None, ge=0)
    features: dict[str, bool] | None = None
    stripe_price_id: str | None = None
    is_public: bool | None = None
    is_active: bool | None = None
    sort_order: int | None = None
    # Explicitly listed fields are set to null (= unlimited).
    unlimited: list[
        Literal[
            "included_minutes",
            "included_human_minutes",
            "max_concurrent_calls",
            "max_agents",
            "max_human_seats",
            "max_campaigns",
        ]
    ] = []


class TenantResponse(BaseModel):
    organization_id: int
    company_name: str | None
    billing_email: str | None
    member_emails: list[str]
    plan_code: str
    status: str
    current_period_start: datetime
    current_period_end: datetime
    trial_ends_at: datetime | None
    limit_overrides: dict[str, Any]
    stripe_customer_id: str | None
    notes: str | None
    created_at: datetime | None


class TenantListResponse(BaseModel):
    tenants: list[TenantResponse]
    total: int
    page: int
    limit: int


class TenantUpdateRequest(BaseModel):
    plan_code: str | None = None
    status: Literal[SUBSCRIPTION_STATUSES] | None = None  # type: ignore[valid-type]
    trial_ends_at: datetime | None = None
    limit_overrides: dict[str, Any] | None = None
    company_name: str | None = Field(default=None, max_length=255)
    billing_email: EmailStr | None = None
    notes: str | None = None


# --------------------------------------------------------------------- helpers
def _plan_response(plan: SubscriptionPlanModel) -> PlanResponse:
    return PlanResponse(
        code=plan.code,
        name=plan.name,
        description=plan.description,
        currency=plan.currency,
        monthly_price_cents=plan.monthly_price_cents,
        included_minutes=plan.included_minutes,
        overage_price_cents_per_minute=plan.overage_price_cents_per_minute,
        included_human_minutes=plan.included_human_minutes,
        human_overage_price_cents_per_minute=plan.human_overage_price_cents_per_minute,
        max_concurrent_calls=plan.max_concurrent_calls,
        max_agents=plan.max_agents,
        max_human_seats=plan.max_human_seats,
        max_campaigns=plan.max_campaigns,
        features={k: bool(v) for k, v in (plan.features or {}).items()},
        purchasable=bool(plan.stripe_price_id and stripe_billing.is_configured()),
        is_public=plan.is_public,
        is_active=plan.is_active,
    )


def _require_org(user: UserModel) -> int:
    if not user.selected_organization_id:
        raise HTTPException(status_code=400, detail="No organization selected")
    return user.selected_organization_id


def _validate_overrides(overrides: dict[str, Any]) -> dict[str, Any]:
    clean: dict[str, Any] = {}
    for key, value in overrides.items():
        if key in LIMIT_FIELDS:
            if value is not None and (not isinstance(value, int) or value < 0):
                raise HTTPException(
                    422, f"{key} must be a non-negative integer or null"
                )
            clean[key] = value
        elif key == "features":
            if not isinstance(value, dict) or set(value) - set(ALL_FEATURES):
                raise HTTPException(422, f"features keys must be among {ALL_FEATURES}")
            clean[key] = {k: bool(v) for k, v in value.items()}
        else:
            raise HTTPException(422, f"Unknown override: {key}")
    return clean


# -------------------------------------------------------------- tenant routes
@router.get("/plans", response_model=list[PlanResponse])
async def list_public_plans():
    """Public price list (no authentication), for a pricing page."""
    await subscription_service.ensure_default_plans()
    plans = await db_client.list_subscription_plans(public_only=True)
    return [_plan_response(plan) for plan in plans]


@router.get("/subscription", response_model=SubscriptionResponse)
async def get_my_subscription(user: UserModel = Depends(get_user)):
    organization_id = _require_org(user)
    summary = await subscription_service.get_usage_summary(organization_id)
    subscription = await db_client.get_organization_subscription(organization_id)
    return SubscriptionResponse(
        platform_name=SAAS_PLATFORM_NAME,
        organization_id=organization_id,
        plan_code=summary.plan_code,
        plan_name=summary.plan_name,
        status=summary.status,
        period_start=summary.period_start,
        period_end=summary.period_end,
        trial_ends_at=summary.trial_ends_at,
        used_minutes=summary.used_minutes,
        included_minutes=summary.included_minutes,
        remaining_minutes=summary.remaining_minutes,
        overage_minutes=summary.overage_minutes,
        estimated_overage_cents=summary.estimated_overage_cents,
        human_used_minutes=summary.human_used_minutes,
        human_included_minutes=summary.human_included_minutes,
        human_remaining_minutes=summary.human_remaining_minutes,
        human_overage_minutes=summary.human_overage_minutes,
        estimated_human_overage_cents=summary.estimated_human_overage_cents,
        limits=summary.limits,
        features=summary.features,
        usable=summary.usable,
        blocked_reason=summary.blocked_reason,
        can_manage_billing=bool(
            stripe_billing.is_configured()
            and subscription is not None
            and subscription.stripe_customer_id
        ),
    )


@router.post("/checkout", response_model=RedirectResponse)
async def start_checkout(request: CheckoutRequest, user: UserModel = Depends(get_user)):
    organization_id = _require_org(user)
    organization = await db_client.get_organization_by_id(organization_id)
    if organization is not None and organization.reseller_id is not None:
        return await _reseller_checkout(organization, request.plan_code, user)
    if not stripe_billing.is_configured():
        raise HTTPException(
            status_code=409,
            detail="Online payment is not enabled. Contact the platform operator.",
        )
    plan = await db_client.get_subscription_plan_by_code(request.plan_code)
    if plan is None or not plan.is_active or not plan.is_public:
        raise HTTPException(status_code=404, detail="Plan not found")
    if not plan.stripe_price_id:
        raise HTTPException(
            status_code=409, detail="This plan cannot be purchased online."
        )
    subscription = await subscription_service.ensure_organization_subscription(
        organization_id
    )
    try:
        url = await stripe_billing.create_checkout_session(
            organization_id=organization_id,
            plan_code=plan.code,
            price_id=plan.stripe_price_id,
            success_url=f"{UI_APP_URL}/subscription?checkout=success",
            cancel_url=f"{UI_APP_URL}/subscription?checkout=cancel",
            customer_id=subscription.stripe_customer_id,
            customer_email=subscription.billing_email or user.email,
        )
    except httpx.HTTPError:
        raise HTTPException(status_code=502, detail="Payment provider unavailable")
    return RedirectResponse(url=url)


async def _reseller_checkout(organization, plan_code: str, user: UserModel):
    """A reseller's company pays online for one of its reseller's offers,
    through the reseller's Stripe Connect account (the platform keeps its
    commission)."""
    reseller = await db_client.get_reseller(organization.reseller_id)
    if (
        reseller is None
        or not stripe_billing.is_configured()
        or not (reseller.stripe_account_id and reseller.stripe_charges_enabled)
    ):
        raise HTTPException(
            status_code=409,
            detail="Le paiement en ligne de votre revendeur n'est pas encore activé : contactez-le.",
        )
    plan = await db_client.get_reseller_plan(reseller.id, plan_code)
    if plan is None or not plan.is_active:
        raise HTTPException(status_code=404, detail="Plan not found")
    subscription = await subscription_service.ensure_organization_subscription(
        organization.id
    )
    try:
        url = await stripe_billing.create_reseller_checkout_session(
            organization_id=organization.id,
            plan_code=plan.code,
            plan_name=plan.name,
            currency=plan.currency,
            monthly_price_cents=plan.monthly_price_cents,
            account_id=reseller.stripe_account_id,
            commission_percent=resellers.bps_to_percent(reseller.commission_bps),
            success_url=f"{UI_APP_URL}/subscription?checkout=success",
            cancel_url=f"{UI_APP_URL}/subscription?checkout=cancel",
            customer_id=subscription.stripe_customer_id,
            customer_email=subscription.billing_email or user.email,
        )
    except httpx.HTTPError:
        raise HTTPException(status_code=502, detail="Payment provider unavailable")
    return RedirectResponse(url=url)


@router.get("/subscription/plans", response_model=list[PlanResponse])
async def list_my_plans(user: UserModel = Depends(get_user)):
    """The offers this company can subscribe to: its reseller's, or the
    platform's public price list for a direct customer."""
    organization_id = _require_org(user)
    organization = await db_client.get_organization_by_id(organization_id)
    if organization is not None and organization.reseller_id is not None:
        plans = await db_client.list_reseller_plans(organization.reseller_id)
        return [_plan_response(plan) for plan in plans if plan.is_active]
    await subscription_service.ensure_default_plans()
    plans = await db_client.list_subscription_plans(public_only=True)
    return [_plan_response(plan) for plan in plans]


@router.post("/portal", response_model=RedirectResponse)
async def open_billing_portal(user: UserModel = Depends(get_user)):
    organization_id = _require_org(user)
    subscription = await db_client.get_organization_subscription(organization_id)
    if (
        not stripe_billing.is_configured()
        or subscription is None
        or not subscription.stripe_customer_id
    ):
        raise HTTPException(status_code=409, detail="No online billing account")
    try:
        url = await stripe_billing.create_portal_session(
            customer_id=subscription.stripe_customer_id,
            return_url=f"{UI_APP_URL}/subscription",
        )
    except httpx.HTTPError:
        raise HTTPException(status_code=502, detail="Payment provider unavailable")
    return RedirectResponse(url=url)


@router.post("/stripe/webhook", include_in_schema=False)
async def stripe_webhook(
    request: Request,
    stripe_signature: str = Header(default="", alias="Stripe-Signature"),
):
    payload = await request.body()
    try:
        stripe_billing.verify_webhook_signature(payload, stripe_signature)
    except stripe_billing.StripeSignatureError as exc:
        logger.warning("Rejected Stripe webhook: {}", exc)
        raise HTTPException(status_code=400, detail="Invalid signature")
    event = await request.json()
    outcome = await stripe_billing.handle_event(event)
    return {"received": True, "outcome": outcome}


# --------------------------------------------------------------- resellers


class ResellerResponse(BaseModel):
    id: int
    name: str
    contact_email: str | None
    commission_percent: float
    is_active: bool
    stripe_ready: bool
    companies: int


class ResellerCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    contact_email: EmailStr | None = None
    commission_percent: float = Field(ge=0, le=100)
    admin_email: EmailStr
    admin_name: str | None = Field(default=None, max_length=255)


class ResellerCreated(BaseModel):
    reseller: ResellerResponse
    invitation_url: str


class ResellerUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    contact_email: EmailStr | None = None
    commission_percent: float | None = Field(default=None, ge=0, le=100)
    is_active: bool | None = None


class ResellerInvitationRequest(BaseModel):
    email: EmailStr
    name: str | None = Field(default=None, max_length=255)


class ResellerInvitation(BaseModel):
    invitation_url: str


def _reseller_response(reseller, companies: int) -> ResellerResponse:
    return ResellerResponse(
        id=reseller.id,
        name=reseller.name,
        contact_email=reseller.contact_email,
        commission_percent=resellers.bps_to_percent(reseller.commission_bps),
        is_active=reseller.is_active,
        stripe_ready=bool(
            reseller.stripe_account_id and reseller.stripe_charges_enabled
        ),
        companies=companies,
    )


@router.get("/admin/resellers", response_model=list[ResellerResponse])
async def admin_list_resellers(_: UserModel = Depends(get_superuser)):
    return [
        _reseller_response(reseller, count)
        for reseller, count in await db_client.list_resellers_with_counts()
    ]


@router.post("/admin/resellers", response_model=ResellerCreated, status_code=201)
async def admin_create_reseller(
    request: ResellerCreateRequest, user: UserModel = Depends(get_superuser)
):
    """The reseller, and the link (shown once) for its first administrator."""
    reseller = await db_client.create_reseller(
        name=request.name.strip(),
        contact_email=request.contact_email,
        commission_bps=resellers.percent_to_bps(request.commission_percent),
    )
    url = await invitations.invite(
        kind="reseller_admin",
        email=request.admin_email,
        name=request.admin_name,
        reseller_id=reseller.id,
        created_by=user.id,
    )
    return ResellerCreated(reseller=_reseller_response(reseller, 0), invitation_url=url)


@router.patch("/admin/resellers/{reseller_id}", response_model=ResellerResponse)
async def admin_update_reseller(
    reseller_id: int,
    request: ResellerUpdateRequest,
    _: UserModel = Depends(get_superuser),
):
    fields = request.model_dump(exclude_unset=True)
    if "commission_percent" in fields:
        percent = fields.pop("commission_percent")
        if percent is not None:
            fields["commission_bps"] = resellers.percent_to_bps(percent)
    reseller = await db_client.update_reseller(reseller_id, fields)
    if reseller is None:
        raise HTTPException(status_code=404, detail="Reseller not found")
    return _reseller_response(
        reseller, await db_client.count_reseller_companies(reseller_id)
    )


@router.post(
    "/admin/resellers/{reseller_id}/invitations", response_model=ResellerInvitation
)
async def admin_invite_reseller_admin(
    reseller_id: int,
    request: ResellerInvitationRequest,
    user: UserModel = Depends(get_superuser),
):
    if await db_client.get_reseller(reseller_id) is None:
        raise HTTPException(status_code=404, detail="Reseller not found")
    url = await invitations.invite(
        kind="reseller_admin",
        email=request.email,
        name=request.name,
        reseller_id=reseller_id,
        created_by=user.id,
    )
    return ResellerInvitation(invitation_url=url)


# --------------------------------------------------------------- admin routes
@router.get("/admin/plans", response_model=list[PlanResponse])
async def admin_list_plans(_: UserModel = Depends(get_superuser)):
    await subscription_service.ensure_default_plans()
    plans = await db_client.list_subscription_plans(include_inactive=True)
    return [_plan_response(plan) for plan in plans]


@router.put("/admin/plans/{code}", response_model=PlanResponse)
async def admin_upsert_plan(
    code: str, request: PlanUpdateRequest, _: UserModel = Depends(get_superuser)
):
    if not code.replace("-", "").replace("_", "").isalnum() or len(code) > 64:
        raise HTTPException(422, "Plan code must be alphanumeric (with - or _)")
    fields = request.model_dump(exclude_unset=True, exclude={"unlimited"})
    fields = {k: v for k, v in fields.items() if v is not None}
    for name in request.unlimited:
        fields[name] = None
    if "features" in fields and set(fields["features"]) - set(ALL_FEATURES):
        raise HTTPException(422, f"features keys must be among {ALL_FEATURES}")
    existing = await db_client.get_subscription_plan_by_code(code)
    if existing is None and "name" not in fields:
        raise HTTPException(422, "A new plan needs a name")
    plan = await db_client.upsert_subscription_plan(code, fields)
    return _plan_response(plan)


@router.get("/admin/tenants", response_model=TenantListResponse)
async def admin_list_tenants(
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    status: str | None = Query(None),
    _: UserModel = Depends(get_superuser),
):
    # Organizations created before SAAS_MODE was switched on get a subscription
    # the first time an operator lists tenants.
    for organization_id in await db_client.list_organizations_without_subscription():
        await subscription_service.ensure_organization_subscription(organization_id)
    rows, total = await db_client.list_organization_subscriptions(
        limit=limit, offset=(page - 1) * limit, status=status
    )
    emails = await db_client.list_organization_member_emails(
        [row.organization_id for row in rows]
    )
    return TenantListResponse(
        tenants=[
            TenantResponse(
                organization_id=row.organization_id,
                company_name=row.company_name,
                billing_email=row.billing_email,
                member_emails=emails.get(row.organization_id, []),
                plan_code=row.plan.code,
                status=row.status,
                current_period_start=row.current_period_start,
                current_period_end=row.current_period_end,
                trial_ends_at=row.trial_ends_at,
                limit_overrides=row.limit_overrides or {},
                stripe_customer_id=row.stripe_customer_id,
                notes=row.notes,
                created_at=row.created_at,
            )
            for row in rows
        ],
        total=total,
        page=page,
        limit=limit,
    )


@router.get(
    "/admin/tenants/{organization_id}/usage", response_model=SubscriptionResponse
)
async def admin_tenant_usage(
    organization_id: int, _: UserModel = Depends(get_superuser)
):
    if await db_client.get_organization_by_id(organization_id) is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    summary = await subscription_service.get_usage_summary(organization_id)
    subscription = await db_client.get_organization_subscription(organization_id)
    return SubscriptionResponse(
        platform_name=SAAS_PLATFORM_NAME,
        organization_id=organization_id,
        can_manage_billing=bool(subscription and subscription.stripe_customer_id),
        **{
            k: getattr(summary, k)
            for k in SubscriptionResponse.model_fields
            if k not in {"platform_name", "organization_id", "can_manage_billing"}
        },
    )


@router.get("/admin/usage")
async def admin_monthly_usage(
    month: str = Query(..., pattern=r"^\d{4}-\d{2}$", description="AAAA-MM"),
    format: Literal["json", "csv"] = Query("json"),
    _: UserModel = Depends(get_superuser),
):
    """AI and human minutes of every company for one calendar month."""
    from dataclasses import asdict

    from fastapi import Response

    from api.services.saas import usage_report

    try:
        lines = await usage_report.monthly_usage(month)
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    if format == "csv":
        return Response(
            content=usage_report.to_csv(lines),
            media_type="text/csv; charset=utf-8",
            headers={
                "Content-Disposition": f'attachment; filename="consommation-{month}.csv"'
            },
        )
    return {"month": month, "lines": [asdict(line) for line in lines]}


@router.post("/admin/tenants/{organization_id}/pbx/provision")
async def admin_provision_pbx(
    organization_id: int, _: UserModel = Depends(get_superuser)
) -> dict[str, Any]:
    """Create (or complete) the company's tenant on the shared PBX."""
    from api.constants import BACKEND_API_ENDPOINT
    from api.services.pbx import provisioning
    from api.services.pbx.client import PbxError
    from api.services.pbx.service import PbxRouteError

    if await db_client.get_organization_by_id(organization_id) is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    try:
        connection = await provisioning.provision_organization(
            organization_id, public_base_url=BACKEND_API_ENDPOINT
        )
    except provisioning.ProvisioningUnavailable as error:
        raise HTTPException(
            404, "No shared PBX configured (PBX_PROVISIONING_URL)"
        ) from error
    except PbxRouteError as error:
        raise HTTPException(error.status, str(error)) from error
    except PbxError as error:
        raise HTTPException(502, f"PBX: {error}") from error
    return {
        "tenant_uuid": connection.tenant_uuid,
        "status": connection.status,
        "provisioning": connection.provisioning,
    }


@router.delete("/admin/tenants/{organization_id}/pbx", status_code=204)
async def admin_deprovision_pbx(
    organization_id: int, _: UserModel = Depends(get_superuser)
):
    """Delete the company's tenant from the shared PBX (irreversible)."""
    from fastapi import Response

    from api.services.pbx import provisioning
    from api.services.pbx.client import PbxError

    try:
        removed = await provisioning.deprovision_organization(organization_id)
    except PbxError as error:
        raise HTTPException(502, f"PBX: {error}") from error
    if not removed:
        raise HTTPException(404, "No platform-managed PBX for this organization")
    return Response(status_code=204)


@router.patch("/admin/tenants/{organization_id}", response_model=TenantResponse)
async def admin_update_tenant(
    organization_id: int,
    request: TenantUpdateRequest,
    _: UserModel = Depends(get_superuser),
):
    if await db_client.get_organization_by_id(organization_id) is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    subscription = await subscription_service.ensure_organization_subscription(
        organization_id
    )
    if request.plan_code:
        plan = await db_client.get_subscription_plan_by_code(request.plan_code)
        if plan is None:
            raise HTTPException(status_code=404, detail="Plan not found")
        subscription = await subscription_service.change_plan(
            organization_id, plan, status=request.status
        )
    fields: dict[str, Any] = request.model_dump(
        exclude_unset=True, exclude={"plan_code"}
    )
    if "limit_overrides" in fields:
        fields["limit_overrides"] = _validate_overrides(fields["limit_overrides"] or {})
    if fields.get("status") == "past_due" and subscription.past_due_since is None:
        fields["past_due_since"] = subscription_service.utcnow()
    elif "status" in fields and fields["status"] != "past_due":
        fields["past_due_since"] = None
    updated = await db_client.update_organization_subscription(organization_id, fields)
    assert updated is not None
    if "limit_overrides" in fields:
        await subscription_service.sync_concurrency_limit(organization_id, updated)
    emails = await db_client.list_organization_member_emails([organization_id])
    return TenantResponse(
        organization_id=organization_id,
        company_name=updated.company_name,
        billing_email=updated.billing_email,
        member_emails=emails.get(organization_id, []),
        plan_code=updated.plan.code,
        status=updated.status,
        current_period_start=updated.current_period_start,
        current_period_end=updated.current_period_end,
        trial_ends_at=updated.trial_ends_at,
        limit_overrides=updated.limit_overrides or {},
        stripe_customer_id=updated.stripe_customer_id,
        notes=updated.notes,
        created_at=updated.created_at,
    )
