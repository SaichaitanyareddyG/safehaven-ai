import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Text
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


class PatientTeachBackResponse(Base):
    """AHRQ's teach-back method (Health Literacy Universal Precautions
    Toolkit, Tool 5) — instead of only a self-reported "Yes, I understand"
    click, the patient explains the instruction back in their own words, and
    that explanation is checked deterministically for whether it actually
    names the medication and mentions its documented timing/reason. See
    US_HOSPITAL_MARKET_STANDARDS_GAP_ANALYSIS.md item 9.

    The check itself (_check_teach_back in service.py) is a deliberately
    approximate, prototype-scale word-overlap comparison — never a claim of
    true language understanding, and it only ever requires facts that are
    actually documented on the order (an undocumented reason is never
    required to be mentioned). A "failed" result never blocks the patient
    from anything — same as UNDERSTOOD/HAS_QUESTION/ASK_CARE_TEAM above, it
    only flags the clinician's Activity Timeline via
    PATIENT_TEACH_BACK_NEEDS_ATTENTION for follow-up.

    One row per attempt, not overwritten — same precedent as
    PatientComprehensionFeedback above."""

    __tablename__ = "patient_teach_back_responses"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    patient_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("patients.id"), nullable=False, index=True)
    care_instruction_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("care_instructions.id"), nullable=False, index=True
    )

    response_text: Mapped[str] = mapped_column(Text, nullable=False)
    passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    confirmed_facts: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    missing_facts: Mapped[list] = mapped_column(JSON, nullable=False, default=list)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False, index=True
    )
