import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, Enum as SAEnum, ForeignKey, SmallInteger, String
from sqlalchemy.dialects.postgresql import UUID
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
