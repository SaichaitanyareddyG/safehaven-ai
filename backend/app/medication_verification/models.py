import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, String, Text
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


class NotGivenReason(str, enum.Enum):
    """Why a verified dose was deliberately not given.

    A scheduled dose that simply never happens is invisible: before this, an
    abandoned verification and a dose the patient refused were the same row —
    VERIFIED, administered_at NULL — and nobody could tell them apart or tell
    that a decision had been made at all. Recording the decision is the point;
    the nurse choosing one of these is documenting care, not failing to."""

    REFUSED = "REFUSED"  # patient declined
    HELD = "HELD"  # clinically withheld (e.g. nil by mouth before surgery)
    PATIENT_UNAVAILABLE = "PATIENT_UNAVAILABLE"  # off the ward, in theatre, at imaging
    VOMITED = "VOMITED"  # taken but not retained
    OTHER = "OTHER"  # free-text note carries the detail


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
    # Persisted at verify() time from the resolved MedicationProduct's
    # high_alert flag (see app/reference/medication_products.py) — never
    # re-derived from the barcode at administer() time, same rationale as
    # the identified_* fields above. Gates the independent second-clinician
    # co-sign requirement in administer(); always False for an
    # image-identified result (see verify_confirmed()'s docstring — there is
    # no catalog entry to check high_alert against for a photo-identified
    # candidate).
    identified_high_alert: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Whether the matched order is as-needed (PRN) rather than scheduled,
    # captured at verify() time from the order's own frequency. A PRN dose is
    # not just "a dose that happened" — CMS/nursing documentation standards
    # expect the indication to be recorded ("pain 7/10"), because without it
    # nobody can later assess whether the dose worked or whether the patient
    # is being dosed too often. Persisted rather than re-derived so
    # administer() reads the same fact verify() did.
    order_is_prn: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

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
    # ISMP's recommended mitigation for high-alert medications: an
    # independent second clinician, authenticated separately (not just
    # clicked through), before administration is recorded. Only ever set
    # when identified_high_alert is True — see administer()'s co-sign gate.
    co_signed_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    # Why this PRN dose was given ("pain 7/10"). Required by administer() only
    # when order_is_prn — a scheduled dose's reason is the schedule itself.
    administration_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # The deliberate not-given outcome. Mutually exclusive with
    # administered_at: a row carries one or the other, never both, and a row
    # with neither is simply a verification nobody acted on yet.
    not_given_reason: Mapped[NotGivenReason | None] = mapped_column(
        SAEnum(NotGivenReason, name="administration_not_given_reason", native_enum=True), nullable=True
    )
    not_given_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    not_given_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    not_given_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Reserved for a future controlled-override flow (see MODULE_2_DESIGN_REPORT.md
    # section 17) — deliberately not written to by anything in this build.
    override_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False, index=True
    )
