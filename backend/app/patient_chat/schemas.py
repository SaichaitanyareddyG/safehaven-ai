import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.patient_chat.models import ChatRole


class ChatMessageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    role: ChatRole
    text: str
    emergency_flagged: bool
    redirect_flagged: bool
    web_search_used: bool
    created_at: datetime


class ChatMessageListResponse(BaseModel):
    messages: list[ChatMessageRead]


class ChatSendRequest(BaseModel):
    token: str
    text: str


class ChatSendResponse(BaseModel):
    patient_message: ChatMessageRead
    assistant_message: ChatMessageRead
