import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.wearables.models import DeviceStatus, MonitoringProfile

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


# ── assignment (staff) ──────────────────────────────────────────────────────


class DeviceAssignmentCreate(BaseModel):
    device_id: uuid.UUID
    # Required with no default, on purpose. Defaulting to STANDARD would let a
    # caller silently get the wrong monitoring behaviour; defaulting to
    # RESTRICTED_MOBILITY would enable an inferential detector nobody asked
    # for. Staff must say which.
    monitoring_profile: MonitoringProfile


class DeviceAssignmentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    device_id: uuid.UUID
    device_code: str
    patient_id: uuid.UUID
    encounter_id: uuid.UUID | None
    monitoring_profile: MonitoringProfile
    assigned_at: datetime
    unassigned_at: datetime | None

    # Live device health, joined in so the assignment panel is one request.
    battery_percent: int | None
    last_seen_at: datetime | None
    device_status: DeviceStatus

    @property
    def active(self) -> bool:
        return self.unassigned_at is None


class PatientAssignmentResponse(BaseModel):
    """`assignment` is null when the patient has no wearable — which is the
    normal case, not an error."""

    assignment: DeviceAssignmentRead | None


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


class DeviceAssignmentView(BaseModel):
    """The ONLY assignment information a device is ever given.

    Note what is absent, and must stay absent: patient_id, patient_code, name,
    DOB, room, diagnosis, medications. The device needs to know *how* to
    monitor, never *who* it is monitoring — the backend resolves
    device -> active assignment -> patient on its own. Keeping this view
    minimal is what makes the wearable's radio traffic PHI-free
    (MODULE_3_IMPLEMENTATION_PLAN.md §19).
    """

    assignment_id: uuid.UUID
    monitoring_profile: MonitoringProfile
    # Echoed so the device can detect a reassignment it missed and reset its
    # detectors rather than carrying state across two different patients.
    assigned_at_ms: int


class DeviceHeartbeatResponse(BaseModel):
    """What the device learns by checking in.

    The heartbeat response is how assignment changes reach the device: the
    device polls, the backend answers. That is why no server-to-device push
    channel — and therefore no MQTT broker — is needed.

    `assignment` is null when the device is unassigned, which the firmware
    treats as a safe idle state: an unassigned device generates no patient
    events at all."""

    server_time_ms: int
    assignment: DeviceAssignmentView | None = None
