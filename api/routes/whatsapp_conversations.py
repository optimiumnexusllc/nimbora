"""WhatsApp conversations handled by the agents (messaging)."""

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.db import db_client
from api.db.models import UserModel
from api.services.auth.depends import get_user

router = APIRouter(prefix="/whatsapp/conversations", tags=["whatsapp"])


def _org(user: UserModel) -> int:
    if not user.selected_organization_id:
        raise HTTPException(status_code=400, detail="No organization selected")
    return user.selected_organization_id


class ConversationResponse(BaseModel):
    id: int
    customer_wa_id: str
    customer_name: str | None
    business_number: str | None
    workflow_id: int | None
    workflow_run_id: int | None
    status: str
    message_count: int
    last_inbound_at: datetime | None
    last_outbound_at: datetime | None
    created_at: datetime | None


class ConversationMessage(BaseModel):
    role: Literal["customer", "agent"]
    text: str
    at: str | None = None


class ConversationDetail(ConversationResponse):
    messages: list[ConversationMessage]


@router.get("", response_model=list[ConversationResponse])
async def list_conversations(
    status: Literal["open", "closed", "all"] = "all",
    user: UserModel = Depends(get_user),
):
    rows = await db_client.list_whatsapp_conversations(
        _org(user), status=None if status == "all" else status
    )
    return [ConversationResponse.model_validate(r, from_attributes=True) for r in rows]


@router.get("/{conversation_id}", response_model=ConversationDetail)
async def get_conversation(conversation_id: int, user: UserModel = Depends(get_user)):
    from api.services.whatsapp_messaging.service import _assistant_texts
    from api.services.workflow.text_chat_session_service import (
        normalize_text_chat_session_data,
    )

    organization_id = _org(user)
    conversation = await db_client.get_whatsapp_conversation(
        organization_id, conversation_id
    )
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    messages: list[ConversationMessage] = []
    if conversation.workflow_run_id:
        session = await db_client.get_workflow_run_text_session(
            conversation.workflow_run_id, organization_id=organization_id
        )
        if session is not None:
            for turn in normalize_text_chat_session_data(session.session_data)["turns"]:
                user_message = turn.get("user_message") or {}
                if user_message.get("text"):
                    messages.append(
                        ConversationMessage(
                            role="customer",
                            text=user_message["text"],
                            at=user_message.get("created_at"),
                        )
                    )
                for text in _assistant_texts(turn):
                    messages.append(ConversationMessage(role="agent", text=text))
    return ConversationDetail(
        **ConversationResponse.model_validate(
            conversation, from_attributes=True
        ).model_dump(),
        messages=messages,
    )
