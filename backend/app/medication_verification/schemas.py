import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.medication_verification.models import IdentificationMethod, VerificationResult


class MedicationProductRead(BaseModel):
    barcode: str
    medication_name: str
    strength_value: float
    strength_unit: str
    formulation: str
    route: str


class CheckResult(BaseModel):
    passed: bool
    detail: str


class VerifyRequest(BaseModel):
    patient_code: str
    barcode: str


class VerifyResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    result: VerificationResult
    identification_method: IdentificationMethod
    checks: dict[str, CheckResult]
    mismatch_reasons: list[str]
    care_instruction_id: uuid.UUID | None
    product: MedicationProductRead | None
    created_at: datetime


class AdministerRequest(BaseModel):
    verification_id: uuid.UUID


class AdministrationEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    patient_id: uuid.UUID
    care_instruction_id: uuid.UUID | None
    product_barcode: str
    identification_method: IdentificationMethod
    verification_result: VerificationResult
    mismatch_reasons: list[str]
    administered_by: uuid.UUID | None
    administered_at: datetime | None
    created_at: datetime


# --- Image fallback (barcode failure) ---


class ImageIdentificationResponse(BaseModel):
    """An UNCONFIRMED candidate only — see identify_from_image()'s docstring.
    Never contains a verification result; there is nothing to verify yet."""

    medication_name: str | None
    strength_value: float | None
    strength_unit: str | None
    formulation: str | None
    route: str | None
    confidence: str


class ConfirmedProductCandidate(BaseModel):
    """What the nurse actually confirmed — may differ from
    ImageIdentificationResponse if they corrected a field before confirming.
    All fields required: an unconfirmed/blank field cannot be compared
    against an order, so the nurse must have supplied something for each."""

    medication_name: str
    strength_value: float
    strength_unit: str
    formulation: str
    route: str


class VerifyConfirmedRequest(BaseModel):
    patient_code: str
    candidate: ConfirmedProductCandidate
