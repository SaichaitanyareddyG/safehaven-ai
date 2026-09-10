import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class PatientCondition(Base):
    """A clinician-documented condition/diagnosis for a patient. Deliberately a
    simple, manually-entered list — not an EHR/FHIR problem-list integration,
    which stays explicitly out of scope for this prototype. Free-text
    condition_name rather than a coded terminology (e.g. ICD-10): matching
    the prototype's overall "production-quality patterns but prototype-scale"
    philosophy. Kept as "conditions" (not renamed to "diagnoses") for this
    implementation pass — a naming-only decision, not a functional one; the
    UI may label it "Diagnoses / Conditions".

    encounter_id links a condition to the visit it was documented during,
    when known — nullable, since a condition can also be general/historical
    patient context not tied to any specific visit. Neither case is ever
    enough, on its own or together with a medication, to infer that
    medication's indication: resolve_why() (patient_access/service.py) only
    ever uses an indication/reason explicitly stated on the CareInstruction
    itself — an earlier prototype version tried matching a patient's
    documented condition to a medication's known uses and was reverted as a
    safety correction (see that module's docstring). This field exists for
    clinician context and encounter organization only, never as an inference
    input."""

    __tablename__ = "patient_conditions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    patient_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("patients.id"), nullable=False, index=True)
    encounter_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("encounters.id"), nullable=True, index=True
    )

    condition_name: Mapped[str] = mapped_column(String(255), nullable=False)

    documented_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    documented_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
