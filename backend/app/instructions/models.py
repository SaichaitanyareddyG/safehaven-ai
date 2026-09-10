import enum
import uuid
from datetime import date, datetime, timezone

from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.patients.models import Language


class InstructionStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    PROCESSING = "PROCESSING"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    READY_FOR_APPROVAL = "READY_FOR_APPROVAL"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class VersionSource(str, enum.Enum):
    ORIGINAL = "ORIGINAL"
    CLARIFICATION = "CLARIFICATION"


class InstructionType(str, enum.Enum):
    """The supported instruction categories for Phase 1. Not exhaustive of all
    clinical instructions — unclassifiable content safely falls back to GENERAL
    rather than forcing an incorrect fit or failing."""

    MEDICATION = "MEDICATION"
    MOBILITY = "MOBILITY"
    DIET = "DIET"
    WOUND_CARE = "WOUND_CARE"
    FOLLOW_UP = "FOLLOW_UP"
    GENERAL = "GENERAL"


class CompletenessStatus(str, enum.Enum):
    PASSED = "PASSED"
    NEEDS_CLARIFICATION = "NEEDS_CLARIFICATION"
    FAILED = "FAILED"


class ValidationStatus(str, enum.Enum):
    PENDING = "PENDING"
    PASSED = "PASSED"
    FAILED = "FAILED"


class ClinicalStatus(str, enum.Enum):
    """Whether a medication is still in effect for the patient — entirely
    separate from InstructionStatus above (which governs the AI/clinician
    authoring workflow, not clinical reality). Applies ONLY to
    instructions whose current extraction's instruction_type is MEDICATION
    — see instructions/service.py's approve() and the clinical-status
    endpoint, the only two places this column is ever written. Every other
    instruction type (MOBILITY/DIET/WOUND_CARE/FOLLOW_UP/GENERAL) leaves
    this column NULL forever, by construction, not by convention: neither
    code path writes to it for a non-MEDICATION instruction, and there is no
    column-level default that could populate it for one either."""

    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    STOPPED = "STOPPED"


class CareInstruction(Base):
    __tablename__ = "care_instructions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    patient_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("patients.id"), nullable=False, index=True
    )
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)

    # Which visit this order originated from, when known — nullable, same as
    # PatientCondition.encounter_id, and for the same reason (see that
    # model's docstring): organizational context only, never an inference
    # input. A medication can remain ACTIVE long after its originating
    # encounter is CLOSED — this column is never re-derived from encounter
    # state, and nothing in this app infers "current encounter" from it.
    encounter_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("encounters.id"), nullable=True, index=True
    )

    status: Mapped[InstructionStatus] = mapped_column(
        SAEnum(InstructionStatus, name="instruction_status", native_enum=True),
        nullable=False,
        default=InstructionStatus.DRAFT,
    )
    review_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # --- Medication clinical lifecycle (MEDICATION-type instructions only —
    # see ClinicalStatus docstring). All five nullable, no column defaults;
    # clinical_start_date is set from approved_at at approval time as a
    # best-available estimate — NOT the same thing as created_at (when the
    # draft record was first made) or an authoritative clinician-entered
    # start date, which this prototype has no UI for yet.
    clinical_status: Mapped[ClinicalStatus | None] = mapped_column(
        SAEnum(ClinicalStatus, name="care_instruction_clinical_status", native_enum=True), nullable=True
    )
    clinical_start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    clinical_end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    clinical_status_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    clinical_status_changed_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )

    # References instruction_versions, which itself references this table (via
    # care_instruction_id) — a genuine circular FK. use_alter=True tells SQLAlchemy
    # (and Alembic autogenerate) to emit this constraint as a separate ALTER TABLE
    # after both tables exist, instead of trying to inline it at CREATE TABLE time.
    current_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "instruction_versions.id",
            use_alter=True,
            name="fk_care_instructions_current_version_id",
        ),
        nullable=True,
    )

    approved_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    versions: Mapped[list["InstructionVersion"]] = relationship(
        "InstructionVersion",
        back_populates="care_instruction",
        foreign_keys="InstructionVersion.care_instruction_id",
        order_by="InstructionVersion.version_number",
    )
    current_version: Mapped["InstructionVersion | None"] = relationship(
        "InstructionVersion",
        foreign_keys=[current_version_id],
        post_update=True,
    )
    encounter: Mapped["Encounter | None"] = relationship("Encounter", foreign_keys=[encounter_id])


