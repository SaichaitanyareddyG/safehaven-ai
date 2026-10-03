import uuid
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.audit.models import ActorType, AuditEventType
from app.audit.service import record_event
from app.auth.dependencies import get_signed_in_user
from app.auth.models import User
from app.auth.provider import AuthenticatedUser, AuthError, get_auth_provider
from app.auth.password_links import PURPOSE_RESET, InvalidPasswordLinkError, create_link, link_url, resolve_link
from app.auth.schemas import (
    ChangePasswordRequest,
    ForgotPasswordRequest,
    LoginRequest,
    PasswordLinkInfo,
    RegisterRequest,
    SetPasswordRequest,
    TokenResponse,
    UserRead,
)
from app.auth.security import hash_password, verify_password
from app.core.config import get_settings
from app.core.db import get_db
from app.core.email import send_reset_email
from app.core.rate_limit import limiter

router = APIRouter(prefix="/auth", tags=["auth"])

# Prototype-scale, per-IP limits — generous enough that a real clinician
# mistyping their password a few times never gets blocked, tight enough to
# make a credential-stuffing script slow and noisy rather than free. Not a
# claim of enterprise-grade brute-force protection (see the security plan).
#
# Deliberately per-IP, not per-account: a real hospital may have many staff
# behind one NAT gateway sharing a single apparent IP, so this is set high
# enough that ordinary shared-network usage doesn't collide with it — this
# is a blunt instrument against a single actor hammering the endpoint, not a
# precise per-account brute-force lockout (that would need a different key,
# e.g. the attempted email, which is a real but separate design decision —
# deferred for now per explicit choice, not an oversight).
_LOGIN_RATE_LIMIT = "30/minute"
_REGISTER_RATE_LIMIT = "15/minute"
# Each one can send an email: kept low so the form cannot be used to flood
# someone's inbox or burn the email allowance.
_FORGOT_RATE_LIMIT = "5/minute"


@router.post("/login", response_model=TokenResponse)
@limiter.limit(_LOGIN_RATE_LIMIT)
def login(request: Request, payload: LoginRequest, db: Annotated[Session, Depends(get_db)]) -> TokenResponse:
    provider = get_auth_provider(db)
    try:
        user = provider.authenticate(payload.email, payload.password)
    except AuthError as exc:
        # No actor_id — authentication failed, so there is no authenticated
        # user to attribute this to. Recorded as SYSTEM, same pattern as
        # other actor-less events (see AuditEventType docstring). The
        # attempted email is logged (not the password) so a targeted
        # brute-force pattern against one account is visible in the audit
        # trail — this is the "failed logins leave no trace at all" gap the
        # security review found.
        record_event(
            db,
            event_type=AuditEventType.LOGIN_FAILED,
            actor_type=ActorType.SYSTEM,
            event_metadata={"email": payload.email},
        )
        db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc

    db.query(User).filter(User.id == uuid.UUID(user.id)).update({User.last_login_at: datetime.now(timezone.utc)})
    record_event(
        db,
        event_type=AuditEventType.USER_LOGIN,
        actor_type=ActorType.CLINICIAN,
        actor_id=uuid.UUID(user.id),
        entity_type="User",
        entity_id=uuid.UUID(user.id),
    )
    db.commit()

    return TokenResponse(access_token=provider.create_token(user))


