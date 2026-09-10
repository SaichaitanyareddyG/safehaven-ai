import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, ForeignKey, String, Text
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class VerificationResult(str, enum.Enum):
    VERIFIED = "VERIFIED"
    WARNING = "WARNING"
    BLOCKED = "BLOCKED"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"


class IdentificationMethod(str, enum.Enum):
    """How the physical product was identified — BARCODE is the normal path;
    IMAGE means the barcode could not be read and the nurse instead
    photographed the label, had it read by vision/OCR, and confirmed the
    result themselves before it entered verification (see
    service.py's identify_from_image()/verify_confirmed()). The UI must
    always disclose IMAGE results as "barcode verification unavailable" —
    this field is what lets it do that even after the fact, from a
    persisted row."""

    BARCODE = "BARCODE"
    IMAGE = "IMAGE"


class AdministrationEvent(Base):
    """One row per medication-verification attempt at the bedside — not one
    row per successful administration. A BLOCKED or REVIEW_REQUIRED attempt
    is still persisted (append-only, like AuditEvent) because a mismatch
    caught at the bedside is itself important safety data.

    Deliberately distinct from "administered": administered_by/administered_at
    stay NULL until the separate confirm-administration step actually runs
    (see service.py's administer()), and only ever get populated when
    verification_result is VERIFIED or WARNING — never BLOCKED or
    REVIEW_REQUIRED. A verified match is a moment-in-time comparison; it is
    not the same fact as "the dose was actually given."

    care_instruction_id is nullable: a BLOCKED result from "no matching order
    at all" or a REVIEW_REQUIRED result from "unrecognized barcode" has no
    single order to point at.

    product_barcode is stored as the raw scanned string, not a foreign key —
    MedicationProduct is a static reference mapping (app/reference/
    medication_products.py), not a database table (see
    MODULE_2_DESIGN_REPORT.md section 5)."""

    __tablename__ = "administration_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    patient_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("patients.id"), nullable=False, index=True
    )
    care_instruction_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("care_instructions.id"), nullable=True, index=True
    )

    product_barcode: Mapped[str] = mapped_column(String(200), nullable=False)
    identification_method: Mapped[IdentificationMethod] = mapped_column(
        SAEnum(IdentificationMethod, name="administration_identification_method", native_enum=True),
        nullable=False,
        default=IdentificationMethod.BARCODE,
    )

    # The product identity actually compared at verify() time — persisted
    # (not just the barcode string) so administer() can revalidate against a
    # FRESH read of the order using the SAME product identity, without
    # re-deriving it from a barcode that, for an image-identified result, is
    # only ever the placeholder "IMAGE-CONFIRMED" (see
    # MODULE_2_EDGE_CASE_REVIEW.md section 11). Null only on the very first
    # verify() early-exit (wristband didn't resolve to a patient at all —
    # see service.py's verify(); that path never persists a row anyway) or
    # when no product could be resolved from the barcode (PRODUCT_NOT_FOUND).
    identified_medication_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    identified_strength_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    identified_strength_unit: Mapped[str | None] = mapped_column(String(50), nullable=True)
    identified_formulation: Mapped[str | None] = mapped_column(String(255), nullable=True)
    identified_route: Mapped[str | None] = mapped_column(String(50), nullable=True)

    verification_result: Mapped[VerificationResult] = mapped_column(
        SAEnum(VerificationResult, name="administration_verification_result", native_enum=True), nullable=False
    )
    # Machine-readable reason codes (e.g. ["FORMULATION_MISMATCH"]) — empty when VERIFIED.
    mismatch_reasons: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    # Per-check pass/fail detail (patient/medication/dose/formulation/route/time),
    # stored so the UI checklist and any later audit review can be reconstructed
    # without recomputing the comparison against data that may have since changed.
    checks: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    performed_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)

    administered_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    administered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Reserved for a future controlled-override flow (see MODULE_2_DESIGN_REPORT.md
    # section 17) — deliberately not written to by anything in this build.
    override_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False, index=True
    )
