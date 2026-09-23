import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Index,
    SmallInteger,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class DeviceStatus(str, enum.Enum):
    """ACTIVE is the only state in which a device may authenticate.

    DISABLED is the revocation state — reversible, credential cleared.
    RETIRED is terminal bookkeeping for hardware taken out of service. Rows are
    never deleted: a device's past events and audit trail must stay resolvable
    long after the hardware is gone."""

    ACTIVE = "ACTIVE"
    DISABLED = "DISABLED"
    RETIRED = "RETIRED"


class WearableDevice(Base):
    """One physical wearable (e.g. SH-WEAR-001).

    Reusable by design — the hardware is never permanently bound to a patient.
    The patient link lives in a separate assignment row (Stage 2), so
    reassigning a device after discharge is a new row rather than an edit here.

    Credential handling copies app/patient_access/PatientCareAccessToken
    exactly: a high-entropy secret is generated once, only its SHA-256 hash is
    stored, and the raw value is returned to the caller a single time and never
    again. That pattern was built for a patient's browser link, but it is the
    right shape for any bedside actor that is not a logged-in clinician, and
    unlike a JWT it is individually revocable — which is a hard requirement
    here. Compromising SH-WEAR-001 must never require re-crediting the rest of
    the fleet (MODULE_3_IMPLEMENTATION_PLAN.md §9).

    No relationship() declarations, matching the rest of this codebase, which
    queries by explicit FK filters throughout."""

    __tablename__ = "wearable_devices"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Human-facing asset tag, printed on the device. Staff-supplied, not generated:
    # it has to match whatever is physically on the hardware.
    device_code: Mapped[str] = mapped_column(String(32), unique=True, index=True, nullable=False)

    status: Mapped[DeviceStatus] = mapped_column(
        SAEnum(DeviceStatus, name="wearable_device_status", native_enum=True),
        default=DeviceStatus.ACTIVE,
        nullable=False,
    )

    # SHA-256 of the per-device secret. NULL means "not enrolled yet" or
    # "revoked" — both are states in which no request can authenticate.
    credential_hash: Mapped[str | None] = mapped_column(String(64), unique=True, index=True, nullable=True)

    # ESP32-S3 eFuse identifier, recorded at enrolment. Ties a credential to
    # specific silicon, so a stolen secret replayed from other hardware is at
    # least visible after the fact.
    hardware_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Single-use enrolment code, also stored only as a hash. Cleared the moment
    # it is consumed, so the same code can never enrol a second device.
    enrollment_code_hash: Mapped[str | None] = mapped_column(String(64), unique=True, index=True, nullable=True)
    enrollment_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Last-reported health. Updated in place by heartbeats rather than stored as
    # one row per beat — a row per device per 30s is precisely the historical
    # sensor-data lake this module is not supposed to build.
    firmware_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    battery_percent: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)

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


class MonitoringProfile(str, enum.Enum):
    """Which detectors the device runs, set explicitly by staff at assignment.

    RESTRICTED_MOBILITY is the only profile that enables the unexpected-mobility
    detector, and it must be chosen deliberately — never inferred from a
    diagnosis, a procedure name, or a mobility care instruction. That rule is
    the whole reason this is a stored field rather than something derived:
    inferring "this patient shouldn't be walking" from clinical data is exactly
    the kind of inference this codebase refuses to make elsewhere
    (DOCUMENTATION.md §7 rule 2).
    """

    STANDARD = "STANDARD"
    FALL_RISK = "FALL_RISK"
    RESTRICTED_MOBILITY = "RESTRICTED_MOBILITY"


