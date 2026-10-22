"""A booked hospital appointment (clinic visit, follow-up, test), entered by
staff and shown in the patient app with reminders."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

STATUS_SCHEDULED = "SCHEDULED"
STATUS_CANCELLED = "CANCELLED"

REMINDER_DAY_BEFORE = "DAY_BEFORE"
REMINDER_TWO_HOURS = "TWO_HOURS"


class Appointment(Base):
    __tablename__ = "appointments"
    __table_args__ = (Index("ix_appointments_starts_at", "starts_at"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    patient_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("patients.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # Shown to the patient, so written for them: "Cardiology check-up".
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    location: Mapped[str | None] = mapped_column(String(300), nullable=True)
    # For the patient: "Bring your medicines", "Nothing to eat after midnight".
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=STATUS_SCHEDULED)
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


class AppointmentReminderSent(Base):
    """One reminder of each kind per appointment, however often the job runs.
    Rescheduling clears these, so the new time is reminded too."""

    __tablename__ = "appointment_reminders_sent"
    __table_args__ = (UniqueConstraint("appointment_id", "kind", name="uq_appointment_reminder"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    appointment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("appointments.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    sent_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
