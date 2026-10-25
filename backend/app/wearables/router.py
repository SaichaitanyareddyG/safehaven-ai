"""Staff-facing device registry (clinician JWT).

Scope is deliberately "enough to run a ward", not device fleet management:
register, list, re-issue an enrolment code, revoke. No firmware distribution,
no grouping, no bulk provisioning.

Authorisation note: every route here uses `get_current_user` with no role
check, because no role check exists anywhere in this codebase — `User.role` is
stored and never branched on. So any authenticated clinician can register or
revoke a device. That matches current behaviour elsewhere in the app rather
than inventing the first RBAC here, and it is recorded as a known gap
(MODULE_3_IMPLEMENTATION_PLAN.md decision D8).
"""

import uuid
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user, require_admin
from app.auth.provider import AuthenticatedUser
from app.core.db import get_db
from app.core.rate_limit import limiter
from app.patients.service import PatientNotFoundError
from app.audit.models import ActorType, AuditEventType
from app.audit.service import record_event
from app.wearables import firmware, service, wifi
from app.wearables.models import AlertStatus, WearableDevice
from app.wearables.schemas import (
    DeviceAssignmentCreate,
    DeviceAssignmentRead,
    PairDeviceRequest,
    PatientAssignmentResponse,
    QrResolveRequest,
    QrResolveResponse,
    SafetyAlertListResponse,
    SafetyAlertRead,
    SensorEventListResponse,
    SensorEventRead,
    WearableDeviceCreate,
    WearableDeviceListResponse,
    WearableDeviceRead,
    WearableDeviceRegistered,
    WifiNetworkCreate,
    WifiNetworkListResponse,
    WifiNetworkRead,
)

router = APIRouter(tags=["wearable-devices"])


@router.post(
    "/wearable-devices", response_model=WearableDeviceRegistered, status_code=status.HTTP_201_CREATED
)
def register_device(
    payload: WearableDeviceCreate,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> WearableDeviceRegistered:
    """Register a physical device and return its one-time enrolment code."""
    try:
        device, enrollment_code = service.register_device(
            db, payload, created_by=uuid.UUID(current_user.id)
        )
    except service.DuplicateDeviceCodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A device with that code already exists",
        ) from exc

    assert device.enrollment_expires_at is not None  # just set by register_device
    return WearableDeviceRegistered(
        device=service.to_read(device),
        enrollment_code=enrollment_code,
        enrollment_expires_at=device.enrollment_expires_at,
    )


