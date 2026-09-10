import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Index, String
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class ActorType(str, enum.Enum):
    CLINICIAN = "CLINICIAN"
    PATIENT = "PATIENT"
    SYSTEM = "SYSTEM"


class AuditEventType(str, enum.Enum):
    """Application-level enum used on the write side for type safety. Stored as a
    plain string column (see AuditEvent.event_type) rather than a native Postgres
    enum — unlike the rest of the schema's stable, closed enums (InstructionStatus
    etc.), this list is expected to grow as later steps/modules add new event
    types, and a native enum would require a migration for every addition."""

    USER_LOGIN = "USER_LOGIN"
    LOGIN_FAILED = "LOGIN_FAILED"
    PATIENT_CREATED = "PATIENT_CREATED"
    PATIENT_UPDATED = "PATIENT_UPDATED"
    PATIENT_DISCHARGED = "PATIENT_DISCHARGED"
    INSTRUCTION_CREATED = "INSTRUCTION_CREATED"
    INSTRUCTION_ANALYSIS_STARTED = "INSTRUCTION_ANALYSIS_STARTED"
    INSTRUCTION_ANALYSIS_PASSED = "INSTRUCTION_ANALYSIS_PASSED"
    INSTRUCTION_NEEDS_REVIEW = "INSTRUCTION_NEEDS_REVIEW"
    CLARIFICATION_CREATED = "CLARIFICATION_CREATED"
    PATIENT_OUTPUT_GENERATED = "PATIENT_OUTPUT_GENERATED"
    FACT_VALIDATION_PASSED = "FACT_VALIDATION_PASSED"
    FACT_VALIDATION_FAILED = "FACT_VALIDATION_FAILED"
    INSTRUCTION_APPROVED = "INSTRUCTION_APPROVED"
    INSTRUCTION_REJECTED = "INSTRUCTION_REJECTED"
    TRANSLATION_CREATED = "TRANSLATION_CREATED"
    TRANSLATION_VALIDATION_PASSED = "TRANSLATION_VALIDATION_PASSED"
    TRANSLATION_VALIDATION_FAILED = "TRANSLATION_VALIDATION_FAILED"
    CARE_ACCESS_TOKEN_CREATED = "CARE_ACCESS_TOKEN_CREATED"
    CARE_ACCESS_TOKEN_REVOKED = "CARE_ACCESS_TOKEN_REVOKED"
    CARE_PLAN_VIEWED = "CARE_PLAN_VIEWED"
    PATIENT_CONDITION_ADDED = "PATIENT_CONDITION_ADDED"
    PATIENT_CONDITION_REMOVED = "PATIENT_CONDITION_REMOVED"
    PATIENT_CHAT_EMERGENCY_FLAGGED = "PATIENT_CHAT_EMERGENCY_FLAGGED"
    PATIENT_CHAT_TREATMENT_CHANGE_REDIRECTED = "PATIENT_CHAT_TREATMENT_CHANGE_REDIRECTED"
    PATIENT_CHAT_WEB_SEARCH_USED = "PATIENT_CHAT_WEB_SEARCH_USED"
    PATIENT_COMPREHENSION_NEEDS_ATTENTION = "PATIENT_COMPREHENSION_NEEDS_ATTENTION"
    ENCOUNTER_CREATED = "ENCOUNTER_CREATED"
    MEDICATION_CLINICAL_STATUS_CHANGED = "MEDICATION_CLINICAL_STATUS_CHANGED"

    # Module 2 — medication administration verification (see
    # app/medication_verification/service.py)
    PATIENT_SCANNED = "PATIENT_SCANNED"
    MEDICATION_SCANNED = "MEDICATION_SCANNED"
    MEDICATION_SCAN_FAILED = "MEDICATION_SCAN_FAILED"
    MEDICATION_IMAGE_IDENTIFIED = "MEDICATION_IMAGE_IDENTIFIED"
    MEDICATION_MANUALLY_CONFIRMED = "MEDICATION_MANUALLY_CONFIRMED"
    MEDICATION_VERIFIED = "MEDICATION_VERIFIED"
    MEDICATION_MISMATCH = "MEDICATION_MISMATCH"
    ADMINISTRATION_CONFIRMED = "ADMINISTRATION_CONFIRMED"


class AuditEvent(Base):
    """Immutable record of a clinically relevant action. Rows are only ever
    inserted — see app/audit/service.py's record_event(), the single writer.
    There is deliberately no update/delete function anywhere in this codebase
    and no PATCH/DELETE route (see audit/router.py and
    tests/integration/test_audit.py's test proving that)."""

    __tablename__ = "audit_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    event_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    actor_type: Mapped[ActorType] = mapped_column(
        SAEnum(ActorType, name="audit_actor_type", native_enum=True), nullable=False
    )
    # Populated for CLINICIAN actors (the clinician's user id). Null for PATIENT
    # (patients have no user account — patient_id below already identifies them)
    # and SYSTEM (automatic actions, e.g. discharge-triggered token revocation).
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )

    patient_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("patients.id"), nullable=True, index=True
    )

    entity_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    entity_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    # Mapped Python attribute is `event_metadata` — `metadata` is reserved on
    # SQLAlchemy declarative classes (Base.metadata). The actual DB column is
    # still named "metadata". Never store API keys, raw tokens, chain-of-thought,
    # raw provider responses, or full clinical/patient text here — see
    # record_event()'s docstring for the redaction rules this must follow.
    event_metadata: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False, index=True
    )

    __table_args__ = (Index("ix_audit_events_patient_created", "patient_id", "created_at"),)
