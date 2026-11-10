"""The patient app: invites, email + password sign-in and what a signed-in
patient may read.

Nothing here is entered twice. Medicines, instructions, conditions and
allergies come from the same approved, validated records as the printed care
link (patient_access.service.build_care_plan); visits come from encounters.
"""

import hashlib
import secrets
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from functools import partial
from datetime import datetime, timedelta, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.audit.models import ActorType, AuditEventType
from app.audit.service import record_event
from app.auth.security import hash_password, verify_password
from app.core import email as email_module
from app.core.config import get_settings
from app.encounters.models import Encounter
from app.patient_app.models import (
    ROLE_CAREGIVER,
    ROLE_PATIENT,
    PURPOSE_INVITE,
    PURPOSE_SIGN_IN,
    STATUS_ACTIVE,
    STATUS_INVITED,
    STATUS_REVOKED,
    PatientAppAccount,
    PatientSignInLink,
    PushSubscription,
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
    """The patient's own login (caregivers have their own: list_caregivers)."""
    return (
        db.query(PatientAppAccount)
        .filter(PatientAppAccount.patient_id == patient_id, PatientAppAccount.role == ROLE_PATIENT)
        .first()
    )


def list_caregivers(db: Session, patient_id: uuid.UUID) -> list[PatientAppAccount]:
    return (
        db.query(PatientAppAccount)
        .filter(PatientAppAccount.patient_id == patient_id, PatientAppAccount.role == ROLE_CAREGIVER)
        .order_by(PatientAppAccount.created_at.asc())
        .all()
    )


def access_status(account: PatientAppAccount | None) -> str:
    if account is None:
        return "NOT_INVITED"
    if account.status == STATUS_ACTIVE and _access_expired(account):
        return "EXPIRED"
    return account.status


def _access_expired(account: PatientAppAccount) -> bool:
    return account.access_expires_at is not None and account.access_expires_at <= datetime.now(timezone.utc)


# An invite link with no time limit still expires in the column's terms.
_NO_TIME_LIMIT = timedelta(days=3650)

PASSWORD_MIN = 8
PASSWORD_MAX = 128


def _create_link(db: Session, account: PatientAppAccount, purpose: str) -> str:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    hours = settings.patient_invite_link_ttl_hours
    lifetime = (
        (timedelta(hours=hours) if hours else _NO_TIME_LIMIT)
        if purpose == PURPOSE_INVITE
        else timedelta(minutes=settings.patient_sign_in_link_ttl_minutes)
    )
    # A new link cancels this login's older unused one (not anyone else's).
    db.query(PatientSignInLink).filter(
        PatientSignInLink.account_id == account.id, PatientSignInLink.used_at.is_(None)
    ).update({PatientSignInLink.used_at: now})
    token = secrets.token_urlsafe(32)
    db.add(
        PatientSignInLink(
            patient_id=account.patient_id,
            account_id=account.id,
            token_hash=_hash(token),
            purpose=purpose,
            expires_at=now + lifetime,
        )
    )
    db.flush()
    return token


def email_in_use(db: Session, email: str, *, except_account_id: uuid.UUID | None = None) -> bool:
    """One live app login per address — patient's or caregiver's — so a
    sign-in link always opens exactly one person's view. A login turned off
    does not block the address for ever."""
    query = db.query(PatientAppAccount.id).filter(
        func.lower(PatientAppAccount.email) == normalize_email(email), PatientAppAccount.status != STATUS_REVOKED
    )
    if except_account_id is not None:
        query = query.filter(PatientAppAccount.id != except_account_id)
    return query.first() is not None


def email_in_use_elsewhere(db: Session, patient_id: uuid.UUID | None, email: str) -> bool:
    """For the patient's own address: in use by any login but their own."""
    own = get_account(db, patient_id) if patient_id is not None else None
    return email_in_use(db, email, except_account_id=own.id if own else None)


def _change_account_email(db: Session, account: PatientAppAccount, email: str | None) -> None:
    """Point a login at a new address, and sign out whoever used the old one.

    A changed address usually means the old one was wrong: a mistyped invite
    reached a stranger, who signed in. Correcting it used to leave that
    person's 30-day session and any unused link working.
    """
    if account.email is not None and (account.email or "").lower() != (email or "").lower():
        account.session_version += 1
        db.query(PatientSignInLink).filter(
            PatientSignInLink.account_id == account.id, PatientSignInLink.used_at.is_(None)
        ).update({PatientSignInLink.used_at: datetime.now(timezone.utc)})
        db.query(PushSubscription).filter(PushSubscription.account_id == account.id).delete()
    account.email = email


def sync_own_account_email(db: Session, patient: Patient) -> None:
    """Staff changed the patient's email: their own login follows it."""
    account = get_account(db, patient.id)
    if account is not None and account.email != patient.email:
        _change_account_email(db, account, patient.email)
        db.flush()


def _expiry_for_new_login(db: Session, patient: Patient) -> datetime | None:
    """No end date (2026-11-09): access lasts until staff turn it off."""
    return None


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
        account = PatientAppAccount(
            patient_id=patient.id, role=ROLE_PATIENT, status=STATUS_INVITED, invited_at=now, invited_by=invited_by
        )
        db.add(account)
    else:
        if account.status == STATUS_REVOKED:
            account.status = STATUS_INVITED
            account.revoked_at = None
        account.invited_at = now
        account.invited_by = invited_by
    account.access_expires_at = None  # no end date since 2026-11-09
    _change_account_email(db, account, patient.email)
    db.flush()

    token = _create_link(db, account, PURPOSE_INVITE)
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
    """Turns off the patient's own login (caregivers keep theirs, each has
    its own switch). Signs it out everywhere. Idempotent."""
    get_patient(db, patient_id)
    account = get_account(db, patient_id)
    if account is None:
        raise PatientAppError("This patient has not been invited to the app.")
    return revoke_account(db, account, revoked_by)


def revoke_account(db: Session, account: PatientAppAccount, revoked_by: uuid.UUID) -> PatientAppAccount:
    if account.status != STATUS_REVOKED:
        now = datetime.now(timezone.utc)
        account.status = STATUS_REVOKED
        account.revoked_at = now
        account.session_version += 1
        db.query(PatientSignInLink).filter(
            PatientSignInLink.account_id == account.id, PatientSignInLink.used_at.is_(None)
        ).update({PatientSignInLink.used_at: now})
        # No more reminders to this login's phones.
        db.query(PushSubscription).filter(PushSubscription.account_id == account.id).delete()
        record_event(
            db,
            event_type=(
                AuditEventType.CAREGIVER_ACCESS_REVOKED
                if account.role == ROLE_CAREGIVER
                else AuditEventType.PATIENT_APP_ACCESS_REVOKED
            ),
            actor_type=ActorType.CLINICIAN,
            actor_id=revoked_by,
            patient_id=account.patient_id,
            entity_type="PatientAppAccount",
            entity_id=account.id,
        )
    db.commit()
    db.refresh(account)
    return account


def invite_caregiver(
    db: Session,
    patient_id: uuid.UUID,
    invited_by: uuid.UUID,
    *,
    email: str,
    name: str,
    relationship: str | None,
    consent: bool,
) -> InviteResult:
    """A family member or carer gets their own login to the patient's app.
    Staff confirm the patient agreed to share their information with them."""
    patient = get_patient(db, patient_id)
    email = normalize_email(email)
    name = (name or "").strip()
    if not email:
        raise PatientAppError("Add the caregiver's email address.")
    if not name:
        raise PatientAppError("Add the caregiver's name.")
    if not consent:
        raise PatientAppError("Confirm the patient agreed to share their care information with this person.")
    existing = (
        db.query(PatientAppAccount)
        .filter(
            PatientAppAccount.patient_id == patient.id,
            PatientAppAccount.role == ROLE_CAREGIVER,
            func.lower(PatientAppAccount.email) == email,
        )
        .first()
    )
    if email_in_use(db, email, except_account_id=existing.id if existing else None):
        raise PatientAppError("This email already has a SafeHaven app login.")
    if patient.email and normalize_email(patient.email) == email:
        raise PatientAppError("That is the patient's own email. Use a different address for the caregiver.")

    now = datetime.now(timezone.utc)
    if existing is None:
        account = PatientAppAccount(
            patient_id=patient.id,
            role=ROLE_CAREGIVER,
            email=email,
            status=STATUS_INVITED,
            invited_at=now,
            invited_by=invited_by,
        )
        db.add(account)
    else:
        account = existing
        if account.status == STATUS_REVOKED:
            account.status = STATUS_INVITED
            account.revoked_at = None
        account.invited_at = now
        account.invited_by = invited_by
    account.display_name = name
    account.relationship = (relationship or "").strip() or None
    account.access_expires_at = _expiry_for_new_login(db, patient)
    db.flush()

    token = _create_link(db, account, PURPOSE_INVITE)
    record_event(
        db,
        event_type=AuditEventType.CAREGIVER_INVITED,
        actor_type=ActorType.CLINICIAN,
        actor_id=invited_by,
        patient_id=patient.id,
        entity_type="PatientAppAccount",
        entity_id=account.id,
        event_metadata={"relationship": account.relationship} if account.relationship else {},
    )
    db.commit()
    link = link_url(token)
    result = email_module.send_caregiver_invite_email(email, link, get_settings().patient_invite_link_ttl_hours)
    return InviteResult(account=account, emailed=result.sent, problem=result.problem, link=None if result.sent else link)


def get_caregiver(db: Session, patient_id: uuid.UUID, account_id: uuid.UUID) -> PatientAppAccount:
    account = db.get(PatientAppAccount, account_id)
    if account is None or account.patient_id != patient_id or account.role != ROLE_CAREGIVER:
        raise PatientAppError("Caregiver not found.")
    return account


def on_admission_status_changed(db: Session, patient: Patient) -> None:
    """Called inside the discharge transaction (app/orchestration/). The app
    stays useful at home for a fixed window; readmission reopens it."""
    # Since 2026-11-09 access does not end after discharge: the app is how a
    # patient at home gets reminders. Staff turn it off when it should stop.
    accounts = db.query(PatientAppAccount).filter(PatientAppAccount.patient_id == patient.id).all()
    for account in accounts:  # the patient's own login and every caregiver's
        account.access_expires_at = None
    db.flush()


def request_sign_in_link(db: Session, email: str) -> Callable[[], object] | None:
    """"Forgot password": makes a reset link if the address belongs to a
    login with app access, and returns the email to send. The caller sends it
    after answering, so the response takes the same time either way and never
    confirms who is a patient."""
    email = normalize_email(email)
    if not email:
        return None
    account = (
        db.query(PatientAppAccount)
        .filter(func.lower(PatientAppAccount.email) == email, PatientAppAccount.status != STATUS_REVOKED)
        .first()
    )
    if account is None or _access_expired(account):
        return None
    token = _create_link(db, account, PURPOSE_SIGN_IN)
    db.commit()
    return partial(
        email_module.send_patient_password_reset_email,
        account.email,
        link_url(token),
        get_settings().patient_sign_in_link_ttl_minutes // 60,
    )


@dataclass(frozen=True)
class LinkInfo:
    email: str | None
    first_time: bool  # no password yet: "Create your password", else "Choose a new password"


def _live_link(db: Session, raw_token: str) -> tuple[PatientSignInLink, PatientAppAccount]:
    now = datetime.now(timezone.utc)
    link = db.query(PatientSignInLink).filter(PatientSignInLink.token_hash == _hash(raw_token)).first()
    if link is None or link.used_at is not None or link.expires_at <= now:
        raise InvalidSignInLinkError()
    # Links made before caregivers existed carry no account: the patient's own.
    account = db.get(PatientAppAccount, link.account_id) if link.account_id else get_account(db, link.patient_id)
    if account is None or account.status == STATUS_REVOKED or _access_expired(account):
        raise InvalidSignInLinkError()
    return link, account


def link_info(db: Session, raw_token: str) -> LinkInfo:
    """What the link page should say, without spending the link."""
    _link, account = _live_link(db, raw_token)
    return LinkInfo(email=account.email, first_time=account.password_hash is None)


def _check_password(password: str) -> None:
    if not (PASSWORD_MIN <= len(password) <= PASSWORD_MAX):
        raise PatientAppError(f"Use at least {PASSWORD_MIN} characters.")


def set_password(db: Session, raw_token: str, password: str) -> tuple[Patient, PatientAppAccount]:
    """Spends an invite or reset link and sets the login's password. The
    caller then issues a session token. Choosing a new password signs out
    every other device."""
    _check_password(password)
    link, account = _live_link(db, raw_token)
    now = datetime.now(timezone.utc)
    # Spend it in one conditional UPDATE: of two requests racing with the same
    # link, exactly one sets the password.
    spent = (
        db.query(PatientSignInLink)
        .filter(PatientSignInLink.id == link.id, PatientSignInLink.used_at.is_(None))
        .update({PatientSignInLink.used_at: now}, synchronize_session=False)
    )
    if spent != 1:
        raise InvalidSignInLinkError()
    if account.password_hash is not None:
        account.session_version += 1  # a reset: whoever else was signed in is out
    account.password_hash = hash_password(password)
    account.password_set_at = now
    if account.status == STATUS_INVITED:
        account.status = STATUS_ACTIVE
        account.activated_at = now
    account.last_sign_in_at = now
    patient = db.get(Patient, link.patient_id)
    record_event(
        db,
        event_type=AuditEventType.PATIENT_APP_SIGNED_IN,
        actor_type=ActorType.PATIENT,
        patient_id=patient.id,
        entity_type="PatientAppAccount",
        entity_id=account.id,
        event_metadata={"via": f"{link.purpose}_password_set", "role": account.role},
    )
    db.commit()
    return patient, account


class WrongPasswordError(Exception):
    """Email or password wrong, or the login cannot be used: one message for all."""


def sign_in_with_password(db: Session, email: str, password: str) -> tuple[Patient, PatientAppAccount]:
    email = normalize_email(email) or ""
    account = (
        db.query(PatientAppAccount)
        .filter(func.lower(PatientAppAccount.email) == email, PatientAppAccount.status == STATUS_ACTIVE)
        .first()
    )
    # Checked even without an account, so a missing login takes as long as a wrong password.
    hashed = account.password_hash if account and account.password_hash else _DUMMY_HASH
    ok = verify_password(password, hashed)
    if account is None or account.password_hash is None or not ok or _access_expired(account):
        raise WrongPasswordError()
    patient = db.get(Patient, account.patient_id)
    now = datetime.now(timezone.utc)
    account.last_sign_in_at = now
    record_event(
        db,
        event_type=AuditEventType.PATIENT_APP_SIGNED_IN,
        actor_type=ActorType.PATIENT,
        patient_id=patient.id,
        entity_type="PatientAppAccount",
        entity_id=account.id,
        event_metadata={"via": "password", "role": account.role},
    )
    db.commit()
    return patient, account


_DUMMY_HASH = hash_password("not a real password - timing only")


def authorize(
    db: Session, patient_id: uuid.UUID, account_id: uuid.UUID | None, session_version: int
) -> tuple[Patient, PatientAppAccount]:
    """Every patient-app request: the login must still be live, belong to
    this patient, and the token be from its current session generation."""
    account = db.get(PatientAppAccount, account_id) if account_id else get_account(db, patient_id)
    if (
        account is None
        or account.patient_id != patient_id
        or account.status != STATUS_ACTIVE
        or account.session_version != session_version
        or _access_expired(account)
    ):
        raise PatientAccessDeniedError()
    patient = db.get(Patient, patient_id)
    if patient is None:
        raise PatientAccessDeniedError()
    return patient, account


def list_visits(db: Session, patient_id: uuid.UUID) -> list[Encounter]:
    return (
        db.query(Encounter)
        .filter(Encounter.patient_id == patient_id)
        .order_by(Encounter.admission_date.desc(), Encounter.created_at.desc())
        .all()
    )
