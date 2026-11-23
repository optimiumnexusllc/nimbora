"""AI Business Hub: conversations, calls, leads, appointments, per channel."""

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException

from api.db.models import UserModel
from api.services.auth.depends import get_user
from api.services.business_hub.service import business_hub

router = APIRouter(prefix="/business-hub", tags=["business-hub"])


@router.get("")
async def read_business_hub(
    period: Literal["7d", "30d", "90d"] = "30d", user: UserModel = Depends(get_user)
) -> dict[str, Any]:
    """Key figures compared with the period before, by channel and by day
    (days in the company's time zone, « Mon entreprise »)."""
    if not user.selected_organization_id:
        raise HTTPException(status_code=400, detail="Aucune organisation sélectionnée")
    return await business_hub(user.selected_organization_id, period)