class DeviceAssignment(Base):
    """A period during which one device monitored one patient.

    Append-only in spirit: unassigning sets `unassigned_at` rather than
    deleting, so a reassigned device keeps a resolvable history and old sensor
    events stay attributable to the patient they actually came from.

    "Active" is DERIVED — `unassigned_at IS NULL` — and is deliberately not a
    stored boolean. A stored flag would be a second source of truth that can
    drift out of step with the timestamp, and there would be no way to tell
    which one was right.

    The two invariants (one active assignment per device, one per patient) are
    enforced by partial unique indexes in the database rather than by Python
    checks alone, so two concurrent assignment requests cannot both succeed.
    """

    __tablename__ = "device_assignments"

    __table_args__ = (
        Index(
            "ux_device_assignments_active_device",
            "device_id",
            unique=True,
            postgresql_where=text("unassigned_at IS NULL"),
        ),
        Index(
            "ux_device_assignments_active_patient",
            "patient_id",
            unique=True,
            postgresql_where=text("unassigned_at IS NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    device_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("wearable_devices.id"), nullable=False, index=True
    )
    patient_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("patients.id"), nullable=False, index=True
    )
    # Context only. Recorded so an event can be tied to the visit it happened
    # during, never used to decide whether to monitor. Note Encounter.status and
    # Patient.admission_status are independent, unlinked state machines in this
    # codebase — admission_status is what discharge actually sets, so it is the
    # authority for ending an assignment, not this column.
    encounter_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("encounters.id"), nullable=True
    )

    monitoring_profile: Mapped[MonitoringProfile] = mapped_column(
        SAEnum(MonitoringProfile, name="device_monitoring_profile", native_enum=True),
        nullable=False,
    )

    assigned_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )

    # NULL on both = active. unassigned_by is also NULL when the cascade ended
    # the assignment automatically on discharge, which is recorded as a SYSTEM
    # actor in the audit trail rather than attributed to a clinician.
    unassigned_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    unassigned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SensorEventType(str, enum.Enum):
    """What a device may report.

    DEVICE_OFFLINE is deliberately absent: it is derived by the backend from a
    missing heartbeat, and a device claiming to be offline is a contradiction.
    A device that submits it is rejected."""

    POSSIBLE_FALL = "POSSIBLE_FALL"
    ABNORMAL_MOVEMENT = "ABNORMAL_MOVEMENT"
    UNEXPECTED_MOBILITY = "UNEXPECTED_MOBILITY"
    DEVICE_LOW_BATTERY = "DEVICE_LOW_BATTERY"


class SensorEvent(Base):
    """One candidate event reported by a device.

    Sparse by design. The device does its own signal processing and sends only
    a compact summary when a pattern matches, so this table holds occasional
    rows rather than a raw IMU stream. Heartbeats are NOT stored here — they
    update WearableDevice in place, because a row per device every 30s is
    exactly the historical sensor-data lake this module must not build.

    `assignment_id` is NOT NULL: an event that cannot be attributed to a
    patient is not stored at all (the API answers 202 and discards it). An
    unassigned device should not be producing events in the first place, and
    orphan rows attributable to nobody could never become alerts anyway.

    `metrics` holds motion measurements only, enforced by a strict schema with
    extra fields forbidden — so a buggy or compromised device cannot smuggle
    arbitrary content, including PHI, into the database.
    """

    __tablename__ = "sensor_events"

    __table_args__ = (
        # The idempotency guarantee (MODULE_3_IMPLEMENTATION_PLAN.md §22).
        # Network retries and offline-queue drains resend events freely; this
        # constraint is what makes that safe, rather than relying on callers
        # being careful.
        UniqueConstraint("device_id", "device_event_id", name="ux_sensor_events_device_event"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    device_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("wearable_devices.id"), nullable=False, index=True
    )
    assignment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("device_assignments.id"), nullable=False, index=True
    )

    # Device-supplied, monotonic per device and persisted across reboot. Half of
    # the idempotency key.
    device_event_id: Mapped[str] = mapped_column(String(64), nullable=False)

    event_type: Mapped[SensorEventType] = mapped_column(
        SAEnum(SensorEventType, name="sensor_event_type", native_enum=True), nullable=False, index=True
    )

    # Both timestamps, always. occurred_at is when the device detected it;
    # received_at is when the backend got it. They differ whenever an event was
    # queued through a network outage, and a nurse needs to see which is which.
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )

    metrics: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    # True when occurred_at is far enough behind received_at that the event
    # describes the past rather than the present. A delayed fall still raises an
    # alert — suppressing it would discard a real safety signal — but it must be
    # labelled, or staff would read it as happening now.
    delayed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class AlertType(str, enum.Enum):
    """The five V1 alert types.

    Mostly mirrors SensorEventType, plus DEVICE_OFFLINE — which no device can
    report, because it is derived by the backend from a missing heartbeat
    (Stage 6). Kept as a separate enum rather than reusing SensorEventType
    precisely so that asymmetry is explicit in the type system."""

    POSSIBLE_FALL = "POSSIBLE_FALL"
    ABNORMAL_MOVEMENT = "ABNORMAL_MOVEMENT"
    UNEXPECTED_MOBILITY = "UNEXPECTED_MOBILITY"
    DEVICE_LOW_BATTERY = "DEVICE_LOW_BATTERY"
    DEVICE_OFFLINE = "DEVICE_OFFLINE"


