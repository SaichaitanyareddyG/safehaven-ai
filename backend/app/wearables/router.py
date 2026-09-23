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
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.auth.provider import AuthenticatedUser
from app.core.db import get_db
from app.patients.service import PatientNotFoundError
from app.wearables import service
from app.wearables.models import AlertStatus
from app.wearables.schemas import (
    DeviceAssignmentCreate,
    DeviceAssignmentRead,
    PatientAssignmentResponse,
    SafetyAlertListResponse,
    SafetyAlertRead,
    SensorEventListResponse,
    SensorEventRead,
    WearableDeviceCreate,
    WearableDeviceListResponse,
    WearableDeviceRead,
    WearableDeviceRegistered,
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
    devices = service.list_devices(db)
    return WearableDeviceListResponse(
        total=len(devices), results=[service.to_read(d) for d in devices]
    )


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
