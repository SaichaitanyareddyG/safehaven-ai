"""Device registry, enrolment and credential verification.

Security model in one paragraph (MODULE_3_IMPLEMENTATION_PLAN.md §9): each
physical wearable gets its own high-entropy secret, stored only as a SHA-256
hash, handed over exactly once, and individually revocable. There is no global
API key baked into firmware, and no JWT — the JWTs this app issues have no
denylist and cannot be revoked, which is disqualifying for hardware that can be
lost or stolen. Compromise of one device must never require re-crediting the
fleet.

This is a near-copy of app/patient_access/service.py's token handling. That is
deliberate: it is the same problem (an unguessable secret held by something at
the bedside that is not a logged-in clinician) and reusing the shape keeps one
audited pattern in the codebase instead of two.
"""

import hashlib
import logging
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.audit.models import ActorType, AuditEventType
from app.audit.service import record_event
from app.core.config import get_settings
from app.encounters.models import Encounter, EncounterStatus
from app.patients.models import AdmissionStatus
from app.patients.service import get_patient
from app.wearables.models import (
    DeviceAssignment,
    DeviceStatus,
    MonitoringProfile,
    SensorEvent,
    WearableDevice,
)
from app.wearables.schemas import (
    DeviceAssignmentCreate,
    DeviceAssignmentRead,
    DeviceHeartbeatRequest,
    SensorEventSubmit,
    WearableDeviceCreate,
    WearableDeviceRead,
)

logger = logging.getLogger(__name__)

SECRET_BYTES = 32  # 256 bits, same strength as the patient care-link token

# Enrolment codes are typed by a human into the device's provisioning portal,
# so they are short and drawn from an alphabet with no 0/O or 1/I/L confusions.
# Short lifetime and single use is what keeps them safe, not length.
_ENROLLMENT_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
_ENROLLMENT_LENGTH = 10

# How far ahead of the server a device's clock may be before we stop believing
# it. Small, because the only legitimate source of forward skew is SNTP jitter;
# anything larger is a broken clock, and a future-dated event would pin itself
# to the top of a time-ordered nurse queue.
_FUTURE_SKEW_TOLERANCE_S = 60


class DeviceNotFoundError(Exception):
    pass


class DuplicateDeviceCodeError(Exception):
    pass


class InvalidEnrollmentCodeError(Exception):
    """Raised uniformly for "no such code" / "expired" / "already used" /
    "device disabled". The HTTP layer must not let a caller tell these apart —
    same reasoning as InvalidCareAccessTokenError."""


class AssignmentNotFoundError(Exception):
    pass


class DeviceNotAssignableError(Exception):
    """Device is disabled, retired, not yet enrolled, or already assigned to
    someone else. Unlike the credential errors, this one IS safe to explain —
    the caller is an authenticated clinician who needs to know why."""


class PatientNotAssignableError(Exception):
    """Patient is discharged, or already has a wearable."""


class InvalidDeviceCredentialError(Exception):
    """Raised uniformly for "no such credential" / "device disabled" /
    "device retired". Deliberately carries no distinguishing detail: knowing
    *why* a credential failed is useful to an attacker probing device ids and
    useless to a legitimate device, which can only re-enrol either way."""


