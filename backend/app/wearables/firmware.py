"""Band firmware updates over Wi-Fi.

An admin publishes a build (scripts/publish_firmware.py). A band learns of
it in its heartbeat reply — only while it is on the charger, so a band on a
patient's wrist is never interrupted — downloads it here with its own
device credential, checks the SHA-256, installs it into the spare app slot
and restarts. If the new firmware cannot reach the backend after restarting,
the bootloader puts the previous one back (firmware: sticks3_main.cpp).

The image is served only to enrolled bands, never publicly: firmware builds
carry the ward Wi-Fi settings.
"""

import hashlib
import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Integer, LargeBinary, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, Session, deferred, mapped_column

from app.core.db import Base


class FirmwareRelease(Base):
    __tablename__ = "firmware_releases"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    version: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    size: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    # Loaded only when a band downloads it, never with the row.
    image: Mapped[bytes] = deferred(mapped_column(LargeBinary, nullable=False))
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    # The one release bands are offered. Publishing a new one switches it.
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )


def current_release(db: Session) -> FirmwareRelease | None:
    return db.query(FirmwareRelease).filter(FirmwareRelease.is_current.is_(True)).first()


def update_offer(db: Session, running_version: str | None, charging: bool) -> FirmwareRelease | None:
    """The release this band should install now, if any: a different
    version is current, and the band is on its charger (not monitoring)."""
    if not charging:
        return None
    release = current_release(db)
    if release is None or release.version == running_version:
        return None
    return release


def publish(db: Session, version: str, image: bytes, notes: str | None = None) -> FirmwareRelease:
    if not image or image[0] != 0xE9:  # every ESP32 app image starts with this magic byte
        raise ValueError("Not an ESP32 firmware image")
    existing = db.query(FirmwareRelease).filter(FirmwareRelease.version == version).first()
    if existing is not None:
        raise ValueError(f"Version {version} was already published")
    db.query(FirmwareRelease).update({FirmwareRelease.is_current: False})
    release = FirmwareRelease(
        version=version,
        size=len(image),
        sha256=hashlib.sha256(image).hexdigest(),
        image=image,
        notes=notes,
        is_current=True,
    )
    db.add(release)
    db.commit()
    db.refresh(release)
    return release