class AlertPriority(str, enum.Enum):
    """OPERATIONAL priority — how soon someone should look — and explicitly
    NOT a clinical severity. Nothing in Module 3 can judge medical acuity, and
    labelling these as clinical severity would be a claim the sensor cannot
    support."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class AlertStatus(str, enum.Enum):
    """Three states, deliberately.

    DISMISSED was considered and rejected: it invites ambiguity about whether
    anyone actually checked the patient. RESOLVED covers "dealt with", and the
    audit trail records who and when."""

    OPEN = "OPEN"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    RESOLVED = "RESOLVED"


class SafetyAlert(Base):
    """Something a nurse needs to look at.

    One alert represents one EPISODE, not one event. Twenty fall-like events in
    three seconds are one fall, so they collapse into a single row with
    event_count incremented (see service.evaluate_event). That collapse is the
    core of this module's alert-fatigue defence: DOCUMENTATION.md §7 rule 6
    says an alert that fires on correct work is itself a safety problem,
    because it teaches people to click through.

    patient_id is denormalised onto the alert deliberately, unlike
    SensorEvent which resolves the patient through its assignment. An alert is
    a permanent record of who was alerted about, and it must stay answerable
    even if assignment history is later reorganised — whereas an event is raw
    input whose attribution should follow the assignment it arrived under.
    """

    __tablename__ = "safety_alerts"

    __table_args__ = (
        # The nurse dashboard's only hot query: open alerts, newest first.
        Index("ix_safety_alerts_status_created", "status", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    patient_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("patients.id"), nullable=False, index=True
    )
    device_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("wearable_devices.id"), nullable=False, index=True
    )
    # The event that opened the episode. NULL for DEVICE_OFFLINE, which is
    # derived from the absence of data rather than from an event.
    sensor_event_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sensor_events.id"), nullable=True
    )

    alert_type: Mapped[AlertType] = mapped_column(
        SAEnum(AlertType, name="safety_alert_type", native_enum=True), nullable=False, index=True
    )
    priority: Mapped[AlertPriority] = mapped_column(
        SAEnum(AlertPriority, name="safety_alert_priority", native_enum=True), nullable=False
    )
    status: Mapped[AlertStatus] = mapped_column(
        SAEnum(AlertStatus, name="safety_alert_status", native_enum=True),
        default=AlertStatus.OPEN,
        nullable=False,
        index=True,
    )

    # How many events folded into this episode, and when the last one arrived.
    # Without these the dedupe would silently discard information: a nurse
    # seeing "14 fall-like events over 40 seconds" knows more than one seeing
    # a bare alert, and it makes the collapse observable rather than invisible.
    event_count: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    last_event_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # True if the opening event was a delayed delivery. Carried onto the alert
    # so the UI can say so without joining back to the event.
    delayed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False, index=True
    )
    acknowledged_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
