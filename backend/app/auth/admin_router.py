"""User management for admins: the dashboard's Users page.

A new user gets an invite link by email (single use, expires) and chooses
their own password; the admin never knows it. The link is also returned, so
the admin can pass it on another way if email fails. Users are deactivated,
never deleted, so audit rows keep a real person behind them.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.audit.models import ActorType, AuditEventType
from app.audit.service import record_event
from app.auth.dependencies import require_admin
from app.auth.models import ROLE_ADMIN, User
from app.auth.password_links import PURPOSE_INVITE, PURPOSE_RESET, create_link, link_url, unusable_password
from app.auth.provider import AuthenticatedUser
from app.auth.schemas import AdminUserCreate, AdminUserRead, AdminUserUpdate, InviteResponse
from app.auth.security import hash_password
from app.core.config import get_settings
from app.core.db import get_db
from app.core.email import send_invite_email, send_reset_email

router = APIRouter(prefix="/admin/users", tags=["admin"])

Admin = Annotated[AuthenticatedUser, Depends(require_admin)]
Db = Annotated[Session, Depends(get_db)]


def _audit(db: Session, admin: AuthenticatedUser, event_type: AuditEventType, user: User, **metadata) -> None:
    record_event(
        db,
        event_type=event_type,
        actor_type=ActorType.CLINICIAN,
        actor_id=uuid.UUID(admin.id),
        entity_type="User",
        entity_id=user.id,
        event_metadata=metadata or None,
    )


def _get_user(db: Session, user_id: uuid.UUID) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return user


def _send_link(db: Session, user: User, purpose: str) -> InviteResponse:
    """Make the link, commit, then email it (after the commit, so a slow mail
    service never holds the transaction open)."""
    settings = get_settings()
    token, record = create_link(db, user, purpose)
    db.commit()
    db.refresh(user)
    link = link_url(token)
    if purpose == PURPOSE_INVITE:
        result = send_invite_email(user.email, user.full_name, link, settings.invite_link_ttl_hours)
    else:
        result = send_reset_email(user.email, user.full_name, link, settings.reset_link_ttl_minutes)
    return InviteResponse(
        user=AdminUserRead.model_validate(user),
        link=link,
        link_expires_at=record.expires_at,
        emailed=result.sent,
        email_problem=result.problem,
    )


@router.get("", response_model=list[AdminUserRead])
def list_users(_: Admin, db: Db) -> list[User]:
    # Active first, then by name: the people a ward actually has.
    return db.query(User).order_by(User.is_active.desc(), User.full_name).all()


@router.post("", response_model=InviteResponse, status_code=status.HTTP_201_CREATED)
def create_user(payload: AdminUserCreate, admin: Admin, db: Db) -> InviteResponse:
    email = payload.email.lower()
    if db.query(User).filter(User.email == email).first() is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="A user with this email already exists")

    user = User(
        email=email,
        full_name=payload.full_name.strip(),
        role=payload.role,
        # Nobody knows this one: the user signs in only after choosing
        # their own through the invite link. must_change_password marks
        # them "Invited" until then.
        hashed_password=hash_password(unusable_password()),
        must_change_password=True,
    )
    db.add(user)
    db.flush()
    _audit(db, admin, AuditEventType.USER_CREATED, user, role=user.role)
    return _send_link(db, user, PURPOSE_INVITE)


@router.patch("/{user_id}", response_model=AdminUserRead)
def update_user(user_id: uuid.UUID, payload: AdminUserUpdate, admin: Admin, db: Db) -> User:
    user = _get_user(db, user_id)
    # An admin locking themselves out could leave the ward with no admin at
    # all; another admin has to do it.
    if str(user.id) == admin.id and (payload.is_active is False or (payload.role and payload.role != ROLE_ADMIN)):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="You cannot remove your own admin access")

    changes = {}
    if payload.role is not None and payload.role != user.role:
        changes["role"] = payload.role
        user.role = payload.role
    if payload.is_active is not None and payload.is_active != user.is_active:
        changes["is_active"] = payload.is_active
        user.is_active = payload.is_active
    if changes:
        _audit(db, admin, AuditEventType.USER_UPDATED, user, **changes)
        db.commit()
        db.refresh(user)
    return user


@router.post("/{user_id}/send-link", response_model=InviteResponse)
def send_password_link(user_id: uuid.UUID, admin: Admin, db: Db) -> InviteResponse:
    """Resend the invite to someone who has not set a password yet, or send a
    reset link to someone who has. Their current password keeps working
    until they use the link; older links stop working."""
    user = _get_user(db, user_id)
    if str(user.id) == admin.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Change your own password from your menu")
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Reactivate this user first")

    purpose = PURPOSE_INVITE if user.must_change_password else PURPOSE_RESET
    _audit(db, admin, AuditEventType.USER_PASSWORD_RESET, user, purpose=purpose)
    return _send_link(db, user, purpose)
