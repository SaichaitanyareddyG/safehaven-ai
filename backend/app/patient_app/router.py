import uuid
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Query, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.auth.provider import AuthenticatedUser
from app.core.db import get_db
from app.core.rate_limit import limiter
from app.patient_access.schemas import PatientCarePlanResponse
from app.patient_access.service import build_care_plan
from app.patient_app import service
from app.core.config import get_settings
from app.patient_app import doses as dose_service
from app.patient_app import push as push_service
from app.patient_app.models import PushSubscription
from app.patient_app.schemas import (
    AdherenceDayRead,
    AdherenceResponse,
    AppAccessRead,
    DoseRead,
    DoseRecordRequest,
    MyDosesResponse,
    PushStatus,
    PushSubscribeRequest,
    PushUnsubscribeRequest,
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
from app.patients.models import AdmissionStatus, Patient
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
def request_link(
    request: Request,
    payload: SignInLinkRequest,
    background: BackgroundTasks,
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    """Always the same answer, in the same time: the email goes out after the
    response, so neither reveals who is a patient."""
    send = service.request_sign_in_link(db, payload.email)
    if send is not None:
        background.add_task(send)
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


def _dose_read(dose: dose_service.DueDose) -> DoseRead:
    return DoseRead(**dose.__dict__)


@router.get("/me/doses", response_model=MyDosesResponse)
def my_doses(
    patient: Annotated[Patient, Depends(get_signed_in_patient)], db: Annotated[Session, Depends(get_db)]
) -> MyDosesResponse:
    """Today's scheduled doses, earliest first, with the patient's answers."""
    today = dose_service.hospital_now().date()
    return MyDosesResponse(
        date=today,
        at_home=patient.admission_status == AdmissionStatus.DISCHARGED,
        doses=[_dose_read(d) for d in dose_service.doses_with_status(db, patient.id, today, today)],
    )


@router.post("/me/doses", status_code=status.HTTP_204_NO_CONTENT)
def record_dose(
    payload: DoseRecordRequest,
    patient: Annotated[Patient, Depends(get_signed_in_patient)],
    db: Annotated[Session, Depends(get_db)],
) -> None:
    """Taken / Skipped (status null = undo), for today or yesterday only."""
    try:
        dose_service.record_dose(db, patient.id, payload.instruction_id, payload.date, payload.time, payload.status)
    except dose_service.DoseNotDueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="That dose is not on your schedule") from exc


@router.get("/push", response_model=PushStatus)
def push_status() -> PushStatus:
    """Public: the key a browser needs to subscribe, if reminders are set up."""
    return PushStatus(available=push_service.push_enabled(), public_key=get_settings().vapid_public_key)


@router.post("/me/push", status_code=status.HTTP_204_NO_CONTENT)
def subscribe_push(
    payload: PushSubscribeRequest,
    patient: Annotated[Patient, Depends(get_signed_in_patient)],
    db: Annotated[Session, Depends(get_db)],
) -> None:
    """Turn reminders on for this phone. Sends one test notification so the
    patient sees at once that it works."""
    if not push_service.push_enabled():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reminders are not set up on this server")
    if not payload.endpoint.startswith("https://"):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Not a push address")
    existing = db.query(PushSubscription).filter(PushSubscription.endpoint == payload.endpoint).first()
    if existing is None:
        existing = PushSubscription(
            patient_id=patient.id, endpoint=payload.endpoint, p256dh=payload.keys.p256dh, auth=payload.keys.auth
        )
        db.add(existing)
    else:
        # The same phone, now signed in as this patient.
        existing.patient_id = patient.id
        existing.p256dh = payload.keys.p256dh
        existing.auth = payload.keys.auth
    db.commit()
    push_service.send_to_subscription(
        db,
        existing,
        {"title": "Reminders are on", "body": "We'll remind you when it's time for your medicines.", "url": "/my", "tag": "welcome"},
    )
    db.commit()


@router.post("/me/push/remove", status_code=status.HTTP_204_NO_CONTENT)
def unsubscribe_push(
    payload: PushUnsubscribeRequest,
    patient: Annotated[Patient, Depends(get_signed_in_patient)],
    db: Annotated[Session, Depends(get_db)],
) -> None:
    db.query(PushSubscription).filter(
        PushSubscription.endpoint == payload.endpoint, PushSubscription.patient_id == patient.id
    ).delete()
    db.commit()


@staff_router.get("/{patient_id}/app-access/adherence", response_model=AdherenceResponse)
def get_adherence(
    patient_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    days: Annotated[int, Query(ge=1, le=60)] = 14,
) -> AdherenceResponse:
    """What the patient reported in the app, per day. Patient-reported, not
    nurse-administered (that is Medication check)."""
    try:
        get_patient(db, patient_id)
    except PatientNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Patient not found") from exc
    rows = dose_service.adherence(db, patient_id, days)
    return AdherenceResponse(
        days=[AdherenceDayRead(date=r.day, due=r.due, taken=r.taken, skipped=r.skipped) for r in rows],
        total_due=sum(r.due for r in rows),
        total_taken=sum(r.taken for r in rows),
        total_skipped=sum(r.skipped for r in rows),
    )


# Called every minute by the Cloudflare cron (frontend/worker/index.js): a
# free Render service sleeps, so it cannot keep its own clock.
internal_router = APIRouter(prefix="/internal", tags=["internal"], include_in_schema=False)


@internal_router.post("/reminders/tick")
def reminders_tick(
    db: Annotated[Session, Depends(get_db)],
    x_tick_secret: Annotated[str | None, Header()] = None,
) -> dict:
    import hmac

    secret = get_settings().reminder_tick_secret
    # Bytes: compare_digest raises on non-ASCII str, which would be a 500.
    if not secret or not x_tick_secret or not hmac.compare_digest(secret.encode(), x_tick_secret.encode()):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not Found")
    return {"sent": push_service.run_reminders(db)}
