"""The patient's own sign-in to the SafeHaven patient app.

A patient has no password. Staff record consent and an email address, and
SafeHaven emails a single-use link; the patient asks for a fresh link any
time from the sign-in page. Only a SHA-256 of each link token is stored, as
with care links and staff password links.
"""

import uuid
from datetime import date, datetime, timezone

from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

STATUS_INVITED = "INVITED"
STATUS_ACTIVE = "ACTIVE"
STATUS_REVOKED = "REVOKED"

PURPOSE_INVITE = "invite"
PURPOSE_SIGN_IN = "sign_in"


class PatientAppAccount(Base):
    """One per patient, created at the first invite."""

    __tablename__ = "patient_app_accounts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    patient_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("patients.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=STATUS_INVITED)
    invited_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    invited_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_sign_in_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Set at discharge: the app keeps working at home for a while, then stops.
    # Null while the patient is admitted.
    access_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # In every patient token; bumping it signs out every device at once.
    session_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )


class PatientSignInLink(Base):
    __tablename__ = "patient_sign_in_links"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    patient_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("patients.id", ondelete="CASCADE"), index=True, nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    purpose: Mapped[str] = mapped_column(String(20), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )


DOSE_TAKEN = "TAKEN"
DOSE_SKIPPED = "SKIPPED"


class DoseLog(Base):
    """The patient's own "Taken" / "Skipped" for one scheduled dose. Patient-
    reported, not a clinical administration record (that is Module 2's
    AdministrationEvent, recorded by a nurse)."""

    __tablename__ = "patient_dose_logs"
    __table_args__ = (UniqueConstraint("instruction_id", "dose_date", "dose_time", name="uq_dose_log_slot"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    patient_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("patients.id", ondelete="CASCADE"), index=True, nullable=False
    )
    instruction_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("care_instructions.id", ondelete="CASCADE"), nullable=False
    )
    dose_date: Mapped[date] = mapped_column(Date, nullable=False)
    # "08:00", hospital local time — the slot from the dose schedule.
    dose_time: Mapped[str] = mapped_column(String(5), nullable=False)
    status: Mapped[str] = mapped_column(String(10), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )


class PushSubscription(Base):
    """One phone or browser that agreed to show reminders (Web Push)."""

    __tablename__ = "patient_push_subscriptions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    patient_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("patients.id", ondelete="CASCADE"), index=True, nullable=False
    )
    endpoint: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    p256dh: Mapped[str] = mapped_column(String(200), nullable=False)
    auth: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    last_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class DoseReminderSent(Base):
    """One reminder per patient per dose time per day, however often the
    reminder job runs."""

    __tablename__ = "patient_dose_reminders_sent"
    __table_args__ = (UniqueConstraint("patient_id", "dose_date", "dose_time", name="uq_dose_reminder_slot"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    patient_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("patients.id", ondelete="CASCADE"), nullable=False
    )
    dose_date: Mapped[date] = mapped_column(Date, nullable=False)
    dose_time: Mapped[str] = mapped_column(String(5), nullable=False)
    sent_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
