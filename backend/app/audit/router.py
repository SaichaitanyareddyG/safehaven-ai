import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.audit import service
from app.auth.dependencies import get_current_user
from app.auth.provider import AuthenticatedUser
from app.audit.schemas import AuditEventListResponse
from app.core.db import get_db
from app.patients.service import PatientNotFoundError, get_patient

router = APIRouter(tags=["audit"])


@router.get("/patients/{patient_id}/audit", response_model=AuditEventListResponse)
def list_patient_audit_events(
    patient_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    event_type: Annotated[str | None, Query()] = None,
    from_: Annotated[datetime | None, Query(alias="from")] = None,
    to: Annotated[datetime | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> AuditEventListResponse:
    """Clinician-authenticated only. Patient care-access tokens are a wholly
    separate, unauthenticated mechanism (see patient_access/router.py) and carry
    no JWT, so a patient token alone can never reach this route."""
    try:
        get_patient(db, patient_id)
    except PatientNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Patient not found") from exc

    total, results = service.list_patient_audit_events(db, patient_id, event_type, from_, to, limit, offset)
    return AuditEventListResponse(total=total, results=results)
