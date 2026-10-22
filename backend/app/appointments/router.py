import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.appointments import service
from app.appointments.schemas import AppointmentCreate, AppointmentListResponse, AppointmentRead, AppointmentUpdate
from app.auth.dependencies import get_current_user
from app.auth.provider import AuthenticatedUser
from app.core.db import get_db
from app.patients.service import PatientNotFoundError

router = APIRouter(tags=["appointments"])


@router.post("/patients/{patient_id}/appointments", response_model=AppointmentRead, status_code=status.HTTP_201_CREATED)
def create_appointment(
    patient_id: uuid.UUID,
    payload: AppointmentCreate,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> AppointmentRead:
    try:
        return service.create_appointment(db, patient_id, payload, created_by=uuid.UUID(current_user.id))
    except PatientNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Patient not found") from exc


@router.get("/patients/{patient_id}/appointments", response_model=AppointmentListResponse)
def list_appointments(
    patient_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> AppointmentListResponse:
    try:
        return AppointmentListResponse(results=service.list_appointments(db, patient_id))
    except PatientNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Patient not found") from exc


@router.patch("/appointments/{appointment_id}", response_model=AppointmentRead)
def update_appointment(
    appointment_id: uuid.UUID,
    payload: AppointmentUpdate,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> AppointmentRead:
    """Edit, reschedule (new reminders) or cancel (status CANCELLED)."""
    try:
        return service.update_appointment(db, appointment_id, payload, updated_by=uuid.UUID(current_user.id))
    except service.AppointmentNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Appointment not found") from exc
