"""User management for admins: the dashboard's Users page.

Accounts are created with a one-time password the admin hands over in person;
it works only to choose a new one (see get_current_user). Users are
deactivated, never deleted, so audit rows keep a real person behind them.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.audit.models import ActorType, AuditEventType
from app.audit.service import record_event
from app.auth.dependencies import require_admin
from app.auth.models import ROLE_ADMIN, User
from app.auth.provider import AuthenticatedUser
from app.auth.schemas import AdminUserCreate, AdminUserRead, AdminUserUpdate, OneTimePasswordResponse
from app.auth.security import generate_one_time_password, hash_password
from app.core.db import get_db

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


@router.get("", response_model=list[AdminUserRead])
def list_users(_: Admin, db: Db) -> list[User]:
    # Active first, then by name: the people a ward actually has.
    return db.query(User).order_by(User.is_active.desc(), User.full_name).all()


@router.post("", response_model=OneTimePasswordResponse, status_code=status.HTTP_201_CREATED)
def create_user(payload: AdminUserCreate, admin: Admin, db: Db) -> OneTimePasswordResponse:
    email = payload.email.lower()
    if db.query(User).filter(User.email == email).first() is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="A user with this email already exists")

    password = generate_one_time_password()
    user = User(
        email=email,
        full_name=payload.full_name.strip(),
        role=payload.role,
        hashed_password=hash_password(password),
        must_change_password=True,
    )
    db.add(user)
    db.flush()
    _audit(db, admin, AuditEventType.USER_CREATED, user, role=user.role)
    db.commit()
    db.refresh(user)
    return OneTimePasswordResponse(user=AdminUserRead.model_validate(user), one_time_password=password)


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


@router.post("/{user_id}/reset-password", response_model=OneTimePasswordResponse)
def reset_password(user_id: uuid.UUID, admin: Admin, db: Db) -> OneTimePasswordResponse:
    user = _get_user(db, user_id)
    if str(user.id) == admin.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Change your own password from your menu")

    password = generate_one_time_password()
    user.hashed_password = hash_password(password)
    user.must_change_password = True
    _audit(db, admin, AuditEventType.USER_PASSWORD_RESET, user)
    db.commit()
    db.refresh(user)
    return OneTimePasswordResponse(user=AdminUserRead.model_validate(user), one_time_password=password)
