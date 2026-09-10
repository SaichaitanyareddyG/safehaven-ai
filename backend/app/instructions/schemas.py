import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, field_validator

from app.encounters.schemas import EncounterSummary
from app.instructions.models import (
    ClinicalStatus,
    CompletenessStatus,
    InstructionStatus,
    InstructionType,
    ValidationStatus,
    VersionSource,
)
from app.patients.models import Language


class InstructionTextPayload(BaseModel):
    """Shared shape for both instruction creation and clarification — both are
    just "here is clinical text", server decides everything else (version number,
    source, status)."""

    text: str

    @field_validator("text")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("text cannot be empty")
        return value


class RejectionRequest(BaseModel):
    reason: str

    @field_validator("reason")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("reason cannot be empty")
        return value


class StructuredExtractionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    instruction_type: InstructionType | None
    extracted_facts: dict
    normalized_facts: dict
    missing_fields: list[str]
    ambiguous_fields: list[str]
    clarification_required_fields: list[str]
    validation_messages: list[str]
    completeness_status: CompletenessStatus
    provider: str
    model: str
    prompt_version: str
    created_at: datetime


class PatientOutputTranslationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    language: Language
    translated_text: str | None
    validation_status: ValidationStatus
    validation_diff: list[dict]
    validation_messages: list[str]
    provider: str
    model: str
    prompt_version: str
    created_at: datetime


class PatientOutputRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    attempt_number: int
    patient_text_en: str | None
    validation_status: ValidationStatus
    validation_diff: list[dict]
    validation_messages: list[str]
    provider: str
    model: str
    prompt_version: str
    created_at: datetime
    # One row per language ever attempted for this output (immutable — see
    # PatientOutputTranslation). A missing language here just means it hasn't
    # been requested yet, same as an empty list.
    translations: list[PatientOutputTranslationRead] = []


class InstructionVersionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    version_number: int
    raw_text: str
    source: VersionSource
    created_at: datetime
    # Nested rather than a sibling top-level field on CareInstructionRead — both
    # belong to a specific version, and historical versions can carry their own
    # extraction/output attempts too (see GET /instructions/{id}). patient_outputs
    # is the full immutable attempt history for this version, ordered by
    # attempt_number — the latest attempt is patient_outputs[-1] when non-empty.
    extraction: StructuredExtractionRead | None = None
    patient_outputs: list[PatientOutputRead] = []


class TranslationRequest(BaseModel):
    languages: list[Language]

    @field_validator("languages")
    @classmethod
    def _no_english_no_duplicates(cls, value: list[Language]) -> list[Language]:
        if not value:
            raise ValueError("languages cannot be empty")
        if Language.ENGLISH in value:
            raise ValueError("English is already the canonical patient text — request TELUGU/HINDI only")
        if len(set(value)) != len(value):
            raise ValueError("languages must not contain duplicates")
        return value


class TranslationResultItem(BaseModel):
    status: ValidationStatus


class CareInstructionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    patient_id: uuid.UUID
    status: InstructionStatus
    review_reason: str | None
    approved_at: datetime | None
    created_at: datetime
    updated_at: datetime
    current_version: InstructionVersionRead | None
    # Medication clinical lifecycle — always None for non-MEDICATION
    # instructions (see ClinicalStatus's docstring). encounter is the visit
    # this order originated from, when known; never re-derived from "which
    # encounter is currently open."
    encounter: EncounterSummary | None = None
    clinical_status: ClinicalStatus | None = None
    clinical_start_date: date | None = None
    clinical_end_date: date | None = None


class CareInstructionDetail(CareInstructionRead):
    versions: list[InstructionVersionRead]


class CareInstructionListResponse(BaseModel):
    total: int
    results: list[CareInstructionRead]


class ClinicalStatusUpdate(BaseModel):
    status: ClinicalStatus
