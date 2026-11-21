"""Customer memory: profiles the agents remember, per organization."""

from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from api.db import db_client
from api.db.models import UserModel
from api.services.auth.depends import get_user
from api.services.customer_memory.service import (
    SETTING_KEY,
    is_memory_enabled,
    normalize_phone,
    phone_suffix,
    profile_to_dict,
)

router = APIRouter(prefix="/customers", tags=["customers"])


class CustomerResponse(BaseModel):
    id: int
    phone: str
    name: Optional[str]
    notes: Optional[str]
    tags: list[str]
    attributes: dict[str, Any]
    last_summary: Optional[str]
    last_sentiment: Optional[str]
    total_calls: int
    first_seen_at: Optional[datetime]
    last_seen_at: Optional[datetime]


class InteractionResponse(BaseModel):
    id: int
    workflow_run_id: Optional[int]
    direction: Optional[str]
    agent_name: Optional[str]
    summary: Optional[str]
    sentiment: Optional[str]
    outcome: Optional[str]
    transferred_to_queue: Optional[str]
    duration_seconds: Optional[int]
    channel: Optional[str] = None
    created_at: Optional[datetime]


class CustomerDetailResponse(CustomerResponse):
    interactions: list[InteractionResponse]


class CustomerListResponse(BaseModel):
    customers: list[CustomerResponse]
    total: int
    memory_enabled: bool


class CustomerCreateRequest(BaseModel):
    phone: str
    name: Optional[str] = Field(default=None, max_length=128)
    notes: Optional[str] = Field(default=None, max_length=4000)
    tags: list[str] = Field(default_factory=list, max_length=20)


class CustomerUpdateRequest(BaseModel):
    name: Optional[str] = Field(default=None, max_length=128)
    notes: Optional[str] = Field(default=None, max_length=4000)
    tags: Optional[list[str]] = Field(default=None, max_length=20)
    attributes: Optional[dict[str, Any]] = None


class MemorySettings(BaseModel):
    enabled: bool


def _org(user: UserModel) -> int:
    if not user.selected_organization_id:
        raise HTTPException(status_code=400, detail="No organization selected")
    return user.selected_organization_id


def _clean_tags(tags: list[str]) -> list[str]:
    seen: dict[str, None] = {}
    for tag in tags:
        tag = " ".join(str(tag).split())[:32]
        if tag:
            seen.setdefault(tag, None)
    return list(seen)


@router.get("", response_model=CustomerListResponse)
async def list_customers(
    q: Optional[str] = Query(default=None, max_length=100),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    user: UserModel = Depends(get_user),
):
    organization_id = _org(user)
    rows, total = await db_client.search_customer_profiles(
        organization_id, query=q, limit=limit, offset=(page - 1) * limit
    )
    return CustomerListResponse(
        customers=[CustomerResponse(**profile_to_dict(p)) for p in rows],
        total=total,
        memory_enabled=await is_memory_enabled(organization_id),
    )


@router.get("/settings", response_model=MemorySettings)
async def get_memory_settings(user: UserModel = Depends(get_user)):
    return MemorySettings(enabled=await is_memory_enabled(_org(user)))


@router.put("/settings", response_model=MemorySettings)
async def update_memory_settings(
    request: MemorySettings, user: UserModel = Depends(get_user)
):
    await db_client.upsert_configuration(
        _org(user), SETTING_KEY, {"enabled": request.enabled}
    )
    return request


@router.post("", response_model=CustomerResponse, status_code=201)
async def create_customer(
    request: CustomerCreateRequest, user: UserModel = Depends(get_user)
):
    organization_id = _org(user)
    phone = normalize_phone(request.phone)
    if not phone:
        raise HTTPException(status_code=422, detail="Invalid phone number")
    profile = await db_client.get_or_create_customer_profile(
        organization_id, phone, phone_suffix(phone)
    )
    fields: dict[str, Any] = {"tags": _clean_tags(request.tags)}
    if request.name:
        fields["name"] = request.name.strip()
    if request.notes:
        fields["notes"] = request.notes
    profile = await db_client.update_customer_profile(
        organization_id, profile.id, fields
    )
    return CustomerResponse(**profile_to_dict(profile))


class IdentitySecretResponse(BaseModel):
    secret: str
    algorithm: str = "HMAC-SHA256(secret, customer_phone in E.164)"


@router.get("/identity", response_model=IdentitySecretResponse)
async def read_identity_secret(user: UserModel = Depends(get_user)):
    """Secret your backend uses to sign the logged-in customer's phone for the
    web chat widget (cross-channel history without spoofing)."""
    from api.services.customer_memory.identity import get_identity_secret

    organization_id = _org(user)
    return IdentitySecretResponse(
        secret=await get_identity_secret(organization_id, create=True)
    )


@router.post("/identity/rotate", response_model=IdentitySecretResponse)
async def rotate_identity(user: UserModel = Depends(get_user)):
    from api.services.customer_memory.identity import rotate_identity_secret

    organization_id = _org(user)
    return IdentitySecretResponse(secret=await rotate_identity_secret(organization_id))


@router.get("/{customer_id}", response_model=CustomerDetailResponse)
async def get_customer(customer_id: int, user: UserModel = Depends(get_user)):
    organization_id = _org(user)
    profile = await db_client.get_customer_profile(organization_id, customer_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="Customer not found")
    interactions = await db_client.list_customer_interactions(
        organization_id, customer_id, limit=50
    )
    return CustomerDetailResponse(
        **profile_to_dict(profile),
        interactions=[
            InteractionResponse(
                id=i.id,
                workflow_run_id=i.workflow_run_id,
                direction=i.direction,
                agent_name=i.agent_name,
                summary=i.summary,
                sentiment=i.sentiment,
                outcome=i.outcome,
                transferred_to_queue=i.transferred_to_queue,
                duration_seconds=i.duration_seconds,
                channel=i.channel,
                created_at=i.created_at,
            )
            for i in interactions
        ],
    )


@router.patch("/{customer_id}", response_model=CustomerResponse)
async def update_customer(
    customer_id: int,
    request: CustomerUpdateRequest,
    user: UserModel = Depends(get_user),
):
    organization_id = _org(user)
    fields = request.model_dump(exclude_unset=True)
    if "tags" in fields:
        fields["tags"] = _clean_tags(fields["tags"] or [])
    if "attributes" in fields:
        attributes = fields["attributes"] or {}
        if len(attributes) > 50 or any(
            not isinstance(v, (str, int, float, bool)) for v in attributes.values()
        ):
            raise HTTPException(422, "attributes: up to 50 simple values")
    profile = await db_client.update_customer_profile(
        organization_id, customer_id, fields
    )
    if profile is None:
        raise HTTPException(status_code=404, detail="Customer not found")
    return CustomerResponse(**profile_to_dict(profile))


@router.delete("/{customer_id}", status_code=204)
async def forget_customer(customer_id: int, user: UserModel = Depends(get_user)):
    """Right to be forgotten: erase the profile and its whole history."""
    if not await db_client.delete_customer_profile(_org(user), customer_id):
        raise HTTPException(status_code=404, detail="Customer not found")
