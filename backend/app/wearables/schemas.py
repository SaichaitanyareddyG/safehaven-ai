import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.wearables.models import DeviceStatus, MonitoringProfile, SensorEventType

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


class SensorEventRead(BaseModel):
    """Staff-facing view of a reported event.

    Both timestamps are exposed, plus `delayed`, because a nurse reading the
    history needs to know whether an event describes now or fifteen minutes
    ago."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    device_id: uuid.UUID
    assignment_id: uuid.UUID
    event_type: SensorEventType
    occurred_at: datetime
    received_at: datetime
    delayed: bool
    metrics: dict


class SensorEventListResponse(BaseModel):
    total: int
    results: list[SensorEventRead]


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


class SensorEventMetrics(BaseModel):
    """Motion measurements only, and nothing else.

    `extra="forbid"` is a deliberate safety control, not strictness for its own
    sake: it means a buggy or compromised device cannot put arbitrary content —
    including patient data — into the metrics JSONB. Anything outside this
    whitelist is a 422.

    Field names and ranges mirror firmware/include/core/EventJson.h exactly. If
    one changes, both change.
    """

    model_config = ConfigDict(extra="forbid")

    # Fall evidence (§13). The stage flags are what produced fall_score, kept so
    # the basis for an alert stays inspectable rather than being a bare boolean.
    fall_score: int = Field(default=0, ge=0, le=4)
    peak_g: float = Field(default=0.0, ge=0.0, le=64.0)
    tilt_delta_deg: float = Field(default=0.0, ge=0.0, le=180.0)
    freefall_ms: int = Field(default=0, ge=0, le=60_000)
    inactive_ms: int = Field(default=0, ge=0, le=3_600_000)
    stages_seen: list[Literal["freefall", "impact", "orientation", "inactivity"]] = Field(
        default_factory=list, max_length=4
    )

    # Movement / mobility evidence (§14, §15)
    duration_s: float = Field(default=0.0, ge=0.0, le=86_400.0)
    dom_freq_hz: float = Field(default=0.0, ge=0.0, le=100.0)
    magnitude: float = Field(default=0.0, ge=0.0, le=64.0)
    periodicity: float = Field(default=0.0, ge=-1.0, le=1.0)


class SensorEventSubmit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Monotonic per device, persisted across reboot. Half of the idempotency
    # key; the backend supplies the other half from the authenticated device.
    device_event_id: str = Field(min_length=1, max_length=64)
    event_type: SensorEventType
    # Epoch milliseconds, converted from the device's monotonic clock at send
    # time so a queued event keeps its true detection time.
    occurred_at_ms: int = Field(ge=0)

    # Optional. A device that knows which assignment it was running when it
    # detected the event lets the backend attribute an event that was queued
    # through an outage and delivered after the assignment ended. Without it,
    # such an event would be discarded — losing a real fall. Always verified
    # against the authenticated device, so a device cannot claim another's
    # assignment.
    assignment_id: uuid.UUID | None = None

    battery_percent: int | None = Field(default=None, ge=0, le=100)
    firmware_version: str | None = Field(default=None, max_length=32)
    metrics: SensorEventMetrics = Field(default_factory=SensorEventMetrics)


class SensorEventAccepted(BaseModel):
    """What the device learns about its submission.

    `outcome` matters to the firmware's offline queue: CREATED and DUPLICATE
    both mean "stop retrying, it is safely delivered". DISCARDED means the
    backend had nowhere to attribute it, and retrying will not help either.
    """

    outcome: Literal["CREATED", "DUPLICATE", "DISCARDED"]
    event_id: uuid.UUID | None = None
    delayed: bool = False


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