@router.get("/wearable-devices", response_model=WearableDeviceListResponse)
def list_devices(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> WearableDeviceListResponse:
    # Refresh derived offline state before reporting the fleet, so this view
    # and the alert queue never disagree about which devices are silent.
    service.sweep_offline_devices(db)
    devices = service.list_devices(db)

    def newer(device):
        release = firmware.newer_release(db, device.firmware_version) if device.firmware_version else None
        return release.version if release else None

    return WearableDeviceListResponse(
        total=len(devices),
        results=[service.to_read(device, assignment, newer(device)) for device, assignment in devices],
    )


@router.post("/wearable-devices/{device_id}/update-now", response_model=WearableDeviceRead)
def request_update_now(
    device_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> WearableDeviceRead:
    """Let this band install the published firmware off its charger, at its
    next check-in (30%+ battery). Valid for 2 hours."""
    device = db.get(WearableDevice, device_id)
    if device is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found")
    release = firmware.newer_release(db, device.firmware_version)
    if release is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This band already runs the latest firmware")
    device.update_requested_at = datetime.now(timezone.utc)
    record_event(
        db,
        event_type=AuditEventType.WEARABLE_UPDATE_REQUESTED,
        actor_type=ActorType.CLINICIAN,
        actor_id=uuid.UUID(current_user.id),
        entity_type="WearableDevice",
        entity_id=device.id,
        event_metadata={"to": release.version},
    )
    db.commit()
    assignment = service.active_assignment_for_device(db, device.id)
    return service.to_read(device, assignment, release.version)


@router.post("/wearable-devices/{device_id}/enrollment-code", response_model=WearableDeviceRegistered)
def reissue_enrollment_code(
    device_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> WearableDeviceRegistered:
    """Mint a fresh enrolment code.

    Needed because `device_code` is unique, so a lost code cannot be resolved
    by re-registering the same physical device.
    """
    try:
        device, enrollment_code = service.reissue_enrollment_code(
            db, device_id, actor_id=uuid.UUID(current_user.id)
        )
    except service.DeviceNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found") from exc
    except service.InvalidEnrollmentCodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Device is retired and cannot be enrolled",
        ) from exc

    assert device.enrollment_expires_at is not None
    return WearableDeviceRegistered(
        device=service.to_read(device),
        enrollment_code=enrollment_code,
        enrollment_expires_at=device.enrollment_expires_at,
    )


@router.post("/wearable-devices/{device_id}/revoke", response_model=WearableDeviceRead)
def revoke_device(
    device_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> WearableDeviceRead:
    """Disable a device and destroy its credential. Other devices are unaffected."""
    try:
        device = service.revoke_device(db, device_id, actor_id=uuid.UUID(current_user.id))
    except service.DeviceNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found") from exc
    return service.to_read(device)


# ── assignment ──────────────────────────────────────────────────────────────


@router.get(
    "/patients/{patient_id}/wearable-assignment", response_model=PatientAssignmentResponse
)
def get_patient_assignment(
    patient_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> PatientAssignmentResponse:
    """Current wearable for a patient, or null. Null is the normal case."""
    assignment = service.active_assignment_for_patient(db, patient_id)
    if assignment is None:
        return PatientAssignmentResponse(assignment=None)
    return PatientAssignmentResponse(assignment=service.assignment_to_read(db, assignment))


@router.post(
    "/patients/{patient_id}/wearable-assignment",
    response_model=DeviceAssignmentRead,
    status_code=status.HTTP_201_CREATED,
)
def assign_wearable(
    patient_id: uuid.UUID,
    payload: DeviceAssignmentCreate,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> DeviceAssignmentRead:
    """Assign a device to a patient with an explicit monitoring profile.

    409 covers every "you cannot assign this right now" case — discharged
    patient, patient already monitored, device unenrolled/disabled/taken. The
    reason is returned in the detail because the caller is an authenticated
    clinician who needs to act on it (unlike the device API, where failures are
    deliberately opaque).
    """
    try:
        assignment = service.assign_device(
            db, patient_id, payload, assigned_by=uuid.UUID(current_user.id)
        )
    except PatientNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Patient not found") from exc
    except service.DeviceNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found") from exc
    except (service.DeviceNotAssignableError, service.PatientNotAssignableError) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return service.assignment_to_read(db, assignment)


@router.delete(
    "/patients/{patient_id}/wearable-assignment", response_model=DeviceAssignmentRead
)
def unassign_wearable(
    patient_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> DeviceAssignmentRead:
    """End monitoring and return the device to the pool.

    The device learns of this on its next heartbeat and drops to its safe
    unassigned state.
    """
    try:
        assignment = service.unassign_device(
            db, patient_id, unassigned_by=uuid.UUID(current_user.id)
        )
    except service.AssignmentNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Patient has no assigned wearable"
        ) from exc
    return service.assignment_to_read(db, assignment)


@router.get("/patients/{patient_id}/safety-events", response_model=SensorEventListResponse)
def list_patient_safety_events(
    patient_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> SensorEventListResponse:
    """Newest-first event history for a patient, across every device they have
    worn.

    Resolved by joining through assignments rather than storing patient_id on
    the event, so a reassigned device's old events stay attributed to the
    patient they actually came from.
    """
    events = service.list_patient_sensor_events(db, patient_id)
    return SensorEventListResponse(
        total=len(events), results=[SensorEventRead.model_validate(e) for e in events]
    )


# ── alerts ──────────────────────────────────────────────────────────────────


@router.get("/safety-alerts", response_model=SafetyAlertListResponse)
def list_safety_alerts(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    status_filter: Annotated[list[AlertStatus] | None, Query(alias="status")] = None,
) -> SafetyAlertListResponse:
    """The cross-patient alert queue.

    This is the endpoint the nurse dashboard polls (decision D1: polling, not
    WebSocket/SSE, because in-process push silently drops alerts under more
    than one uvicorn worker and Redis is not available to fan out). It is also
    the fix for the "cross-patient alert queue" that DOCUMENTATION.md §13 calls
    the single biggest remaining usability gap.

    Defaults to live alerts only — OPEN and ACKNOWLEDGED. A dashboard showing
    resolved alerts by default would bury the ones needing action, which is how
    alert fatigue starts.

    Ordered by priority then recency, so a possible fall never sits below a low
    battery whatever their timestamps.
    """
    # THE POLL IS THE SWEEP. There is no scheduler in this codebase, so
    # newly-silent devices are detected here, on the read that the nurse
    # dashboard performs every few seconds (see service.sweep_offline_devices
    # for the trade-off this accepts).
    service.sweep_offline_devices(db)

    statuses = status_filter or [AlertStatus.OPEN, AlertStatus.ACKNOWLEDGED]
    alerts = service.list_alerts(db, statuses=statuses)
    return SafetyAlertListResponse(
        total=len(alerts), results=[service.alert_to_read(db, a) for a in alerts]
    )


@router.post("/safety-alerts/{alert_id}/acknowledge", response_model=SafetyAlertRead)
def acknowledge_safety_alert(
    alert_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> SafetyAlertRead:
    """Record that a human has seen this and is acting on it."""
    try:
        alert = service.acknowledge_alert(db, alert_id, actor_id=uuid.UUID(current_user.id))
    except service.AlertNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Alert not found") from exc
    except service.AlertTransitionError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return service.alert_to_read(db, alert)


@router.post("/safety-alerts/{alert_id}/resolve", response_model=SafetyAlertRead)
def resolve_safety_alert(
    alert_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> SafetyAlertRead:
    """Close the alert out. Allowed directly from OPEN — requiring an
    acknowledge first would add a click with no safety value."""
    try:
        alert = service.resolve_alert(db, alert_id, actor_id=uuid.UUID(current_user.id))
    except service.AlertNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Alert not found") from exc
    return service.alert_to_read(db, alert)


# A scanner in a nurse's hand resolves one band at a time; this limit only
# exists to stop anyone iterating the token space with a stolen session.
_QR_RESOLVE_RATE_LIMIT = "30/minute"


@router.post("/wearable-assignments/resolve", response_model=QrResolveResponse)
@limiter.limit(_QR_RESOLVE_RATE_LIMIT)
def resolve_wearable_qr(
    request: Request,
    payload: QrResolveRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> QrResolveResponse:
    """Which patient wears the band whose QR was just scanned.

    Clinician JWT only — the QR itself means nothing to anyone else. One
    generic 404 covers unknown, malformed and ended tokens alike.
    """
    try:
        assignment, patient, device = service.resolve_qr_token(
            db, payload.token, resolved_by=uuid.UUID(current_user.id)
        )
    except service.QrTokenNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="This band is not currently assigned to a patient",
        ) from exc
    return QrResolveResponse(
        patient_id=patient.id,
        patient_code=patient.patient_code,
        patient_name=f"{patient.first_name} {patient.last_name}",
        room_number=patient.room_number,
        device_code=device.device_code,
        monitoring_profile=assignment.monitoring_profile,
        assigned_at=assignment.assigned_at,
    )


@router.post(
    "/wearable-devices/pair", response_model=WearableDeviceRead, status_code=status.HTTP_201_CREATED
)
def pair_device(
    payload: PairDeviceRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> WearableDeviceRead:
    """Add the band whose screen shows `pairing_code`, under the label on its case.

    The band finishes enrolling by itself within a few seconds — no enrolment
    code is shown to anyone, and no USB or terminal is involved.
    """
    try:
        device = service.approve_pairing(
            db, payload.pairing_code, payload.device_code, approved_by=uuid.UUID(current_user.id)
        )
    except service.PairingNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No band is showing that code. Codes change every 10 minutes - check the band's screen.",
        ) from exc
    except service.DuplicateDeviceCodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="A device with that label already exists"
        ) from exc
    return service.to_read(device)


# Wi-Fi networks for every band. Admins only: these are the hospital's Wi-Fi
# passwords. They go to the bands and are never shown again.
Admin = Annotated[AuthenticatedUser, Depends(require_admin)]


@router.get("/wifi-networks", response_model=WifiNetworkListResponse)
def list_wifi_networks(db: Annotated[Session, Depends(get_db)], admin: Admin) -> WifiNetworkListResponse:
    return WifiNetworkListResponse(
        items=[WifiNetworkRead.model_validate(n) for n in wifi.list_networks(db)], version=wifi.version(db)
    )


@router.post("/wifi-networks", response_model=WifiNetworkRead, status_code=status.HTTP_201_CREATED)
def add_wifi_network(
    payload: WifiNetworkCreate, db: Annotated[Session, Depends(get_db)], admin: Admin
) -> WifiNetworkRead:
    """Every band picks it up at its next check-in (within about 5 minutes)."""
    try:
        network = wifi.add_network(
            db,
            uuid.UUID(admin.id),
            label=payload.label,
            ssid=payload.ssid,
            security=payload.security,
            password=payload.password,
            username=payload.username,
            identity=payload.identity,
        )
    except wifi.WifiError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    record_event(
        db,
        event_type=AuditEventType.WIFI_NETWORK_ADDED,
        actor_type=ActorType.CLINICIAN,
        actor_id=uuid.UUID(admin.id),
        entity_type="WifiNetwork",
        entity_id=network.id,
        event_metadata={"ssid": network.ssid, "security": network.security},
    )
    db.commit()
    return WifiNetworkRead.model_validate(network)


@router.delete("/wifi-networks/{network_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_wifi_network(network_id: uuid.UUID, db: Annotated[Session, Depends(get_db)], admin: Admin) -> None:
    network = wifi.remove_network(db, network_id)
    if network is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such network")
    record_event(
        db,
        event_type=AuditEventType.WIFI_NETWORK_REMOVED,
        actor_type=ActorType.CLINICIAN,
        actor_id=uuid.UUID(admin.id),
        entity_type="WifiNetwork",
        entity_id=network.id,
        event_metadata={"ssid": network.ssid},
    )
    db.commit()
