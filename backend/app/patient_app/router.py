import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.auth.provider import AuthenticatedUser
from app.core.db import get_db
from app.core.rate_limit import limiter
from app.patient_access.schemas import PatientCarePlanResponse
from app.patient_access.service import build_care_plan
from app.patient_app import service
from app.patient_app.schemas import (
    AppAccessRead,
    AppInviteRequest,
    AppInviteResponse,
    ExchangeRequest,
    MyProfile,
    MyVisit,
    MyVisitsResponse,
    PatientSessionResponse,
    SignInLinkRequest,
)
from app.patient_app.security import InvalidPatientTokenError, create_patient_token, decode_patient_token
from app.patient_app.service import InvalidSignInLinkError, PatientAccessDeniedError, PatientAppError
from app.patients.models import Patient
from app.patients.service import PatientNotFoundError, get_patient

# Staff manage a patient's app access next to the rest of the patient record.
staff_router = APIRouter(prefix="/patients", tags=["patient-app"])
# The patient's own API. Separate prefix and its own bearer check: a staff
# token is refused here and a patient token is refused everywhere else.
router = APIRouter(prefix="/patient-app", tags=["patient-app"])

# Each request can send an email.
_LINK_RATE_LIMIT = "5/minute"
_EXCHANGE_RATE_LIMIT = "30/minute"
_LINK_INVALID = "This sign-in link has expired or was already used. Ask for a new one below."


def to_access_read(patient: Patient, account) -> AppAccessRead:
    return AppAccessRead(
        status=service.access_status(account),
        email=patient.email,
        phone=patient.phone,
        consent_at=patient.app_consent_at,
        invited_at=account.invited_at if account else None,
        activated_at=account.activated_at if account else None,
        last_sign_in_at=account.last_sign_in_at if account else None,
        access_expires_at=account.access_expires_at if account else None,
    )


@staff_router.get("/{patient_id}/app-access", response_model=AppAccessRead)
def get_app_access(
    patient_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> AppAccessRead:
    try:
        patient = get_patient(db, patient_id)
    except PatientNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Patient not found") from exc
    return to_access_read(patient, service.get_account(db, patient_id))


@staff_router.post("/{patient_id}/app-access/invite", response_model=AppInviteResponse)
def invite_to_app(
    patient_id: uuid.UUID,
    payload: AppInviteRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> AppInviteResponse:
    """Send, or send again, the invite email. Also records email and consent."""
    try:
        result = service.invite(
            db,
            patient_id,
            uuid.UUID(current_user.id),
            email=payload.email,
            phone=payload.phone,
            consent=payload.consent,
        )
    except PatientNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Patient not found") from exc
    except PatientAppError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    patient = get_patient(db, patient_id)
    return AppInviteResponse(
        access=to_access_read(patient, result.account), emailed=result.emailed, problem=result.problem, link=result.link
    )


@staff_router.post("/{patient_id}/app-access/revoke", response_model=AppAccessRead)
def revoke_app_access(
    patient_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> AppAccessRead:
    try:
        account = service.revoke(db, patient_id, uuid.UUID(current_user.id))
    except PatientNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Patient not found") from exc
    except PatientAppError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return to_access_read(get_patient(db, patient_id), account)


# --- The patient's own API -----------------------------------------------------

_bearer = HTTPBearer(auto_error=False)


def get_signed_in_patient(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    db: Annotated[Session, Depends(get_db)],
) -> Patient:
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Please sign in again",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if credentials is None:
        raise unauthorized
    try:
        patient_id, session_version = decode_patient_token(credentials.credentials)
        return service.authorize(db, patient_id, session_version)
    except (InvalidPatientTokenError, PatientAccessDeniedError) as exc:
        raise unauthorized from exc


@router.post("/request-link", status_code=status.HTTP_202_ACCEPTED)
@limiter.limit(_LINK_RATE_LIMIT)
def request_link(request: Request, payload: SignInLinkRequest, db: Annotated[Session, Depends(get_db)]) -> dict:
    """Always the same answer, so the form never reveals who is a patient."""
    service.request_sign_in_link(db, payload.email)
    return {"detail": "If that address can use SafeHaven, a sign-in link is on its way."}


@router.post("/exchange", response_model=PatientSessionResponse)
@limiter.limit(_EXCHANGE_RATE_LIMIT)
def exchange(request: Request, payload: ExchangeRequest, db: Annotated[Session, Depends(get_db)]) -> PatientSessionResponse:
    try:
        patient, account = service.exchange_link(db, payload.token)
    except InvalidSignInLinkError as exc:
        raise HTTPException(status_code=status.HTTP_410_GONE, detail=_LINK_INVALID) from exc
    token, expires_at = create_patient_token(patient.id, account.session_version)
    return PatientSessionResponse(access_token=token, expires_at=expires_at)


@router.get("/me", response_model=MyProfile)
def me(patient: Annotated[Patient, Depends(get_signed_in_patient)], db: Annotated[Session, Depends(get_db)]) -> MyProfile:
    account = service.get_account(db, patient.id)
    return MyProfile(
        first_name=patient.first_name,
        last_name=patient.last_name,
        preferred_language=patient.preferred_language,
        admission_status=patient.admission_status,
        room_number=patient.room_number,
        access_expires_at=account.access_expires_at if account else None,
    )


@router.get("/me/care-plan", response_model=PatientCarePlanResponse)
def my_care_plan(
    patient: Annotated[Patient, Depends(get_signed_in_patient)], db: Annotated[Session, Depends(get_db)]
) -> PatientCarePlanResponse:
    """Medicines (current and past), care instructions, conditions and
    allergies — exactly what the printed care link shows."""
    return build_care_plan(db, patient)


@router.get("/me/visits", response_model=MyVisitsResponse)
def my_visits(
    patient: Annotated[Patient, Depends(get_signed_in_patient)], db: Annotated[Session, Depends(get_db)]
) -> MyVisitsResponse:
    return MyVisitsResponse(
        visits=[
            MyVisit(
                id=e.id,
                reason_for_visit=e.reason_for_visit,
                encounter_type=e.encounter_type,
                planned_procedure=e.planned_procedure,
                nil_by_mouth_from=e.nil_by_mouth_from,
                admission_date=e.admission_date,
                discharge_date=e.discharge_date,
                status=e.status,
            )
            for e in service.list_visits(db, patient.id)
        ]
    )
