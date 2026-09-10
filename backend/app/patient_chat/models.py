import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Text
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class ChatRole(str, enum.Enum):
    PATIENT = "PATIENT"
    ASSISTANT = "ASSISTANT"


class PatientChatMessage(Base):
    """One row per chat turn, patient and assistant alike, so the full
    conversation can be replayed in order on both the patient view (via a
    care-access token) and the clinician view (via normal auth).

    emergency_flagged / redirect_flagged record which of the two hard,
    deterministic, pre-LLM gates (see patient_chat/service.py) fired on a
    given patient message — the assistant's reply in that case is the fixed
    safety message, never something the LLM composed. web_search_used
    records whether the assistant's reply was generated with the live,
    trusted-domain-restricted web search tool (see PATIENT_CHAT_SYSTEM_PROMPT)
    rather than from the care plan and curated facts alone — so a clinician
    reviewing the transcript can see when an answer went beyond what this
    app already had on file."""

    __tablename__ = "patient_chat_messages"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    patient_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("patients.id"), nullable=False, index=True)

    role: Mapped[ChatRole] = mapped_column(SAEnum(ChatRole, name="patient_chat_role", native_enum=True), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)

    emergency_flagged: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    redirect_flagged: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    web_search_used: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False, index=True
    )