class InstructionVersion(Base):
    __tablename__ = "instruction_versions"
    __table_args__ = (
        UniqueConstraint("care_instruction_id", "version_number", name="uq_instruction_version_number"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    care_instruction_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("care_instructions.id"), nullable=False, index=True
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)

    # Immutable once written — clarifications always create a new row, never edit this one.
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[VersionSource] = mapped_column(
        SAEnum(VersionSource, name="instruction_version_source", native_enum=True), nullable=False
    )

    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )

    care_instruction: Mapped["CareInstruction"] = relationship(
        "CareInstruction", back_populates="versions", foreign_keys=[care_instruction_id]
    )
    extraction: Mapped["StructuredExtraction | None"] = relationship(
        "StructuredExtraction", back_populates="instruction_version", uselist=False
    )
    patient_outputs: Mapped[list["PatientOutput"]] = relationship(
        "PatientOutput", back_populates="instruction_version", order_by="PatientOutput.attempt_number"
    )


class StructuredExtraction(Base):
    __tablename__ = "structured_extractions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # At most one extraction per version — a clarification creates a new version
    # (and thus a new extraction) rather than this row ever being overwritten.
    instruction_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("instruction_versions.id"),
        nullable=False,
        unique=True,
        index=True,
    )

    # Nullable: a failed/malformed extraction may have no reliable classification.
    instruction_type: Mapped[InstructionType | None] = mapped_column(
        SAEnum(InstructionType, name="structured_extraction_instruction_type", native_enum=True),
        nullable=True,
    )

    extracted_facts: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    normalized_facts: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    missing_fields: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    ambiguous_fields: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    clarification_required_fields: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    validation_messages: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)

    completeness_status: Mapped[CompletenessStatus] = mapped_column(
        SAEnum(CompletenessStatus, name="structured_extraction_completeness_status", native_enum=True),
        nullable=False,
    )

    # Provider/operational metadata — never the raw prompt or raw response text,
    # which may contain PHI (see Settings.store_raw_llm_data, default off, and no
    # raw-storage column exists here at all).
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(50), nullable=False)
    provider_request_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    token_usage: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )

    instruction_version: Mapped["InstructionVersion"] = relationship(
        "InstructionVersion", back_populates="extraction", foreign_keys=[instruction_version_id]
    )


class PatientOutput(Base):
    __tablename__ = "patient_outputs"
    __table_args__ = (
        UniqueConstraint("instruction_version_id", "attempt_number", name="uq_patient_output_attempt"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    instruction_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("instruction_versions.id"), nullable=False, index=True
    )
    # Immutable attempt history — a second generation attempt on the same version
    # (e.g. after a FAILED one) is a new row, never an overwrite of the first.
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)

    # Nullable: a total provider/generation failure may have no text at all.
    patient_text_en: Mapped[str | None] = mapped_column(Text, nullable=True)

    validation_status: Mapped[ValidationStatus] = mapped_column(
        SAEnum(ValidationStatus, name="patient_output_validation_status", native_enum=True),
        nullable=False,
        default=ValidationStatus.PENDING,
    )
    validation_diff: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    validation_messages: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)

    # Provider/operational metadata only — never the raw prompt or raw response
    # text, and never the LLM's own reasoning/chain-of-thought about its output.
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(50), nullable=False)
    provider_request_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    token_usage: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )

    instruction_version: Mapped["InstructionVersion"] = relationship(
        "InstructionVersion", back_populates="patient_outputs", foreign_keys=[instruction_version_id]
    )
    translations: Mapped[list["PatientOutputTranslation"]] = relationship(
        "PatientOutputTranslation", back_populates="patient_output", order_by="PatientOutputTranslation.language"
    )


class PatientOutputTranslation(Base):
    __tablename__ = "patient_output_translations"
    __table_args__ = (
        UniqueConstraint("patient_output_id", "language", name="uq_translation_per_language"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    patient_output_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("patient_outputs.id"), nullable=False, index=True
    )
    # English isn't stored here — PatientOutput.patient_text_en is already the
    # canonical English source. One row per (output, language) forever — no
    # attempt_number/retry history, unlike PatientOutput itself (see service.py:
    # a repeat request for an already-translated language returns the existing
    # row rather than re-translating, keeping rows immutable).
    language: Mapped[Language] = mapped_column(
        SAEnum(Language, name="patient_language", native_enum=True, create_type=False), nullable=False
    )

    translated_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    validation_status: Mapped[ValidationStatus] = mapped_column(
        SAEnum(ValidationStatus, name="patient_output_validation_status", native_enum=True, create_type=False),
        nullable=False,
        default=ValidationStatus.PENDING,
    )
    validation_diff: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    validation_messages: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)

    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(50), nullable=False)
    provider_request_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    token_usage: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )

    patient_output: Mapped["PatientOutput"] = relationship(
        "PatientOutput", back_populates="translations", foreign_keys=[patient_output_id]
    )
