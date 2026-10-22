import uuid
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.auth.provider import AuthenticatedUser
from app.core.db import get_db
from app.orchestration import patient_ops
from app.patients import service
from app.patients.models import AdmissionStatus
from app.appointments.service import list_appointments
from app.audit.models import ActorType, AuditEventType
from app.audit.service import record_event
from app.patient_access.service import build_care_plan
from app.patient_app import service as app_service
from app.patient_app.doses import missed_doses_flags
from app.patients.schemas import (
    AppInviteOutcome,
    CarePlanPrintout,
    MissedDosesFlag,
    MissedDosesResponse,
    PatientCreate,
    PatientCreateResponse,
    PatientListResponse,
    PatientRead,
    PatientUpdate,
)
from app.patients.service import PatientNotFoundError

router = APIRouter(prefix="/patients", tags=["patients"])


@router.post("", response_model=PatientCreateResponse, status_code=status.HTTP_201_CREATED)
def create_patient(
    payload: PatientCreate,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> PatientCreateResponse:
    """With an email and the patient's consent, also emails the patient-app
    invite. The patient is registered either way: a failed invite is
    reported, never a reason to lose the registration."""
    staff_id = uuid.UUID(current_user.id)
    if payload.email and payload.app_consent and app_service.email_in_use_elsewhere(db, None, payload.email):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Another patient already uses this email for the app."
        )
    patient = service.create_patient(db, payload, created_by=staff_id)
    response = PatientCreateResponse.model_validate(patient, from_attributes=True)
    if payload.email and payload.app_consent:
        try:
            result = app_service.invite(db, patient.id, staff_id, consent=True)
            response.app_invite = AppInviteOutcome(emailed=result.emailed, problem=result.problem, link=result.link)
        except app_service.PatientAppError as exc:
            response.app_invite = AppInviteOutcome(emailed=False, problem=str(exc))
    return response


@router.get("", response_model=PatientListResponse)
def list_patients(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    status_filter: Annotated[AdmissionStatus | None, Query(alias="status")] = None,
    search: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> PatientListResponse:
    total, results = service.list_patients(db, status_filter, search, limit, offset)
    return PatientListResponse(total=total, results=results)


@router.get("/missed-doses", response_model=MissedDosesResponse)
def missed_doses(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> MissedDosesResponse:
    """Patients at home who missed 2+ doses in the app today or yesterday
    (app/patient_app/doses.py). Declared before /{patient_id} so the path is
    not read as a patient id."""
    return MissedDosesResponse(
        flags=[
            MissedDosesFlag(patient_id=f.patient_id, date=f.day, missed=f.missed, skipped=f.skipped)
            for f in missed_doses_flags(db)
        ]
    )


@router.get("/{patient_id}/care-plan-printout", response_model=CarePlanPrintout)
def care_plan_printout(
    patient_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> CarePlanPrintout:
    """The printable care plan: the same approved content the patient sees,
    plus upcoming appointments. Printing is recorded: a paper copy of a
    care plan leaves the system."""
    try:
        patient = service.get_patient(db, patient_id)
    except PatientNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Patient not found") from exc
    plan = build_care_plan(db, patient)
    now = datetime.now(timezone.utc)
    upcoming = [a for a in list_appointments(db, patient.id, include_cancelled=False) if a.starts_at >= now]
    record_event(
        db,
        event_type=AuditEventType.CARE_PLAN_PRINTED,
        actor_type=ActorType.CLINICIAN,
        actor_id=uuid.UUID(current_user.id),
        patient_id=patient.id,
        entity_type="Patient",
        entity_id=patient.id,
    )
    db.commit()
    return CarePlanPrintout(
        patient_first_name=patient.first_name,
        patient_last_name=patient.last_name,
        patient_code=patient.patient_code,
        date_of_birth=patient.date_of_birth,
        care_plan=plan,
        appointments=upcoming,
        printed_at=now,
    )


@router.get("/by-code/{patient_code}", response_model=PatientRead)
def get_patient_by_code(
    patient_code: str,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> PatientRead:
    """Resolves a scanned wristband code to a patient — see Module 2's
    medication verification workflow."""
    try:
        return service.get_patient_by_code(db, patient_code)
    except PatientNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Patient not found") from exc


@router.get("/{patient_id}", response_model=PatientRead)
def get_patient(
    patient_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> PatientRead:
    try:
        return service.get_patient(db, patient_id)
    except PatientNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Patient not found") from exc


@router.patch("/{patient_id}", response_model=PatientRead)
def update_patient(
    patient_id: uuid.UUID,
    payload: PatientUpdate,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> PatientRead:
    if payload.email and app_service.email_in_use_elsewhere(db, patient_id, payload.email):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Another patient already uses this email for the app."
        )
    try:
        return patient_ops.update_patient(db, patient_id, payload, updated_by=uuid.UUID(current_user.id))
    except PatientNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Patient not found") from exc