@router.post("/register", response_model=UserRead, status_code=status.HTTP_201_CREATED)
@limiter.limit(_REGISTER_RATE_LIMIT)
def register(request: Request, payload: RegisterRequest, db: Annotated[Session, Depends(get_db)]) -> User:
    """Dev-only convenience for creating clinician accounts locally. Not part of the
    Phase 1 product API surface — on a shared server ALLOW_SELF_REGISTRATION is
    off and an admin creates accounts (app/auth/admin_router.py); Cognito will
    own user provisioning in later phases."""
    settings = get_settings()
    if settings.auth_provider != "dev" or not settings.allow_self_registration:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not available")

    if db.query(User).filter(User.email == payload.email).first() is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")

    user = User(
        email=payload.email,
        hashed_password=hash_password(payload.password),
        full_name=payload.full_name,
        role="clinician",
        # Dev and test accounts (and the scripted demo) skip the first-run
        # tour; it is for people an admin invites. Replayable from the menu.
        tour_completed_at=datetime.now(timezone.utc),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.get("/me", response_model=UserRead)
def me(current_user: Annotated[AuthenticatedUser, Depends(get_signed_in_user)]) -> AuthenticatedUser:
    return current_user


@router.post("/change-password", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit(_LOGIN_RATE_LIMIT)
def change_password(
    request: Request,
    payload: ChangePasswordRequest,
    current_user: Annotated[AuthenticatedUser, Depends(get_signed_in_user)],
    db: Annotated[Session, Depends(get_db)],
) -> None:
    """Also how a new user replaces the one-time password an admin gave them."""
    user = db.get(User, uuid.UUID(current_user.id))
    if user is None or not verify_password(payload.current_password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Current password is incorrect")
    if payload.new_password == payload.current_password:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Choose a password you have not used here")

    user.hashed_password = hash_password(payload.new_password)
    user.must_change_password = False
    record_event(
        db,
        event_type=AuditEventType.USER_PASSWORD_CHANGED,
        actor_type=ActorType.CLINICIAN,
        actor_id=user.id,
        entity_type="User",
        entity_id=user.id,
    )
    db.commit()


@router.post("/tour-complete", status_code=status.HTTP_204_NO_CONTENT)
def tour_complete(
    current_user: Annotated[AuthenticatedUser, Depends(get_signed_in_user)],
    db: Annotated[Session, Depends(get_db)],
) -> None:
    """The dashboard's first-run guided tour was finished or skipped."""
    db.query(User).filter(User.id == uuid.UUID(current_user.id), User.tour_completed_at.is_(None)).update(
        {User.tour_completed_at: datetime.now(timezone.utc)}
    )
    db.commit()


_LINK_INVALID = "This link has expired or was already used. Ask your admin for a new one, or use Forgot password."


@router.post("/forgot-password", status_code=status.HTTP_202_ACCEPTED)
@limiter.limit(_FORGOT_RATE_LIMIT)
def forgot_password(request: Request, payload: ForgotPasswordRequest, db: Annotated[Session, Depends(get_db)]) -> dict:
    """Emails a reset link. Always the same answer, so the form never reveals
    which addresses have an account."""
    user = db.query(User).filter(func.lower(User.email) == payload.email.strip().lower()).first()
    if user is not None and user.is_active:
        token, _ = create_link(db, user, PURPOSE_RESET)
        record_event(
            db,
            event_type=AuditEventType.PASSWORD_RESET_REQUESTED,
            actor_type=ActorType.SYSTEM,
            entity_type="User",
            entity_id=user.id,
        )
        db.commit()
        send_reset_email(user.email, user.full_name, link_url(token), get_settings().reset_link_ttl_minutes)
    return {"detail": "If that address has an account, a reset link is on its way."}


@router.get("/password-link/{token}", response_model=PasswordLinkInfo)
@limiter.limit(_LOGIN_RATE_LIMIT)
def password_link(request: Request, token: str, db: Annotated[Session, Depends(get_db)]) -> PasswordLinkInfo:
    try:
        record, user = resolve_link(db, token)
    except InvalidPasswordLinkError as exc:
        raise HTTPException(status_code=status.HTTP_410_GONE, detail=_LINK_INVALID) from exc
    return PasswordLinkInfo(purpose=record.purpose, email=user.email, full_name=user.full_name)


@router.post("/set-password", response_model=TokenResponse)
@limiter.limit(_LOGIN_RATE_LIMIT)
def set_password(request: Request, payload: SetPasswordRequest, db: Annotated[Session, Depends(get_db)]) -> TokenResponse:
    """Choose a password from an invite or reset link, and sign straight in."""
    try:
        record, user = resolve_link(db, payload.token)
    except InvalidPasswordLinkError as exc:
        raise HTTPException(status_code=status.HTTP_410_GONE, detail=_LINK_INVALID) from exc

    now = datetime.now(timezone.utc)
    user.hashed_password = hash_password(payload.new_password)
    user.must_change_password = False
    user.last_login_at = now
    record.used_at = now
    record_event(
        db,
        event_type=AuditEventType.USER_PASSWORD_CHANGED,
        actor_type=ActorType.CLINICIAN,
        actor_id=user.id,
        entity_type="User",
        entity_id=user.id,
        event_metadata={"via": record.purpose},
    )
    db.commit()

    signed_in = AuthenticatedUser(id=str(user.id), email=user.email, full_name=user.full_name, role=user.role)
    return TokenResponse(access_token=get_auth_provider(db).create_token(signed_in))
