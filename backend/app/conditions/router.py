import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.auth.provider import AuthenticatedUser
from app.conditions import service
from app.conditions.schemas import PatientConditionCreate, PatientConditionListResponse, PatientConditionRead
from app.conditions.service import ConditionNotFoundError
from app.core.db import get_db
from app.patients.service import PatientNotFoundError

router = APIRouter(tags=["conditions"])


@router.post(
    "/patients/{patient_id}/conditions", response_model=PatientConditionRead, status_code=status.HTTP_201_CREATED
)
def create_condition(
    patient_id: uuid.UUID,
    payload: PatientConditionCreate,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> PatientConditionRead:
    try:
        return service.create_condition(db, patient_id, payload, documented_by=uuid.UUID(current_user.id))
    except PatientNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Patient not found") from exc


@router.get("/patients/{patient_id}/conditions", response_model=PatientConditionListResponse)
def list_conditions(
    patient_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> PatientConditionListResponse:
    try:
        records = service.list_conditions(db, patient_id)
    except PatientNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Patient not found") from exc
    return PatientConditionListResponse(total=len(records), results=records)


@router.delete("/patients/{patient_id}/conditions/{condition_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_condition(
    patient_id: uuid.UUID,
    condition_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> None:
    try:
        service.delete_condition(db, patient_id, condition_id, removed_by=uuid.UUID(current_user.id))
    except ConditionNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Condition not found") from exc
