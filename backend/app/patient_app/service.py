"""The patient app: invites, passwordless sign-in and what a signed-in
patient may read.

Nothing here is entered twice. Medicines, instructions, conditions and
allergies come from the same approved, validated records as the printed care
link (patient_access.service.build_care_plan); visits come from encounters.
"""

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.audit.models import ActorType, AuditEventType
from app.audit.service import record_event
from app.core import email as email_module
from app.core.config import get_settings
from app.encounters.models import Encounter
from app.patient_app.models import (
    PURPOSE_INVITE,
    PURPOSE_SIGN_IN,
    STATUS_ACTIVE,
    STATUS_INVITED,
    STATUS_REVOKED,
    PatientAppAccount,
    PatientSignInLink,
)
from app.patients.models import AdmissionStatus, Patient
from app.patients.service import get_patient


class PatientAppError(Exception):
    """A staff action that cannot go ahead; the message is safe to show."""


class InvalidSignInLinkError(Exception):
    """Unknown, expired, used, revoked — deliberately one error."""


class PatientAccessDeniedError(Exception):
    pass


@dataclass(frozen=True)
class InviteResult:
    account: PatientAppAccount
    emailed: bool
    problem: str | None
    # Only when the email did not go: staff can pass it on another way.
    link: str | None


def normalize_email(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip().lower()
    return value or None


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def link_url(token: str) -> str:
    # Fragment, not query: never sent to a server, so never in an access log.
    return f"{get_settings().dashboard_url.rstrip('/')}/my/sign-in#token={token}"


def get_account(db: Session, patient_id: uuid.UUID) -> PatientAppAccount | None:
    return db.query(PatientAppAccount).filter(PatientAppAccount.patient_id == patient_id).first()


def access_status(account: PatientAppAccount | None) -> str:
    if account is None:
        return "NOT_INVITED"
    if account.status == STATUS_ACTIVE and _access_expired(account):
        return "EXPIRED"
    return account.status


def _access_expired(account: PatientAppAccount) -> bool:
    return account.access_expires_at is not None and account.access_expires_at <= datetime.now(timezone.utc)


def _create_link(db: Session, patient_id: uuid.UUID, purpose: str) -> str:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    lifetime = (
        timedelta(hours=settings.patient_invite_link_ttl_hours)
        if purpose == PURPOSE_INVITE
        else timedelta(minutes=settings.patient_sign_in_link_ttl_minutes)
    )
    # A new link cancels any older unused one.
    db.query(PatientSignInLink).filter(
        PatientSignInLink.patient_id == patient_id, PatientSignInLink.used_at.is_(None)
    ).update({PatientSignInLink.used_at: now})
    token = secrets.token_urlsafe(32)
    db.add(PatientSignInLink(patient_id=patient_id, token_hash=_hash(token), purpose=purpose, expires_at=now + lifetime))
    db.flush()
    return token


def email_in_use_elsewhere(db: Session, patient_id: uuid.UUID | None, email: str) -> bool:
    """One app login per address, so a sign-in link always reaches one record.
    Only patients with a live app account count: a discharged relative who
    once shared the address does not block a new patient for ever."""
    query = (
        db.query(Patient.id)
        .join(PatientAppAccount, PatientAppAccount.patient_id == Patient.id)
        .filter(func.lower(Patient.email) == normalize_email(email), PatientAppAccount.status != STATUS_REVOKED)
    )
    if patient_id is not None:
        query = query.filter(Patient.id != patient_id)
    return query.first() is not None


def invite(
    db: Session,
    patient_id: uuid.UUID,
    invited_by: uuid.UUID,
    *,
    email: str | None = None,
    phone: str | None = None,
    consent: bool = False,
    commit: bool = True,
) -> InviteResult:
    """Record contact and consent (when given) and email a sign-in link.
    Also the "resend invite" action: a new link replaces the old one."""
    patient = get_patient(db, patient_id)
    now = datetime.now(timezone.utc)

    # Every check before any change, so a refusal leaves nothing half-saved.
    new_email = normalize_email(email) or patient.email
    if not new_email:
        raise PatientAppError("Add the patient's email address first.")
    if patient.app_consent_at is None and not consent:
        raise PatientAppError("Confirm the patient agreed to use the app first.")
    if email_in_use_elsewhere(db, patient.id, new_email):
        raise PatientAppError("Another patient already uses this email for the app.")

    patient.email = new_email
    if phone is not None:
        patient.phone = phone.strip() or None
    if patient.app_consent_at is None:
        patient.app_consent_at = now
        patient.app_consent_by = invited_by

    account = get_account(db, patient.id)
    if account is None:
        account = PatientAppAccount(patient_id=patient.id, status=STATUS_INVITED, invited_at=now, invited_by=invited_by)
        db.add(account)
    else:
        if account.status == STATUS_REVOKED:
            account.status = STATUS_INVITED
            account.revoked_at = None
        account.invited_at = now
        account.invited_by = invited_by
    if patient.admission_status == AdmissionStatus.ACTIVE:
        account.access_expires_at = None
    elif account.access_expires_at is None or _access_expired(account):
        # Invited after discharge: the same window as if they were discharged today.
        account.access_expires_at = now + timedelta(days=get_settings().patient_access_after_discharge_days)
    db.flush()

    token = _create_link(db, patient.id, PURPOSE_INVITE)
    record_event(
        db,
        event_type=AuditEventType.PATIENT_APP_INVITED,
        actor_type=ActorType.CLINICIAN,
        actor_id=invited_by,
        patient_id=patient.id,
        entity_type="PatientAppAccount",
        entity_id=account.id,
    )
    if commit:
        db.commit()
    else:
        db.flush()

    link = link_url(token)
    result = email_module.send_patient_invite_email(
        patient.email, link, get_settings().patient_invite_link_ttl_hours
    )
    return InviteResult(
        account=account, emailed=result.sent, problem=result.problem, link=None if result.sent else link
    )


def revoke(db: Session, patient_id: uuid.UUID, revoked_by: uuid.UUID) -> PatientAppAccount:
    """Signs the patient out everywhere and stops new sign-ins until staff
    invite them again. Idempotent."""
    get_patient(db, patient_id)
    account = get_account(db, patient_id)
    if account is None:
        raise PatientAppError("This patient has not been invited to the app.")
    if account.status != STATUS_REVOKED:
        now = datetime.now(timezone.utc)
        account.status = STATUS_REVOKED
        account.revoked_at = now
        account.session_version += 1
        db.query(PatientSignInLink).filter(
            PatientSignInLink.patient_id == patient_id, PatientSignInLink.used_at.is_(None)
        ).update({PatientSignInLink.used_at: now})
        record_event(
            db,
            event_type=AuditEventType.PATIENT_APP_ACCESS_REVOKED,
            actor_type=ActorType.CLINICIAN,
            actor_id=revoked_by,
            patient_id=patient_id,
            entity_type="PatientAppAccount",
            entity_id=account.id,
        )
    db.commit()
    db.refresh(account)
    return account


def on_admission_status_changed(db: Session, patient: Patient) -> None:
    """Called inside the discharge transaction (app/orchestration/). The app
    stays useful at home for a fixed window; readmission reopens it."""
    account = get_account(db, patient.id)
    if account is None:
        return
    if patient.admission_status == AdmissionStatus.DISCHARGED:
        account.access_expires_at = datetime.now(timezone.utc) + timedelta(
            days=get_settings().patient_access_after_discharge_days
        )
    else:
        account.access_expires_at = None
    db.flush()


def request_sign_in_link(db: Session, email: str) -> None:
    """Sends a link if the address belongs to a patient with app access.
    Says nothing either way, so the form never confirms who is a patient."""
    email = normalize_email(email)
    if not email:
        return
    row = (
        db.query(Patient, PatientAppAccount)
        .join(PatientAppAccount, PatientAppAccount.patient_id == Patient.id)
        .filter(func.lower(Patient.email) == email, PatientAppAccount.status != STATUS_REVOKED)
        .first()
    )
    if row is None:
        return
    patient, account = row
    if _access_expired(account):
        return
    token = _create_link(db, patient.id, PURPOSE_SIGN_IN)
    db.commit()
    email_module.send_patient_sign_in_email(
        patient.email, link_url(token), get_settings().patient_sign_in_link_ttl_minutes
    )


def exchange_link(db: Session, raw_token: str) -> tuple[Patient, PatientAppAccount]:
    """Spends a sign-in link. The caller then issues a session token."""
    now = datetime.now(timezone.utc)
    link = db.query(PatientSignInLink).filter(PatientSignInLink.token_hash == _hash(raw_token)).first()
    if link is None or link.used_at is not None or link.expires_at <= now:
        raise InvalidSignInLinkError()
    account = get_account(db, link.patient_id)
    if account is None or account.status == STATUS_REVOKED or _access_expired(account):
        raise InvalidSignInLinkError()
    patient = db.get(Patient, link.patient_id)

    link.used_at = now
    if account.status == STATUS_INVITED:
        account.status = STATUS_ACTIVE
        account.activated_at = now
    account.last_sign_in_at = now
    record_event(
        db,
        event_type=AuditEventType.PATIENT_APP_SIGNED_IN,
        actor_type=ActorType.PATIENT,
        patient_id=patient.id,
        entity_type="PatientAppAccount",
        entity_id=account.id,
        event_metadata={"via": link.purpose},
    )
    db.commit()
    return patient, account


def authorize(db: Session, patient_id: uuid.UUID, session_version: int) -> Patient:
    """Every patient-app request: the account must still be live and the
    token from the current session generation."""
    account = get_account(db, patient_id)
    if (
        account is None
        or account.status != STATUS_ACTIVE
        or account.session_version != session_version
        or _access_expired(account)
    ):
        raise PatientAccessDeniedError()
    patient = db.get(Patient, patient_id)
    if patient is None:
        raise PatientAccessDeniedError()
    return patient


def list_visits(db: Session, patient_id: uuid.UUID) -> list[Encounter]:
    return (
        db.query(Encounter)
        .filter(Encounter.patient_id == patient_id)
        .order_by(Encounter.admission_date.desc(), Encounter.created_at.desc())
        .all()
    )
