import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.audit.models import ActorType, AuditEventType
from app.audit.service import record_event
from app.auth.dependencies import get_current_user
from app.auth.models import User
from app.auth.provider import AuthenticatedUser, AuthError, get_auth_provider
from app.auth.schemas import LoginRequest, RegisterRequest, TokenResponse, UserRead
from app.auth.security import hash_password
from app.core.config import get_settings
from app.core.db import get_db
from app.core.rate_limit import limiter

router = APIRouter(prefix="/auth", tags=["auth"])

# Prototype-scale, per-IP limits — generous enough that a real clinician
# mistyping their password a few times never gets blocked, tight enough to
# make a credential-stuffing script slow and noisy rather than free. Not a
# claim of enterprise-grade brute-force protection (see the security plan).
_LOGIN_RATE_LIMIT = "10/minute"
_REGISTER_RATE_LIMIT = "5/minute"


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
    Phase 1 product API surface — Cognito will own user provisioning in later phases."""
    settings = get_settings()
    if settings.auth_provider != "dev":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not available")

    if db.query(User).filter(User.email == payload.email).first() is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")

    user = User(
        email=payload.email,
        hashed_password=hash_password(payload.password),
        full_name=payload.full_name,
        role="clinician",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.get("/me", response_model=UserRead)
def me(current_user: Annotated[AuthenticatedUser, Depends(get_current_user)]) -> AuthenticatedUser:
    return current_user
