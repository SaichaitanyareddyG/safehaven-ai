import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.auth.provider import AuthenticatedUser
from app.core.db import get_db
from app.encounters import service
from app.encounters.models import Encounter
from app.encounters.schemas import EncounterCreate, EncounterListResponse, EncounterRead, EncounterUpdate
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


@router.patch("/encounters/{encounter_id}", response_model=EncounterRead)
def update_encounter(
    encounter_id: uuid.UUID,
    payload: EncounterUpdate,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> EncounterRead:
    """Adds procedure / nil-by-mouth context to a visit already in progress —
    the decision is normally taken after the patient is admitted, not at
    registration."""
    encounter = db.get(Encounter, encounter_id)
    if encounter is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Encounter not found")

    if payload.planned_procedure is not None:
        encounter.planned_procedure = payload.planned_procedure.strip() or None
    if payload.nil_by_mouth_from is not None:
        encounter.nil_by_mouth_from = payload.nil_by_mouth_from

    db.commit()
    db.refresh(encounter)
    return encounter
