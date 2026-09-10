import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class ComprehensionResponse(str, enum.Enum):
    UNDERSTOOD = "UNDERSTOOD"
    HAS_QUESTION = "HAS_QUESTION"
    ASK_CARE_TEAM = "ASK_CARE_TEAM"


class PatientComprehensionFeedback(Base):
    """"Did this explanation help?" — the one place this app asks whether
    understanding was actually confirmed, not just whether information was
    shown. HAS_QUESTION / ASK_CARE_TEAM are surfaced to the clinician via the
    audit trail (PATIENT_COMPREHENSION_NEEDS_ATTENTION) so they land on the
    same Activity & Safety Timeline a clinician already watches — no separate
    UI needed. UNDERSTOOD is stored but not audited: not actionable, and
    audit events are for things a clinician needs to see, not routine
    confirmations.

    One row per response, not one-per-instruction — a patient can revisit
    and change their answer (e.g. "I still have a question" now, "Yes, I
    understand" after asking their care team), and the history of that is
    itself meaningful, not something to overwrite."""

    __tablename__ = "patient_comprehension_feedback"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    patient_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("patients.id"), nullable=False, index=True)
    care_instruction_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("care_instructions.id"), nullable=False, index=True
    )

    response: Mapped[ComprehensionResponse] = mapped_column(
        SAEnum(ComprehensionResponse, name="comprehension_response", native_enum=True), nullable=False
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False, index=True
    )
