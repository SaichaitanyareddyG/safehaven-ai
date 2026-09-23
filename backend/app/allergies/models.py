import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class PatientAllergy(Base):
    """A clinician-documented medication/substance allergy for a patient —
    the single most basic medication-safety check a hospital system is
    expected to have (ONC CDS certification criterion 170.315(a)(4), drug-
    allergy interaction checking) and, until now, one this prototype didn't
    have at all. See US_HOSPITAL_MARKET_STANDARDS_GAP_ANALYSIS.md item 2.

    Free-text allergen (not a coded terminology like RxNorm) — matching
    PatientCondition's same prototype-scale precedent. reaction and severity
    are optional context for the clinician; the verification engine
    (medication_verification/service.py's _check_allergy) only ever matches
    on allergen name, never on reaction/severity."""

    __tablename__ = "patient_allergies"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    patient_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("patients.id"), nullable=False, index=True)

    allergen: Mapped[str] = mapped_column(String(255), nullable=False)
    reaction: Mapped[str | None] = mapped_column(String(255), nullable=True)
    severity: Mapped[str | None] = mapped_column(String(50), nullable=True)

    documented_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    documented_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
