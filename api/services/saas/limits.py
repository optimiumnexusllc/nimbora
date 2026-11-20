"""Plan limits enforced when tenants create resources."""

from api.constants import SAAS_MODE


class PlanLimitExceeded(Exception):
    """Creating one more resource would exceed the tenant's plan."""


async def enforce_agent_limit(organization_id: int) -> None:
    if not SAAS_MODE:
        return
    from api.db import db_client
    from api.services.saas.subscription_service import check_limit

    current = await db_client.count_organization_agents(organization_id)
    message = await check_limit(organization_id, "max_agents", current)
    if message:
        raise PlanLimitExceeded(message)


async def enforce_human_seat_limit(organization_id: int) -> None:
    if not SAAS_MODE:
        return
    from api.db import db_client
    from api.services.saas.subscription_service import check_limit

    current = await db_client.count_contact_center_agents(organization_id)
    message = await check_limit(organization_id, "max_human_seats", current)
    if message:
        raise PlanLimitExceeded(message)
