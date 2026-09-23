import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.wearables.models import DeviceStatus

# ── staff-facing (clinician JWT) ────────────────────────────────────────────


class WearableDeviceCreate(BaseModel):
    # Staff-supplied, because it has to match the label physically on the
    # hardware. Unlike patient_code, this is not server-generated.
    device_code: str = Field(min_length=3, max_length=32)


class WearableDeviceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    device_code: str
    status: DeviceStatus
    hardware_id: str | None
    firmware_version: str | None
    battery_percent: int | None
    last_seen_at: datetime | None
    created_at: datetime

    # Derived, never stored: a device is enrolled iff it holds a credential.
    # Storing a flag as well would be a second source of truth that can
    # disagree with the hash column.
    enrolled: bool


class WearableDeviceListResponse(BaseModel):
    total: int
    results: list[WearableDeviceRead]


class WearableDeviceRegistered(BaseModel):
    """Response to registration. `enrollment_code` is shown ONCE — it is stored
    only as a hash and cannot be recovered. Re-issue it if lost."""

    device: WearableDeviceRead
    enrollment_code: str
    enrollment_expires_at: datetime


# ── device-facing (per-device credential) ───────────────────────────────────


class DeviceEnrollRequest(BaseModel):
    enrollment_code: str = Field(min_length=6, max_length=64)
    # eFuse identifier. Recorded so a credential is traceable to specific
    # silicon; not trusted as authentication on its own.
    hardware_id: str = Field(min_length=3, max_length=64)


class DeviceEnrollResponse(BaseModel):
    """`device_secret` is returned exactly once, at enrolment, and never again.

    The device writes it to encrypted NVS. If it is lost the device must be
    re-enrolled — which is the intended failure mode, because the alternative
    is a recoverable secret."""

    device_id: uuid.UUID
    device_code: str
    device_secret: str


class DeviceHeartbeatRequest(BaseModel):
    battery_percent: int = Field(ge=0, le=100)
    firmware_version: str = Field(min_length=1, max_length=32)
    # Signal strength and queue depth are diagnostics, not safety signals.
    rssi: int | None = Field(default=None, ge=-120, le=0)
    sensor_ok: bool = True
    queue_depth: int = Field(default=0, ge=0)


class DeviceHeartbeatResponse(BaseModel):
    """What the device learns by checking in.

    `assignment` is null in Stage 1 — assignment lands in Stage 2. The field
    exists now because the heartbeat response is how assignment changes reach
    the device at all: the device polls, the backend answers. That avoids
    needing any server-to-device push channel (and therefore avoids MQTT).

    Note what is absent: no patient name, no patient_code, no room, no
    diagnosis. A device never learns who it is monitoring."""

    server_time_ms: int
    assignment: dict | None = None
