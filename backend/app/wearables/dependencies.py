"""The device authentication boundary.

Three actor types now exist in SAFEHAVEN, and they must not be
interchangeable (MODULE_3_IMPLEMENTATION_PLAN.md §9):

    clinician  →  JWT              →  app.auth.dependencies.get_current_user
    patient    →  care-link token  →  app.patient_access.service.validate_*
    device     →  device secret    →  get_current_device  (here)

A device credential must never be accepted on a clinician route, and a
clinician JWT must never be accepted here. That separation is why this is its
own dependency rather than an extra branch inside get_current_user: a device is
not a user, has no role, and must not inherit anything a clinician can do.
"""

from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.wearables import service
from app.wearables.models import WearableDevice

# auto_error=False so a missing/!Bearer header lands in our own handler and
# produces the same opaque 401 as a wrong secret. Letting FastAPI raise its own
# 403 for a missing header would tell a prober that the header was the problem.
_device_scheme = HTTPBearer(auto_error=False, scheme_name="DeviceCredential")

_UNAUTHORIZED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Invalid device credential",
    headers={"WWW-Authenticate": "Bearer"},
)


def get_current_device(
    db: Annotated[Session, Depends(get_db)],
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_device_scheme)] = None,
) -> WearableDevice:
    """Authenticate a device by its bearer secret.

    Absent header, wrong scheme, unknown credential, disabled device and
    retired device all produce the byte-identical 401 above. A caller cannot
    use the response to learn whether a device id exists, which is the same
    property the patient care-link endpoints deliberately have.
    """
    if creds is None or creds.scheme.lower() != "bearer" or not creds.credentials:
        raise _UNAUTHORIZED
    try:
        return service.authenticate_device(db, creds.credentials)
    except service.InvalidDeviceCredentialError as exc:
        raise _UNAUTHORIZED from exc
