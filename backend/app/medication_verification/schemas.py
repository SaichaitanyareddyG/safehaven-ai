import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.medication_verification.models import IdentificationMethod, NotGivenReason, VerificationResult


class MedicationProductRead(BaseModel):
    barcode: str
    medication_name: str
    strength_value: float
    strength_unit: str
    formulation: str
    route: str
    high_alert: bool = False


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
    # True when the matched order is as-needed (PRN) — the UI must then
    # collect an indication before administration can be confirmed.
    order_is_prn: bool = False
    created_at: datetime


class AdministerRequest(BaseModel):
    verification_id: uuid.UUID
    # Only required when the verified product is high-alert (see
    # MedicationProductRead.high_alert) — ignored otherwise.
    co_signer_email: str | None = None
    co_signer_password: str | None = None
    # Required only when the verified order is PRN (see VerifyResponse.order_is_prn).
    administration_reason: str | None = None


class NotGivenRequest(BaseModel):
    verification_id: uuid.UUID
    reason: NotGivenReason
    note: str | None = None


class AdministrationHistoryItem(BaseModel):
    """One bedside verification, as it appears on the patient's record.

    Blocked and review-required attempts are included deliberately — a wrong
    drug caught at this patient's bedside is exactly what the next shift and
    any reviewer need to see."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    created_at: datetime
    verification_result: VerificationResult
    identification_method: IdentificationMethod
    mismatch_reasons: list[str]
    identified_medication_name: str | None
    identified_strength_value: float | None
    identified_strength_unit: str | None
    administered_at: datetime | None
    administered_by: uuid.UUID | None
    co_signed_by: uuid.UUID | None
    administration_reason: str | None
    not_given_reason: NotGivenReason | None
    not_given_note: str | None
    not_given_at: datetime | None


class AdministrationHistoryResponse(BaseModel):
    total: int
    results: list[AdministrationHistoryItem]


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
    co_signed_by: uuid.UUID | None
    administration_reason: str | None
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
