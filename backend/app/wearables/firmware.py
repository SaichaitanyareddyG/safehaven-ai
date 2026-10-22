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
from datetime import datetime, timedelta, timezone

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


def _version_key(version: str | None) -> tuple[int, ...] | None:
    """"0.5.10" -> (0, 5, 10). None for anything else ("0.4.0-link", "dev")."""
    if not version:
        return None
    parts = version.strip().split(".")
    if not all(p.isdigit() for p in parts):
        return None
    return tuple(int(p) for p in parts)


# Off the charger a band needs at least this much battery to update.
MIN_BATTERY_FOR_UPDATE = 30
# How long an "Update now" request stays good.
UPDATE_REQUEST_TTL = timedelta(hours=2)


def newer_release(db: Session, running_version: str | None) -> FirmwareRelease | None:
    """The published release if it is NEWER than what the band runs. Never a
    downgrade: a band flashed by cable with a newer build keeps it. A band
    reporting a version that is not plain numbers (an old or bench build) is
    offered the release."""
    release = current_release(db)
    if release is None or release.version == running_version:
        return None
    newest, running = _version_key(release.version), _version_key(running_version)
    if newest is None:
        return None
    if running is not None and newest <= running:
        return None
    return release


def update_offer(
    db: Session,
    running_version: str | None,
    charging: bool,
    *,
    assigned: bool = True,
    battery_percent: int | None = None,
    update_requested_at: datetime | None = None,
) -> tuple[FirmwareRelease, bool] | None:
    """(release, allowed on battery) for this check-in, or None.

    On the charger a band is not monitoring: any newer release is offered.
    On battery only with 30%+ charge, and only if the band is not on a
    patient, or staff pressed "Update now" for it: while it downloads its
    alerts can be delayed by a few minutes, and it restarts once."""
    release = newer_release(db, running_version)
    if release is None:
        return None
    if charging:
        return release, False
    if battery_percent is None or battery_percent < MIN_BATTERY_FOR_UPDATE:
        return None
    requested = update_requested_at is not None and update_requested_at > datetime.now(timezone.utc) - UPDATE_REQUEST_TTL
    if not assigned or requested:
        return release, True
    return None


def publish(db: Session, version: str, image: bytes, notes: str | None = None) -> FirmwareRelease:
    if _version_key(version) is None:
        raise ValueError("Version must be plain numbers, like 0.5.2")
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
