"""Business profile at run time, and agents created from industry templates."""

from __future__ import annotations

from typing import Any

from loguru import logger

from api.services.business.profile import (
    PROMPT_KEY,
    business_variables,
    get_business_profile,
    render_business_prompt,
)
from api.services.business.templates import (
    IndustryTemplate,
    build_agent_definition,
)


def _opted_out(workflow_run) -> bool:
    definition = getattr(workflow_run, "definition", None)
    configurations = getattr(definition, "workflow_configurations", None) or {}
    return configurations.get("use_business_profile") is False


async def load_business_context(
    organization_id: int | None, workflow_run_id: int | None
) -> dict[str, Any]:
    """``business_profile`` (prompt section) and ``business`` (variables).

    Empty when the company has no card, disabled it, or this agent's pinned
    version opted out. Never raises: an agent without its card still works.
    """
    if not organization_id:
        return {}
    try:
        profile = await get_business_profile(organization_id)
        section = render_business_prompt(profile)
        if section is None:
            return {}
        if workflow_run_id:
            from api.db import db_client

            run = await db_client.get_workflow_run(
                workflow_run_id, organization_id=organization_id
            )
            if run is not None and _opted_out(run):
                return {}
        return {PROMPT_KEY: section, "business": business_variables(profile)}
    except Exception:
        logger.opt(exception=True).warning("Business profile unavailable")
        return {}


async def business_prompt_for_definition(
    organization_id: int | None, workflow_configurations: dict | None
) -> tuple[str | None, dict[str, str]]:
    """(section, variables) as an agent version reads them (previews, caches)."""
    if not organization_id:
        return None, {}
    if (workflow_configurations or {}).get("use_business_profile") is False:
        return None, {}
    try:
        profile = await get_business_profile(organization_id)
        section = render_business_prompt(profile)
        return section, business_variables(profile) if section else {}
    except Exception:
        logger.opt(exception=True).warning("Business profile unavailable")
        return None, {}


def business_section_for_prompt(
    business_profile: str | None, *prompts: str | None
) -> str | None:
    """The section to append, unless a prompt already places it itself."""
    if not business_profile:
        return None
    if any(p and PROMPT_KEY in p for p in prompts):
        return None
    return business_profile


async def attachable_tools(
    organization_id: int, template: IndustryTemplate
) -> tuple[list[str], list[str]]:
    """(uuids of the company's active tools in the template's categories,
    categories the company has no tool for yet)."""
    from api.db import db_client

    tools = await db_client.get_tools_for_organization(organization_id, status="active")
    uuids: list[str] = []
    found: set[str] = set()
    for category in template.tools:
        for tool in tools:
            if tool.category == category:
                uuids.append(tool.tool_uuid)
                found.add(category)
                break
    return uuids, [c for c in template.tools if c not in found]


async def create_agent_from_template(
    *,
    organization_id: int,
    user_id: int,
    template: IndustryTemplate,
    name: str | None = None,
    attach_tools: bool = True,
):
    """A ready agent for the trade; returns (workflow, missing tool categories)."""
    from api.db import db_client

    profile = await get_business_profile(organization_id)
    uuids, missing = (
        await attachable_tools(organization_id, template)
        if attach_tools
        else ([], list(template.tools))
    )
    definition, configurations = build_agent_definition(
        template, profile, tool_uuids=uuids
    )
    company = profile.name.strip()
    workflow = await db_client.create_workflow(
        name or (f"{template.label} — {company}" if company else template.label),
        definition,
        user_id,
        organization_id,
        created_via="template",
        workflow_configurations=configurations,
    )
    return workflow, missing
