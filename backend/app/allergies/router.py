import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.allergies import service
from app.allergies.schemas import PatientAllergyCreate, PatientAllergyListResponse, PatientAllergyRead
from app.allergies.service import AllergyNotFoundError
from app.auth.dependencies import get_current_user
from app.auth.provider import AuthenticatedUser
from app.core.db import get_db
from app.patients.service import PatientNotFoundError

router = APIRouter(tags=["allergies"])


@router.post(
    "/patients/{patient_id}/allergies", response_model=PatientAllergyRead, status_code=status.HTTP_201_CREATED
)
def create_allergy(
    patient_id: uuid.UUID,
    payload: PatientAllergyCreate,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> PatientAllergyRead:
    try:
        return service.create_allergy(db, patient_id, payload, documented_by=uuid.UUID(current_user.id))
    except PatientNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Patient not found") from exc


@router.get("/patients/{patient_id}/allergies", response_model=PatientAllergyListResponse)
def list_allergies(
    patient_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> PatientAllergyListResponse:
    try:
        records = service.list_allergies(db, patient_id)
    except PatientNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Patient not found") from exc
    return PatientAllergyListResponse(total=len(records), results=records)


@router.delete("/patients/{patient_id}/allergies/{allergy_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_allergy(
    patient_id: uuid.UUID,
    allergy_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> None:
    try:
        service.delete_allergy(db, patient_id, allergy_id, removed_by=uuid.UUID(current_user.id))
    except AllergyNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Allergy not found") from exc
