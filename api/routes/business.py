"""Company card (business profile) and industry templates."""

import asyncio

from fastapi import APIRouter, Depends, HTTPException
from loguru import logger
from pydantic import BaseModel, Field

from api.db.models import UserModel
from api.services.auth.depends import get_user
from api.services.business.profile import (
    SKILL_LABELS,
    BusinessProfile,
    get_business_profile,
    opening_status,
    render_business_prompt,
    save_business_profile,
)
from api.services.business.templates import (
    TEMPLATES,
    apply_template_to_profile,
    get_template,
)

router = APIRouter(prefix="/business", tags=["business"])


def _org(user: UserModel) -> int:
    if not user.selected_organization_id:
        raise HTTPException(status_code=400, detail="No organization selected")
    return user.selected_organization_id


class SkillInfo(BaseModel):
    id: str
    label: str


class ProfilePreview(BaseModel):
    prompt: str | None = Field(
        description="Section added to every agent's prompt (null when empty or off)."
    )
    opening_status: str | None
    characters: int


class TemplateSummary(BaseModel):
    id: str
    sector: str
    sector_label: str
    label: str
    description: str
    icon: str
    activity: str
    method: list[str]
    rules: list[str] = Field(description="Non-negotiable rules given to the agent.")
    recommendations: list[str] = Field(description="Set-up advice for the company.")
    collects: list[str]
    dispositions: list[str]
    skills: list[str]
    tools: list[str]
    example_offers: list[dict[str, str]]
    example_faq: list[dict[str, str]]
    example_policies: list[dict[str, str]]


class ApplyTemplateRequest(BaseModel):
    with_examples: bool = Field(
        default=False,
        description="Fill empty offers, FAQ and policies with examples to adapt.",
    )


class CreateAgentRequest(BaseModel):
    name: str | None = Field(default=None, max_length=255)
    attach_tools: bool = True


class CreateAgentResponse(BaseModel):
    workflow_id: int
    name: str
    missing_tools: list[str] = Field(
        description="Suggested tool categories the company has not set up yet."
    )


@router.get("/profile", response_model=BusinessProfile)
async def read_profile(user: UserModel = Depends(get_user)):
    return await get_business_profile(_org(user))


@router.put("/profile", response_model=BusinessProfile)
async def update_profile(profile: BusinessProfile, user: UserModel = Depends(get_user)):
    organization_id = _org(user)
    before = await get_business_profile(organization_id)
    saved = await save_business_profile(organization_id, profile)
    await _refresh_pbx_hours(organization_id, before, saved)
    return saved


async def _refresh_pbx_hours(organization_id: int, before, after) -> None:
    """New hours reach the PBX schedules already in place (numbers and
    outbound routes) without re-applying them by hand. Never blocks the save:
    a PBX that does not answer keeps its previous hours until the next change
    or a manual « Appliquer »."""
    from api.services.pbx.admin import refresh_schedules, schedule_from_profile

    if schedule_from_profile(before) == schedule_from_profile(after):
        return
    try:
        refreshed = await asyncio.wait_for(refresh_schedules(organization_id), 20)
        if refreshed:
            logger.info(
                f"[PBX org={organization_id}] hours refreshed: {', '.join(refreshed)}"
            )
    except Exception as error:  # noqa: BLE001 - the card is saved regardless
        logger.warning(
            f"[PBX org={organization_id}] hours not refreshed on the PBX: {error}"
        )


@router.post("/profile/preview", response_model=ProfilePreview)
async def preview_profile(
    profile: BusinessProfile, user: UserModel = Depends(get_user)
):
    """What the agents will read, for a card being edited (not saved)."""
    _org(user)
    prompt = render_business_prompt(profile)
    return ProfilePreview(
        prompt=prompt,
        opening_status=opening_status(profile),
        characters=len(prompt or ""),
    )


@router.get("/skills", response_model=list[SkillInfo])
async def list_skills(user: UserModel = Depends(get_user)):
    return [SkillInfo(id=k, label=v) for k, v in SKILL_LABELS.items()]


@router.get("/templates", response_model=list[TemplateSummary])
async def list_templates(user: UserModel = Depends(get_user)):
    return [TemplateSummary(**t.summary()) for t in TEMPLATES.values()]


@router.post("/templates/{template_id}/apply", response_model=BusinessProfile)
async def apply_template(
    template_id: str,
    request: ApplyTemplateRequest,
    user: UserModel = Depends(get_user),
):
    """Set the company's trade: its skills, and example content if asked."""
    template = get_template(template_id)
    if template is None:
        raise HTTPException(status_code=404, detail="Template not found")
    organization_id = _org(user)
    profile = apply_template_to_profile(
        await get_business_profile(organization_id),
        template,
        with_examples=request.with_examples,
    )
    return await save_business_profile(organization_id, profile)


@router.post("/templates/{template_id}/agent", response_model=CreateAgentResponse)
async def create_agent(
    template_id: str,
    request: CreateAgentRequest,
    user: UserModel = Depends(get_user),
):
    """Create a ready agent for the trade, reading the company card."""
    from api.services.business.service import create_agent_from_template
    from api.services.saas.limits import PlanLimitExceeded

    template = get_template(template_id)
    if template is None:
        raise HTTPException(status_code=404, detail="Template not found")
    try:
        workflow, missing = await create_agent_from_template(
            organization_id=_org(user),
            user_id=user.id,
            template=template,
            name=(request.name or "").strip() or None,
            attach_tools=request.attach_tools,
        )
    except PlanLimitExceeded as error:
        raise HTTPException(status_code=403, detail=str(error)) from error
    return CreateAgentResponse(
        workflow_id=workflow.id, name=workflow.name, missing_tools=missing
    )
