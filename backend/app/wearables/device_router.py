"""The /device-api surface — the only routes a wearable may call.

Kept in its own router, under its own path prefix, with its own authentication
dependency, so the boundary is visible in the URL and impossible to blur by
accident. Nothing here accepts a clinician JWT, and none of these endpoints
returns patient data: a device never learns who it is monitoring
(MODULE_3_IMPLEMENTATION_PLAN.md §9, §20).
"""

import time
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.rate_limit import limiter
from app.wearables import service
from app.wearables.dependencies import get_current_device
from app.wearables.models import WearableDevice
from app.wearables.schemas import (
    DeviceAssignmentView,
    DeviceEnrollResponse,
    DeviceEnrollRequest,
    DeviceHeartbeatRequest,
    DeviceHeartbeatResponse,
)

router = APIRouter(prefix="/device-api", tags=["wearable-device-api"])

# Enrolment is the one unauthenticated route on this surface, so it is the one
# that needs an IP limit — a short human-typeable code is inherently more
# guessable than a 256-bit secret, and this is what stops someone working
# through the code space. Heartbeats are limited too, generously: they are
# authenticated, but a looping device with a broken backoff should not be able
# to saturate the API either.
_ENROLL_RATE_LIMIT = "10/minute"
_HEARTBEAT_RATE_LIMIT = "120/minute"


@router.post("/enroll", response_model=DeviceEnrollResponse)
@limiter.limit(_ENROLL_RATE_LIMIT)
def enroll(
    request: Request,
    payload: DeviceEnrollRequest,
    db: Annotated[Session, Depends(get_db)],
) -> DeviceEnrollResponse:
    """Exchange a single-use enrolment code for this device's permanent secret.

    The secret is in the response body once and is never retrievable again —
    only its hash is stored. A device that loses it must be re-enrolled.
    """
    try:
        device, raw_secret = service.enroll_device(db, payload.enrollment_code, payload.hardware_id)
    except service.InvalidEnrollmentCodeError as exc:
        # One generic failure for unknown / expired / consumed / non-active,
        # so the response cannot be used to probe which codes exist.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid enrollment code"
        ) from exc

    return DeviceEnrollResponse(
        device_id=device.id, device_code=device.device_code, device_secret=raw_secret
    )


@router.post("/heartbeat", response_model=DeviceHeartbeatResponse)
@limiter.limit(_HEARTBEAT_RATE_LIMIT)
def heartbeat(
    request: Request,
    payload: DeviceHeartbeatRequest,
    db: Annotated[Session, Depends(get_db)],
    device: Annotated[WearableDevice, Depends(get_current_device)],
) -> DeviceHeartbeatResponse:
    """Report health, and learn the current assignment.

    This is also the backend→device channel: the device polls, and the response
    carries whatever the backend wants it to know. That is why no server push
    (and therefore no MQTT broker) is needed for assignment changes.

    `server_time_ms` is returned so a device without SNTP can still convert its
    monotonic event timestamps to wall clock before sending them.

    `assignment` is null whenever the device is unassigned — including
    immediately after a discharge cascade ended it — and the firmware treats
    that as a safe idle state in which no patient events are produced. Note the
    view deliberately carries no patient identity of any kind.
    """
    service.record_heartbeat(db, device, payload)

    assignment = service.active_assignment_for_device(db, device.id)
    view = (
        DeviceAssignmentView(
            assignment_id=assignment.id,
            monitoring_profile=assignment.monitoring_profile,
            assigned_at_ms=int(assignment.assigned_at.timestamp() * 1000),
        )
        if assignment is not None
        else None
    )
    return DeviceHeartbeatResponse(server_time_ms=int(time.time() * 1000), assignment=view)
