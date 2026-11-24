from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.constants import ENABLE_SIGNUP, SAAS_MODE
from api.db import db_client
from api.db.models import UserModel
from api.enums import PostHogEvent
from api.schemas.auth import AuthResponse, LoginRequest, SignupRequest, UserResponse
from api.services.auth.depends import get_user, require_local_auth
from api.services.organization_bootstrap import ensure_organization_bootstrapped
from api.services.posthog_client import capture_event
from api.services.posthog_tenant import tenant_properties
from api.utils.auth import create_jwt_token, hash_password, verify_password

router = APIRouter(
    prefix="/auth",
    tags=["auth"],
)


@router.post(
    "/signup",
    response_model=AuthResponse,
    dependencies=[Depends(require_local_auth)],
)
async def signup(request: SignupRequest):
    if not ENABLE_SIGNUP:
        raise HTTPException(status_code=403, detail="Signup is disabled")

    # Check if email is already taken
    existing_user = await db_client.get_user_by_email(request.email)
    if existing_user:
        raise HTTPException(status_code=409, detail="Email already registered")

    # Hash password and create user
    hashed = hash_password(request.password)
    user = await db_client.create_user_with_email(
        email=request.email,
        password_hash=hashed,
        name=request.name,
    )

    # Create organization for the user
    org_provider_id = f"org_{user.provider_id}"
    organization, _ = await db_client.get_or_create_organization_by_provider_id(
        org_provider_id=org_provider_id, user_id=user.id
    )

    # Link user to organization
    await db_client.add_user_to_organization(user.id, organization.id)
    await db_client.update_user_selected_organization(user.id, organization.id)

    await _start_company(organization.id, user, billing_email=request.email)

    # Create JWT token
    token = create_jwt_token(user.id, request.email)

    capture_event(
        distinct_id=str(user.provider_id),
        event=PostHogEvent.SIGNED_UP,
        properties={
            **await tenant_properties(organization.id),
            "auth_provider": "local",
        },
    )

    return AuthResponse(
        token=token,
        user=UserResponse(
            id=user.id,
            email=user.email,
            name=getattr(user, "name", None),
            organization_id=organization.id,
            provider_id=user.provider_id,
        ),
    )


async def _start_company(
    organization_id: int, user: UserModel, *, billing_email: str
) -> None:
    """What a new company needs from its first user: default configuration,
    then (SaaS) its subscription and its tenant on the shared PBX."""

    # Create default service configuration. This never raises, so signup still
    # succeeds if MPS is down; `_handle_oss_auth` re-enters bootstrap on the
    # user's subsequent authenticated requests, so a failure here is recovered
    # rather than permanent. Doing it here anyway means the common case has a
    # model configuration and SIP connectivity by the time the UI first loads.
    await ensure_organization_bootstrapped(
        organization_id,
        created_by=user.provider_id,
    )

    if SAAS_MODE:
        # Start the tenant's trial on the default plan right away so limits
        # (concurrency, minutes) apply from the very first call.
        from api.services.saas.subscription_service import (
            ensure_organization_subscription,
        )

        await ensure_organization_subscription(
            organization_id, billing_email=billing_email
        )
        from api.constants import PBX_PROVISIONING_ON_SIGNUP, PBX_PROVISIONING_URL

        if PBX_PROVISIONING_ON_SIGNUP and PBX_PROVISIONING_URL:
            # The company's tenant on the shared PBX, created in the background.
            from api.tasks.arq import enqueue_job
            from api.tasks.function_names import FunctionNames

            try:
                await enqueue_job(FunctionNames.PROVISION_PBX_TENANT, organization_id)
            except Exception:  # noqa: BLE001 - never fail a signup on this
                from loguru import logger

                logger.opt(exception=True).warning(
                    "Could not enqueue PBX provisioning for org {}", organization_id
                )


# ----------------------------------------------------------------- invitations


class InvitationInfo(BaseModel):
    kind: str
    email: str
    name: str | None
    target_name: str
    existing_account: bool
    expires_at: datetime


class InvitationAccept(BaseModel):
    password: str = Field(min_length=8, max_length=200)
    name: str | None = Field(default=None, max_length=255)


@router.get(
    "/invitations/{token}",
    response_model=InvitationInfo,
    dependencies=[Depends(require_local_auth)],
)
async def read_invitation(token: str):
    """Who is invited, to what, and whether they already have an account."""
    from api.services.saas import invitations

    try:
        view = await invitations.describe(token)
    except invitations.InvitationError as error:
        raise HTTPException(status_code=error.status, detail=str(error))
    return InvitationInfo(
        kind=view.invitation.kind,
        email=view.invitation.email,
        name=view.invitation.name,
        target_name=view.target_name,
        existing_account=view.existing_account,
        expires_at=view.invitation.expires_at,
    )


@router.post(
    "/invitations/{token}/accept",
    response_model=AuthResponse,
    dependencies=[Depends(require_local_auth)],
)
async def accept_invitation(token: str, request: InvitationAccept):
    """Create the account (or sign in to the existing one) and join."""
    from api.services.saas import invitations

    try:
        user, invitation = await invitations.accept(
            token, password=request.password, name=request.name
        )
    except invitations.InvitationError as error:
        raise HTTPException(status_code=error.status, detail=str(error))
    if invitation.kind == "company_owner" and invitation.organization_id:
        await _start_company(
            invitation.organization_id, user, billing_email=invitation.email
        )
    return AuthResponse(
        token=create_jwt_token(user.id, user.email),
        user=UserResponse(
            id=user.id,
            email=user.email,
            name=getattr(user, "name", None),
            organization_id=invitation.organization_id or user.selected_organization_id,
            provider_id=user.provider_id,
        ),
    )


@router.post(
    "/login",
    response_model=AuthResponse,
    dependencies=[Depends(require_local_auth)],
)
async def login(request: LoginRequest):
    # Look up user by email
    user = await db_client.get_user_by_email(request.email)
    if not user or not user.password_hash:
        raise HTTPException(status_code=401, detail="Invalid email or password")

    # Verify password
    if not verify_password(request.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    # Create JWT token
    token = create_jwt_token(user.id, user.email)

    capture_event(
        distinct_id=str(user.provider_id),
        event=PostHogEvent.SIGNED_IN,
        properties={
            **await tenant_properties(user.selected_organization_id),
            "auth_provider": "local",
        },
    )

    return AuthResponse(
        token=token,
        user=UserResponse(
            id=user.id,
            email=user.email,
            name=getattr(user, "name", None),
            organization_id=user.selected_organization_id,
            provider_id=user.provider_id,
        ),
    )


@router.get("/me", response_model=UserResponse)
async def get_current_user(user: UserModel = Depends(get_user)):
    return UserResponse(
        id=user.id,
        email=user.email,
        name=getattr(user, "name", None),
        organization_id=user.selected_organization_id,
        provider_id=user.provider_id,
    )
