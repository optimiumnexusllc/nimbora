"""One-time invitation links: to administer a reseller, or to own a company a
reseller created. The link carries a random token; only its SHA-256 is stored.
It expires after ``EXPIRY`` and works once. Someone who already has an account
proves it with their password and simply joins.
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from api.constants import UI_APP_URL
from api.db import db_client
from api.db.models import InvitationModel, UserModel
from api.utils.auth import hash_password, verify_password

EXPIRY = timedelta(days=7)


class InvitationError(Exception):
    def __init__(self, message: str, status: int):
        super().__init__(message)
        self.status = status


def digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def new_token() -> tuple[str, str]:
    token = secrets.token_urlsafe(32)
    return token, digest(token)


def url_of(token: str) -> str:
    return f"{UI_APP_URL.rstrip('/')}/auth/invitation/{token}"


async def invite(
    *,
    kind: str,
    email: str,
    name: str | None = None,
    organization_id: int | None = None,
    reseller_id: int | None = None,
    created_by: int | None = None,
) -> str:
    """The link to send to the person (shown once, never stored)."""
    token, token_hash = new_token()
    await db_client.create_invitation(
        kind=kind,
        token_hash=token_hash,
        email=email.strip().lower(),
        name=name,
        organization_id=organization_id,
        reseller_id=reseller_id,
        created_by=created_by,
        expires_at=datetime.now(UTC) + EXPIRY,
    )
    return url_of(token)


@dataclass
class InvitationView:
    invitation: InvitationModel
    target_name: str
    existing_account: bool


async def _usable(token: str) -> InvitationModel:
    invitation = await db_client.get_invitation_by_hash(digest(token))
    if invitation is None:
        raise InvitationError("Invitation introuvable", 404)
    if invitation.accepted_at is not None:
        raise InvitationError("Cette invitation a déjà servi", 410)
    if invitation.expires_at <= datetime.now(UTC):
        raise InvitationError("Cette invitation a expiré : demandez-en une autre", 410)
    return invitation


async def _target_name(invitation: InvitationModel) -> str:
    if invitation.reseller_id and invitation.kind == "reseller_admin":
        reseller = await db_client.get_reseller(invitation.reseller_id)
        return reseller.name if reseller else ""
    if invitation.organization_id:
        subscription = await db_client.get_organization_subscription(
            invitation.organization_id
        )
        return (subscription.company_name if subscription else None) or ""
    return ""


async def describe(token: str) -> InvitationView:
    invitation = await _usable(token)
    return InvitationView(
        invitation=invitation,
        target_name=await _target_name(invitation),
        existing_account=await db_client.get_user_by_email(invitation.email)
        is not None,
    )


async def accept(
    token: str, *, password: str, name: str | None = None
) -> tuple[UserModel, InvitationModel]:
    """Create the account (or check the existing one's password) and join."""
    invitation = await _usable(token)
    user = await db_client.get_user_by_email(invitation.email)
    if user is not None:
        if not user.password_hash or not verify_password(password, user.password_hash):
            raise InvitationError("Mot de passe incorrect pour ce compte", 401)
    if not await db_client.claim_invitation(invitation.id):
        raise InvitationError("Cette invitation a déjà servi", 410)
    if user is None:
        user = await db_client.create_user_with_email(
            email=invitation.email,
            password_hash=hash_password(password),
            name=name or invitation.name,
        )
    if invitation.kind == "reseller_admin" and invitation.reseller_id:
        await db_client.add_reseller_member(invitation.reseller_id, user.id)
    elif invitation.organization_id:
        await db_client.add_user_to_organization(user.id, invitation.organization_id)
        await db_client.update_user_selected_organization(
            user.id, invitation.organization_id
        )
        user.selected_organization_id = invitation.organization_id
    return user, invitation