def _hash(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _new_enrollment_code() -> str:
    return "".join(secrets.choice(_ENROLLMENT_ALPHABET) for _ in range(_ENROLLMENT_LENGTH))


def to_read(device: WearableDevice) -> WearableDeviceRead:
    return WearableDeviceRead(
        id=device.id,
        device_code=device.device_code,
        status=device.status,
        hardware_id=device.hardware_id,
        firmware_version=device.firmware_version,
        battery_percent=device.battery_percent,
        last_seen_at=device.last_seen_at,
        created_at=device.created_at,
        enrolled=device.credential_hash is not None,
    )


# ── staff operations ────────────────────────────────────────────────────────


def register_device(
    db: Session, data: WearableDeviceCreate, created_by: uuid.UUID
) -> tuple[WearableDevice, str]:
    """Create the device record and mint its single-use enrolment code.

    Returns (device, raw_enrollment_code). The raw code is available only here.
    """
    code = data.device_code.strip().upper()
    raw_enrollment = _new_enrollment_code()
    ttl = get_settings().device_enrollment_ttl_minutes

    device = WearableDevice(
        device_code=code,
        status=DeviceStatus.ACTIVE,
        enrollment_code_hash=_hash(raw_enrollment),
        enrollment_expires_at=datetime.now(timezone.utc) + timedelta(minutes=ttl),
        created_by=created_by,
    )
    db.add(device)
    try:
        db.flush()  # assigns device.id, and surfaces the unique-code collision
    except IntegrityError as exc:
        db.rollback()
        raise DuplicateDeviceCodeError(code) from exc

    record_event(
        db,
        event_type=AuditEventType.WEARABLE_DEVICE_REGISTERED,
        actor_type=ActorType.CLINICIAN,
        actor_id=created_by,
        entity_type="WearableDevice",
        entity_id=device.id,
        event_metadata={"device_code": code, "enrollment_ttl_minutes": ttl},
    )

    db.commit()
    db.refresh(device)
    return device, raw_enrollment


def reissue_enrollment_code(
    db: Session, device_id: uuid.UUID, actor_id: uuid.UUID
) -> tuple[WearableDevice, str]:
    """Mint a fresh enrolment code for a device that is not yet enrolled, or
    that needs re-enrolling after revocation.

    Needed because device_code is unique, so a lost enrolment code cannot be
    resolved by simply registering the device again.
    """
    device = get_device(db, device_id)
    if device.status is DeviceStatus.RETIRED:
        raise InvalidEnrollmentCodeError("retired")

    raw_enrollment = _new_enrollment_code()
    ttl = get_settings().device_enrollment_ttl_minutes
    device.enrollment_code_hash = _hash(raw_enrollment)
    device.enrollment_expires_at = datetime.now(timezone.utc) + timedelta(minutes=ttl)

    record_event(
        db,
        event_type=AuditEventType.WEARABLE_DEVICE_REGISTERED,
        actor_type=ActorType.CLINICIAN,
        actor_id=actor_id,
        entity_type="WearableDevice",
        entity_id=device.id,
        event_metadata={"device_code": device.device_code, "reissued": True},
    )
    db.commit()
    db.refresh(device)
    return device, raw_enrollment


def get_device(db: Session, device_id: uuid.UUID) -> WearableDevice:
    device = db.query(WearableDevice).filter(WearableDevice.id == device_id).first()
    if device is None:
        raise DeviceNotFoundError(str(device_id))
    return device


def list_devices(db: Session) -> list[WearableDevice]:
    return db.query(WearableDevice).order_by(WearableDevice.device_code).all()


def revoke_device(db: Session, device_id: uuid.UUID, actor_id: uuid.UUID) -> WearableDevice:
    """Disable a device and destroy its credential.

    Clearing credential_hash rather than only flipping status means a leaked
    secret is worthless immediately, even if some future code path forgets to
    check status. Other devices are untouched — that independence is the whole
    point of per-device credentials.
    """
    device = get_device(db, device_id)
    device.status = DeviceStatus.DISABLED
    device.credential_hash = None
    device.enrollment_code_hash = None
    device.enrollment_expires_at = None

    record_event(
        db,
        event_type=AuditEventType.WEARABLE_DEVICE_REVOKED,
        actor_type=ActorType.CLINICIAN,
        actor_id=actor_id,
        entity_type="WearableDevice",
        entity_id=device.id,
        event_metadata={"device_code": device.device_code},
    )
    db.commit()
    db.refresh(device)
    return device


# ── device operations ───────────────────────────────────────────────────────


def enroll_device(db: Session, enrollment_code: str, hardware_id: str) -> tuple[WearableDevice, str]:
    """Exchange a single-use enrolment code for the device's permanent secret.

    Returns (device, raw_device_secret). The secret is returned exactly once;
    only its hash is persisted.
    """
    code_hash = _hash(enrollment_code.strip().upper())
    device = (
        db.query(WearableDevice)
        .filter(WearableDevice.enrollment_code_hash == code_hash)
        .first()
    )
    if device is None:
        logger.warning("Device enrolment attempted with an unrecognised code.")
        raise InvalidEnrollmentCodeError("not found")
    if device.status is not DeviceStatus.ACTIVE:
        logger.warning("Device enrolment attempted for a non-active device.")
        raise InvalidEnrollmentCodeError("not active")
    if device.enrollment_expires_at is None or device.enrollment_expires_at < datetime.now(timezone.utc):
        logger.warning("Device enrolment attempted with an expired code.")
        raise InvalidEnrollmentCodeError("expired")

    raw_secret = secrets.token_urlsafe(SECRET_BYTES)
    device.credential_hash = _hash(raw_secret)
    device.hardware_id = hardware_id.strip()
    # Consume the code so it can never enrol a second device.
    device.enrollment_code_hash = None
    device.enrollment_expires_at = None

    record_event(
        db,
        event_type=AuditEventType.WEARABLE_DEVICE_ENROLLED,
        actor_type=ActorType.SYSTEM,
        entity_type="WearableDevice",
        entity_id=device.id,
        # hardware_id is device identity, not patient data. The secret and its
        # hash are never recorded — record_event's own rule.
        event_metadata={"device_code": device.device_code, "hardware_id": device.hardware_id},
    )
    db.commit()
    db.refresh(device)
    return device, raw_secret


def authenticate_device(db: Session, raw_secret: str) -> WearableDevice:
    """Resolve a bearer secret to its device, or raise.

    Every rejection path raises the same exception with no detail, and the HTTP
    layer turns all of them into one identical 401.
    """
    device = (
        db.query(WearableDevice)
        .filter(WearableDevice.credential_hash == _hash(raw_secret))
        .first()
    )
    if device is None:
        logger.warning("Device API called with a credential matching no device.")
        raise InvalidDeviceCredentialError("not found")
    if device.status is not DeviceStatus.ACTIVE:
        logger.warning("Device API called by a non-active device.")
        raise InvalidDeviceCredentialError("not active")
    return device


# ── assignment ──────────────────────────────────────────────────────────────


def active_assignment_for_device(db: Session, device_id: uuid.UUID) -> DeviceAssignment | None:
    return (
        db.query(DeviceAssignment)
        .filter(
            DeviceAssignment.device_id == device_id,
            DeviceAssignment.unassigned_at.is_(None),
        )
        .first()
    )


def active_assignment_for_patient(db: Session, patient_id: uuid.UUID) -> DeviceAssignment | None:
    return (
        db.query(DeviceAssignment)
        .filter(
            DeviceAssignment.patient_id == patient_id,
            DeviceAssignment.unassigned_at.is_(None),
        )
        .first()
    )


def assignment_to_read(db: Session, assignment: DeviceAssignment) -> DeviceAssignmentRead:
    device = get_device(db, assignment.device_id)
    return DeviceAssignmentRead(
        id=assignment.id,
        device_id=assignment.device_id,
        device_code=device.device_code,
        patient_id=assignment.patient_id,
        encounter_id=assignment.encounter_id,
        monitoring_profile=assignment.monitoring_profile,
        assigned_at=assignment.assigned_at,
        unassigned_at=assignment.unassigned_at,
        battery_percent=device.battery_percent,
        last_seen_at=device.last_seen_at,
        device_status=device.status,
    )


def assign_device(
    db: Session, patient_id: uuid.UUID, data: DeviceAssignmentCreate, assigned_by: uuid.UUID
) -> DeviceAssignment:
    """Start monitoring a patient with a specific device and profile.

    Refuses in four cases, each for a safety reason rather than tidiness:
      • patient discharged — monitoring someone who has left is meaningless
      • patient already has a device — two monitors means two alert streams
        for one person, and no way to tell which is authoritative
      • device not enrolled — it has no credential, so it can never report
        anything; assigning it would create a false impression of monitoring
      • device disabled/retired, or already on another patient
    """
    patient = get_patient(db, patient_id)  # raises PatientNotFoundError
    if patient.admission_status is not AdmissionStatus.ACTIVE:
        raise PatientNotAssignableError("patient is discharged")
    if active_assignment_for_patient(db, patient_id) is not None:
        raise PatientNotAssignableError("patient already has an assigned wearable")

    device = get_device(db, data.device_id)  # raises DeviceNotFoundError
    if device.status is not DeviceStatus.ACTIVE:
        raise DeviceNotAssignableError(f"device is {device.status.value}")
    if device.credential_hash is None:
        raise DeviceNotAssignableError("device is not enrolled")
    if active_assignment_for_device(db, device.id) is not None:
        raise DeviceNotAssignableError("device is already assigned to another patient")

    # Context only — the visit this monitoring happened during. Absence of an
    # open encounter is not a reason to refuse: encounters and admission status
    # are separate, unlinked state machines here, and admission status is what
    # actually gates monitoring.
    open_encounter = (
        db.query(Encounter)
        .filter(Encounter.patient_id == patient_id, Encounter.status == EncounterStatus.OPEN)
        .order_by(Encounter.admission_date.desc())
        .first()
    )

    assignment = DeviceAssignment(
        device_id=device.id,
        patient_id=patient_id,
        encounter_id=open_encounter.id if open_encounter else None,
        monitoring_profile=data.monitoring_profile,
        assigned_by=assigned_by,
    )
    db.add(assignment)
    try:
        db.flush()
    except IntegrityError as exc:
        # Lost a race against a concurrent assignment; the partial unique
        # indexes caught what the checks above could not.
        db.rollback()
        raise DeviceNotAssignableError("device or patient was assigned concurrently") from exc

    record_event(
        db,
        event_type=AuditEventType.WEARABLE_DEVICE_ASSIGNED,
        actor_type=ActorType.CLINICIAN,
        actor_id=assigned_by,
        patient_id=patient_id,
        entity_type="DeviceAssignment",
        entity_id=assignment.id,
        event_metadata={
            "device_code": device.device_code,
            "monitoring_profile": data.monitoring_profile.value,
        },
    )
    db.commit()
    db.refresh(assignment)
    return assignment


def unassign_device(
    db: Session, patient_id: uuid.UUID, unassigned_by: uuid.UUID
) -> DeviceAssignment:
    """End the patient's active assignment. Staff-initiated."""
    assignment = active_assignment_for_patient(db, patient_id)
    if assignment is None:
        raise AssignmentNotFoundError(str(patient_id))
    _end_assignment(db, assignment, unassigned_by=unassigned_by, reason="staff_unassigned")
    db.commit()
    db.refresh(assignment)
    return assignment


def end_assignments_for_patient(
    db: Session, patient_id: uuid.UUID, commit: bool = True
) -> list[DeviceAssignment]:
    """End every active assignment for a patient, attributed to SYSTEM.

    Called by the discharge cascade in app/orchestration/patient_ops.py with
    commit=False so the discharge, the unassignment and both audit rows land in
    one transaction — the same contract revoke_all_tokens_for_patient already
    has. A device still believing it monitors a discharged patient is the
    failure this prevents.
    """
    assignments = (
        db.query(DeviceAssignment)
        .filter(
            DeviceAssignment.patient_id == patient_id,
            DeviceAssignment.unassigned_at.is_(None),
        )
        .all()
    )
    for assignment in assignments:
        _end_assignment(db, assignment, unassigned_by=None, reason="patient_discharged")
    if commit:
        db.commit()
    return assignments


def _end_assignment(
    db: Session, assignment: DeviceAssignment, unassigned_by: uuid.UUID | None, reason: str
) -> None:
    """Close out an assignment and audit it.

    unassigned_by is None for the discharge cascade — there is no clinician to
    attribute an automatic action to, so it is recorded as a SYSTEM actor, the
    same convention revoke_all_tokens_for_patient uses.
    """
    device = get_device(db, assignment.device_id)
    assignment.unassigned_at = datetime.now(timezone.utc)
    assignment.unassigned_by = unassigned_by

    record_event(
        db,
        event_type=AuditEventType.WEARABLE_DEVICE_UNASSIGNED,
        actor_type=ActorType.CLINICIAN if unassigned_by else ActorType.SYSTEM,
        actor_id=unassigned_by,
        patient_id=assignment.patient_id,
        entity_type="DeviceAssignment",
        entity_id=assignment.id,
        event_metadata={"device_code": device.device_code, "reason": reason},
    )


# ── event ingestion ─────────────────────────────────────────────────────────


def _resolve_assignment_for_event(
    db: Session, device: WearableDevice, claimed_assignment_id: uuid.UUID | None
) -> DeviceAssignment | None:
    """Work out which assignment an incoming event belongs to.

    Two paths, and the second exists to avoid losing a real safety signal:

    1. The device names an assignment it was running. Accepted even if that
       assignment has since ended — this is the queued-through-an-outage case: a
       fall detected at 10:43, network down, patient unassigned at 10:50, device
       reconnects at 10:55. Attributing it to the assignment it actually
       happened under is correct; discarding it would throw away a fall.
       Always filtered by device_id, so a device cannot claim another's
       assignment.

    2. No claim: fall back to the device's currently active assignment.

    Returns None when neither resolves, and the caller discards the event.
    """
    if claimed_assignment_id is not None:
        return (
            db.query(DeviceAssignment)
            .filter(
                DeviceAssignment.id == claimed_assignment_id,
                DeviceAssignment.device_id == device.id,
            )
            .first()
        )
    return active_assignment_for_device(db, device.id)


def ingest_event(
    db: Session, device: WearableDevice, payload: SensorEventSubmit
) -> tuple[str, SensorEvent | None]:
    """Store one candidate event.

    Returns (outcome, event) where outcome is CREATED, DUPLICATE or DISCARDED.
    Stage 3 stores and attributes events; turning them into nurse alerts is
    Stage 4.
    """
    assignment = _resolve_assignment_for_event(db, device, payload.assignment_id)
    if assignment is None:
        # Nothing to attribute this to. An unassigned device should not be
        # producing patient events at all, so this is a stale queue or a bug —
        # either way there is no patient, and a row attributable to nobody could
        # never become an alert.
        logger.warning(
            "Discarding sensor event from device %s: no resolvable assignment.", device.device_code
        )
        return "DISCARDED", None

    now = datetime.now(timezone.utc)
    occurred_at = datetime.fromtimestamp(payload.occurred_at_ms / 1000.0, tz=timezone.utc)

    # A device with a wrong clock must not be able to date an event in the
    # future: the nurse queue is ordered by time, and a future-dated alert would
    # sort above every genuine one and stay there.
    if occurred_at > now + timedelta(seconds=_FUTURE_SKEW_TOLERANCE_S):
        logger.warning(
            "Device %s reported a future occurred_at; clamping to receipt time.", device.device_code
        )
        occurred_at = now

    delayed = (now - occurred_at) > timedelta(seconds=get_settings().device_delayed_after_seconds)

    existing = (
        db.query(SensorEvent)
        .filter(
            SensorEvent.device_id == device.id,
            SensorEvent.device_event_id == payload.device_event_id,
        )
        .first()
    )
    if existing is not None:
        # Idempotent: a retry or queue drain resent this. No second row, and
        # later no second alert.
        return "DUPLICATE", existing

    event = SensorEvent(
        device_id=device.id,
        assignment_id=assignment.id,
        device_event_id=payload.device_event_id,
        event_type=payload.event_type,
        occurred_at=occurred_at,
        received_at=now,
        metrics=payload.metrics.model_dump(),
        delayed=delayed,
    )
    db.add(event)
    try:
        db.flush()
    except IntegrityError:
        # Lost a race with a concurrent submission of the same event id. The
        # unique constraint is what guarantees this, not the check above.
        db.rollback()
        existing = (
            db.query(SensorEvent)
            .filter(
                SensorEvent.device_id == device.id,
                SensorEvent.device_event_id == payload.device_event_id,
            )
            .first()
        )
        return "DUPLICATE", existing

    # Keep the device's last-known health fresh even when it reports via an
    # event rather than a heartbeat.
    if payload.battery_percent is not None:
        device.battery_percent = payload.battery_percent
    if payload.firmware_version is not None:
        device.firmware_version = payload.firmware_version
    device.last_seen_at = now

    record_event(
        db,
        event_type=AuditEventType.SAFETY_EVENT_RECEIVED,
        actor_type=ActorType.SYSTEM,
        patient_id=assignment.patient_id,
        entity_type="SensorEvent",
        entity_id=event.id,
        # A small structured summary, per record_event's own rule — not the
        # whole metrics blob.
        event_metadata={
            "device_code": device.device_code,
            "sensor_event_type": payload.event_type.value,
            "delayed": delayed,
        },
    )
    db.commit()
    db.refresh(event)
    return "CREATED", event


def list_patient_sensor_events(
    db: Session, patient_id: uuid.UUID, limit: int = 50
) -> list[SensorEvent]:
    """Newest-first history for the patient detail panel.

    Joins through assignments rather than storing patient_id on the event: the
    assignment already owns that fact, and duplicating it would allow the two to
    disagree after a reassignment.
    """
    return (
        db.query(SensorEvent)
        .join(DeviceAssignment, SensorEvent.assignment_id == DeviceAssignment.id)
        .filter(DeviceAssignment.patient_id == patient_id)
        .order_by(SensorEvent.occurred_at.desc())
        .limit(limit)
        .all()
    )


def record_heartbeat(
    db: Session, device: WearableDevice, payload: DeviceHeartbeatRequest
) -> WearableDevice:
    """Update last-known health in place.

    Deliberately not stored as one row per beat: a row per device every 30s
    would be the historical sensor-data lake this module is explicitly not
    building. last_seen_at is all that offline detection needs (Stage 6), and
    it is derived on read rather than swept by a background job.

    No audit event — a heartbeat is not a clinically relevant action, and
    writing one every 30s per device would bury the events that matter.
    """
    device.last_seen_at = datetime.now(timezone.utc)
    device.battery_percent = payload.battery_percent
    device.firmware_version = payload.firmware_version
    db.commit()
    db.refresh(device)
    return device
