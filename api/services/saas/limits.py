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

    # One seat = one agent of the built-in contact center or one extension
    # of the enterprise PBX (see services/pbx/provisioning).
    current = await db_client.count_contact_center_agents(organization_id)
    current += await _pbx_extension_count(organization_id)
    message = await check_limit(organization_id, "max_human_seats", current)
    if message:
        raise PlanLimitExceeded(message)


async def _pbx_extension_count(organization_id: int) -> int:
    """Extensions of the company's PBX; 0 when none or unreachable."""
    from api.db import db_client

    if await db_client.get_pbx_connection(organization_id) is None:
        return 0
    from api.services.pbx import service
    from api.services.pbx.client import PbxError

    try:
        connection = await service._connection(organization_id)
        async with service.client_for(connection) as client:
            return len(await client.users())
    except PbxError:
        # Never block the built-in contact center on a PBX outage; the PBX
        # side checks the seats again when an extension is created.
        return 0
