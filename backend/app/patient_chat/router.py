import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.auth.provider import AuthenticatedUser
from app.core.db import get_db
from app.patient_chat import service
from app.patient_chat.schemas import ChatMessageListResponse, ChatMessageRead

router = APIRouter(prefix="/patients", tags=["patient-chat"])


@router.get("/{patient_id}/chat", response_model=ChatMessageListResponse)
def list_patient_chat_messages(
    patient_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> ChatMessageListResponse:
    """Clinician-authenticated — the same transcript the patient sees via
    /care-plan/chat, so a clinician can review what their patient asked and
    what they were told, including whether an emergency/treatment-change gate
    fired or a reply used live web search."""
    messages = service.list_chat_messages(db, patient_id)
    return ChatMessageListResponse(messages=[ChatMessageRead.model_validate(m) for m in messages])
