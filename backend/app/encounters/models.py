import enum
import uuid
from datetime import date, datetime, timezone

from sqlalchemy import Date, DateTime, ForeignKey, String, Text
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class EncounterStatus(str, enum.Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class Encounter(Base):
    """A single hospital visit — the missing concept that let a diagnosis or
    medication order from one visit get flattened together with an unrelated
    one from a different visit. CareInstruction.encounter_id and
    PatientCondition.encounter_id (both nullable) link into this, but linkage
    is optional by design: a diagnosis or medication documented outside any
    specific visit context is still valid clinician-authored data, just not
    tied to a visit — see those models' own docstrings. Neither linkage, nor
    its absence, ever changes the "never infer indication from a diagnosis"
    rule (see instructions/service.py's clinical-status logic and
    patient_access/service.py's resolve_why()) — Encounter is purely
    organizational context, never a basis for inference.

    Deliberately minimal for this prototype: no ward/unit, no coded
    encounter-type terminology (FHIR's Encounter.class), no separate
    admitting-provider field — reason_for_visit (free text) plus the two
    dates cover what Module 1 needs to prove the model."""

    __tablename__ = "encounters"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    patient_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("patients.id"), nullable=False, index=True)

    encounter_type: Mapped[str | None] = mapped_column(String(50), nullable=True)  # free text, e.g. "outpatient"

    # Planned procedure and the point from which the patient is nil by mouth.
    #
    # These exist because the verification engine knew a patient's orders but
    # nothing about their situation. Before surgery a patient is typically NPO
    # and oral medication is deliberately held — yet the order stays ACTIVE and
    # every dose/route/timing check still passes, so Module 2 would report
    # VERIFIED and tell the nurse it was safe to give. Same class as the
    # discharged-patient gap: situational state the engine could not see.
    #
    # nil_by_mouth_from is a timestamp rather than a boolean so it can be set
    # in advance ("NPO from midnight") and become true on its own, which is how
    # it is actually ordered. Null means the patient may eat and drink.
    planned_procedure: Mapped[str | None] = mapped_column(Text, nullable=True)
    nil_by_mouth_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reason_for_visit: Mapped[str | None] = mapped_column(Text, nullable=True)
    admission_date: Mapped[date] = mapped_column(Date, nullable=False)
    discharge_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[EncounterStatus] = mapped_column(
        SAEnum(EncounterStatus, name="encounter_status", native_enum=True), nullable=False, default=EncounterStatus.OPEN
    )

    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
