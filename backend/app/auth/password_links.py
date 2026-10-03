"""Single-use links to set a password: the invite an admin sends a new user,
and "forgot password". Only a SHA-256 of the token is stored (like care
links), so a database leak gives no working link. A link is spent when used,
and making a new one cancels the user's older ones.
"""

import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.auth.models import User
from app.core.config import get_settings
from app.core.db import Base

PURPOSE_INVITE = "invite"
PURPOSE_RESET = "reset"


class PasswordLink(Base):
    __tablename__ = "password_links"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    purpose: Mapped[str] = mapped_column(String(20), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )


class InvalidPasswordLinkError(Exception):
    """Unknown, expired, used or for a deactivated user — deliberately one error."""


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def link_url(token: str) -> str:
    # In the fragment, not the query: browsers never send it to a server, so
    # it stays out of access logs and Referer headers.
    return f"{get_settings().dashboard_url.rstrip('/')}/set-password#token={token}"


def create_link(db: Session, user: User, purpose: str) -> tuple[str, PasswordLink]:
    """Returns (raw_token, record). The raw token exists only here."""
    settings = get_settings()
    now = datetime.now(timezone.utc)
    lifetime = (
        timedelta(hours=settings.invite_link_ttl_hours)
        if purpose == PURPOSE_INVITE
        else timedelta(minutes=settings.reset_link_ttl_minutes)
    )
    db.query(PasswordLink).filter(PasswordLink.user_id == user.id, PasswordLink.used_at.is_(None)).update(
        {PasswordLink.used_at: now}
    )
    token = secrets.token_urlsafe(32)
    record = PasswordLink(user_id=user.id, token_hash=_hash(token), purpose=purpose, expires_at=now + lifetime)
    db.add(record)
    db.flush()
    return token, record


def resolve_link(db: Session, token: str) -> tuple[PasswordLink, User]:
    record = db.query(PasswordLink).filter(PasswordLink.token_hash == _hash(token)).first()
    if record is None or record.used_at is not None or record.expires_at <= datetime.now(timezone.utc):
        raise InvalidPasswordLinkError()
    user = db.get(User, record.user_id)
    if user is None or not user.is_active:
        raise InvalidPasswordLinkError()
    return record, user


def unusable_password() -> str:
    """For an invited user who has not chosen one yet: nobody knows it."""
    return secrets.token_urlsafe(32)
