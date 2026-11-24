"""The reseller's console: its offers and its client companies.

Every route acts on the caller's own reseller (``reseller_of``): a reseller
never sees another one's companies or offers. 404 unless SAAS_MODE is on.
"""

from datetime import datetime
from typing import Literal

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr, Field

from api.constants import SAAS_MODE, UI_APP_URL
from api.db import db_client
from api.db.models import ResellerModel, SubscriptionPlanModel, UserModel
from api.services.auth.depends import get_user
from api.services.saas import resellers, stripe_billing
from api.services.saas.plans import LIMIT_FIELDS


async def require_saas_mode() -> None:
    if not SAAS_MODE:
        raise HTTPException(status_code=404, detail="Not found")


router = APIRouter(
    prefix="/reseller", tags=["reseller"], dependencies=[Depends(require_saas_mode)]
)


async def current_reseller(user: UserModel = Depends(get_user)) -> ResellerModel:
    try:
        return await resellers.reseller_of(user)
    except resellers.ResellerError as error:
        raise HTTPException(status_code=error.status, detail=str(error))


def _fail(error: resellers.ResellerError):
    raise HTTPException(status_code=error.status, detail=str(error))


# --------------------------------------------------------------------- schemas


class ResellerInfo(BaseModel):
    id: int
    name: str
    commission_percent: float
    stripe_ready: bool
    companies: int


class ResellerPlan(BaseModel):
    code: str
    name: str
    description: str | None
    currency: str
    monthly_price_cents: int
    base_plan_code: str | None
    included_minutes: int | None
    included_human_minutes: int | None
    max_concurrent_calls: int | None
    max_agents: int | None
    max_human_seats: int | None
    max_campaigns: int | None
    features: dict[str, bool]
    is_public: bool


class OfferRequest(BaseModel):
    base_plan_code: str
    name: str = Field(min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=1000)
    monthly_price_cents: int = Field(ge=0)
    limits: dict[
        Literal[
            "included_minutes",
            "included_human_minutes",
            "max_concurrent_calls",
            "max_agents",
            "max_human_seats",
            "max_campaigns",
        ],
        int | None,
    ] = {}
    features: dict[str, bool] = {}


class Company(BaseModel):
    organization_id: int
    company_name: str | None
    billing_email: str | None
    plan_code: str | None
    plan_name: str | None
    status: str | None
    trial_ends_at: datetime | None
    created_at: datetime | None


class CompanyRequest(BaseModel):
    company_name: str = Field(min_length=1, max_length=255)
    owner_email: EmailStr
    owner_name: str | None = Field(default=None, max_length=255)
    plan_code: str


class CompanyCreated(BaseModel):
    company: Company
    invitation_url: str


class CompanyUpdate(BaseModel):
    plan_code: str | None = None
    status: Literal["trialing", "active", "suspended"] | None = None


class InvitationRequest(BaseModel):
    email: EmailStr
    name: str | None = Field(default=None, max_length=255)


class InvitationLink(BaseModel):
    invitation_url: str


async def _plan(plan: SubscriptionPlanModel) -> ResellerPlan:
    base = (
        await db_client.get_subscription_plan_by_id(plan.base_plan_id)
        if plan.base_plan_id
        else None
    )
    return ResellerPlan(
        code=plan.code,
        name=plan.name,
        description=plan.description,
        currency=plan.currency,
        monthly_price_cents=plan.monthly_price_cents,
        base_plan_code=base.code if base else None,
        **{field: getattr(plan, field) for field in LIMIT_FIELDS},
        features={k: bool(v) for k, v in (plan.features or {}).items()},
        is_public=plan.is_public,
    )


async def _companies(reseller: ResellerModel) -> list[Company]:
    rows = await db_client.list_reseller_companies(reseller.id)
    return [
        Company(
            organization_id=org.id,
            company_name=sub.company_name if sub else None,
            billing_email=sub.billing_email if sub else None,
            plan_code=sub.plan.code if sub else None,
            plan_name=sub.plan.name if sub else None,
            status=sub.status if sub else None,
            trial_ends_at=sub.trial_ends_at if sub else None,
            created_at=org.created_at,
        )
        for org, sub in rows
    ]


async def _company(reseller: ResellerModel, organization_id: int) -> Company:
    return next(
        c for c in await _companies(reseller) if c.organization_id == organization_id
    )


class StripeState(BaseModel):
    connected: bool
    charges_enabled: bool
    details_submitted: bool


class StripeLink(BaseModel):
    url: str


# ---------------------------------------------------------------------- routes


@router.get("", response_model=ResellerInfo)
async def get_reseller(reseller: ResellerModel = Depends(current_reseller)):
    return ResellerInfo(
        id=reseller.id,
        name=reseller.name,
        commission_percent=resellers.bps_to_percent(reseller.commission_bps),
        stripe_ready=bool(
            reseller.stripe_account_id and reseller.stripe_charges_enabled
        ),
        companies=await db_client.count_reseller_companies(reseller.id),
    )


@router.get("/stripe", response_model=StripeState)
async def get_stripe_state(reseller: ResellerModel = Depends(current_reseller)):
    """Its Stripe account, as Stripe sees it now."""
    if not reseller.stripe_account_id:
        return StripeState(
            connected=False, charges_enabled=False, details_submitted=False
        )
    try:
        account = await stripe_billing.retrieve_account(reseller.stripe_account_id)
    except (httpx.HTTPError, stripe_billing.StripeNotConfigured):
        raise HTTPException(status_code=502, detail="Stripe indisponible")
    charges_enabled = bool(account.get("charges_enabled"))
    if charges_enabled != reseller.stripe_charges_enabled:
        await db_client.set_reseller_stripe(
            reseller.id, reseller.stripe_account_id, charges_enabled
        )
    return StripeState(
        connected=True,
        charges_enabled=charges_enabled,
        details_submitted=bool(account.get("details_submitted")),
    )


