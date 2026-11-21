"""Run an agent action tool (calendar, message, ticket) for a live call."""

from __future__ import annotations

from typing import Any

from api.services.actions.common import ActionContext, ActionError
from loguru import logger

ACTION_CATEGORIES = ("book_appointment", "send_message", "create_ticket")


async def run_action(
    category: str, ctx: ActionContext, config: dict[str, Any], args: dict[str, Any]
):
    """Never raises: errors become a result the agent can explain."""
    try:
        if category == "book_appointment":
            from api.services.actions.calendar.service import handle_calendar

            return await handle_calendar(ctx, config, args)
        if category == "send_message":
            from api.services.actions.messaging import handle_message

            return await handle_message(ctx, config, args)
        if category == "create_ticket":
            from api.services.actions.tickets import handle_ticket

            return await handle_ticket(ctx, config, args)
        raise ActionError(f"Unknown action tool '{category}'")
    except ActionError as exc:
        return {"status": "error", "error": str(exc)}
    except Exception:
        logger.opt(exception=True).error(f"Action tool {category} failed")
        return {
            "status": "error",
            "error": "The action failed. Apologize and offer a callback or a human.",
        }
