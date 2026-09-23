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
    WearableDevice,
)
from app.wearables.schemas import (
    DeviceAssignmentCreate,
    DeviceAssignmentRead,
    DeviceHeartbeatRequest,
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