@router.post("/stripe/onboarding", response_model=StripeLink)
async def start_stripe_onboarding(reseller: ResellerModel = Depends(current_reseller)):
    """Stripe's page to open (or finish) its Express account."""
    if not stripe_billing.is_configured():
        raise HTTPException(
            status_code=409,
            detail="Le paiement en ligne n'est pas activé sur la plateforme",
        )
    try:
        account_id = reseller.stripe_account_id
        if not account_id:
            account = await stripe_billing.create_express_account(
                reseller_id=reseller.id, email=reseller.contact_email
            )
            account_id = account["id"]
            await db_client.set_reseller_stripe(
                reseller.id, account_id, bool(account.get("charges_enabled"))
            )
        url = await stripe_billing.create_account_link(
            account_id=account_id,
            refresh_url=f"{UI_APP_URL.rstrip('/')}/reseller?stripe=refresh",
            return_url=f"{UI_APP_URL.rstrip('/')}/reseller?stripe=return",
        )
    except httpx.HTTPError:
        raise HTTPException(status_code=502, detail="Stripe indisponible")
    return StripeLink(url=url)


@router.post("/stripe/dashboard", response_model=StripeLink)
async def open_stripe_dashboard(reseller: ResellerModel = Depends(current_reseller)):
    """Its Express dashboard: payments received, payouts."""
    if not reseller.stripe_account_id:
        raise HTTPException(status_code=409, detail="Compte Stripe non connecté")
    try:
        url = await stripe_billing.create_login_link(reseller.stripe_account_id)
    except httpx.HTTPStatusError as error:
        if error.response.status_code == 400:
            # Stripe opens the dashboard only once onboarding is submitted.
            raise HTTPException(
                status_code=409,
                detail="Terminez l'inscription Stripe avant d'ouvrir le tableau de bord",
            )
        raise HTTPException(status_code=502, detail="Stripe indisponible")
    except (httpx.HTTPError, stripe_billing.StripeNotConfigured):
        raise HTTPException(status_code=502, detail="Stripe indisponible")
    return StripeLink(url=url)


@router.get("/base-plans", response_model=list[ResellerPlan])
async def list_base_plans(_: ResellerModel = Depends(current_reseller)):
    """The platform's plans an offer can be built on."""
    return [await _plan(plan) for plan in await db_client.list_platform_plans()]


@router.get("/plans", response_model=list[ResellerPlan])
async def list_offers(reseller: ResellerModel = Depends(current_reseller)):
    return [
        await _plan(plan) for plan in await db_client.list_reseller_plans(reseller.id)
    ]


@router.post("/plans", response_model=ResellerPlan, status_code=201)
async def create_offer(
    request: OfferRequest, reseller: ResellerModel = Depends(current_reseller)
):
    try:
        return await _plan(await resellers.create_offer(reseller, request.model_dump()))
    except resellers.ResellerError as error:
        _fail(error)


@router.put("/plans/{code}", response_model=ResellerPlan)
async def update_offer(
    code: str,
    request: OfferRequest,
    reseller: ResellerModel = Depends(current_reseller),
):
    try:
        return await _plan(
            await resellers.update_offer(reseller, code, request.model_dump())
        )
    except resellers.ResellerError as error:
        _fail(error)


@router.get("/companies", response_model=list[Company])
async def list_companies(reseller: ResellerModel = Depends(current_reseller)):
    return await _companies(reseller)


@router.post("/companies", response_model=CompanyCreated, status_code=201)
async def create_company(
    request: CompanyRequest,
    reseller: ResellerModel = Depends(current_reseller),
    user: UserModel = Depends(get_user),
):
    """The company starts its trial on the offer; the link (shown once) lets
    its owner create an account and join it."""
    try:
        organization_id, url = await resellers.create_company(
            reseller,
            user,
            company_name=request.company_name,
            owner_email=request.owner_email,
            owner_name=request.owner_name,
            plan_code=request.plan_code,
        )
    except resellers.ResellerError as error:
        _fail(error)
    return CompanyCreated(
        company=await _company(reseller, organization_id), invitation_url=url
    )


@router.patch("/companies/{organization_id}", response_model=Company)
async def update_company(
    organization_id: int,
    request: CompanyUpdate,
    reseller: ResellerModel = Depends(current_reseller),
):
    try:
        await resellers.update_company(
            reseller,
            organization_id,
            plan_code=request.plan_code,
            status=request.status,
        )
    except resellers.ResellerError as error:
        _fail(error)
    return await _company(reseller, organization_id)


@router.post("/companies/{organization_id}/invitations", response_model=InvitationLink)
async def invite_to_company(
    organization_id: int,
    request: InvitationRequest,
    reseller: ResellerModel = Depends(current_reseller),
    user: UserModel = Depends(get_user),
):
    """Another person of the company (or a new link for its owner)."""
    from api.services.saas import invitations

    try:
        await resellers.company_of(reseller, organization_id)
    except resellers.ResellerError as error:
        _fail(error)
    url = await invitations.invite(
        kind="company_owner",
        email=request.email,
        name=request.name,
        organization_id=organization_id,
        reseller_id=reseller.id,
        created_by=user.id,
    )
    return InvitationLink(invitation_url=url)
