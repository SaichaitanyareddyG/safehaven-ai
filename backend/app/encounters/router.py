import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.auth.provider import AuthenticatedUser
from app.core.db import get_db
from app.encounters import service
from app.encounters.schemas import EncounterCreate, EncounterListResponse, EncounterRead
from app.patients.service import PatientNotFoundError

router = APIRouter(tags=["encounters"])


@router.post("/patients/{patient_id}/encounters", response_model=EncounterRead, status_code=status.HTTP_201_CREATED)
def create_encounter(
    patient_id: uuid.UUID,
    payload: EncounterCreate,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> EncounterRead:
    try:
        return service.create_encounter(db, patient_id, payload, created_by=uuid.UUID(current_user.id))
    except PatientNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Patient not found") from exc


@router.get("/patients/{patient_id}/encounters", response_model=EncounterListResponse)
def list_encounters(
    patient_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> EncounterListResponse:
    try:
        records = service.list_encounters(db, patient_id)
    except PatientNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Patient not found") from exc
    return EncounterListResponse(total=len(records), results=records)
