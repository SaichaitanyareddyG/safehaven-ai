"""Wi-Fi networks the bands should know, managed by admins on the Bands page.

A band receives the list at its next check-in (it sees a new version in the
heartbeat reply and fetches /device-api/wifi-networks with its credential),
keeps every network, and joins the strongest one it can see. So before bands
move to a new ward or site, its Wi-Fi is added here and they are ready.

Passwords are encrypted at rest (Fernet). The key is WIFI_SECRET_KEY, or one
derived from JWT_SECRET_KEY when that is unset; changing that secret means
re-entering the passwords. They are never returned to the dashboard, only to
an authenticated band over TLS.
"""

import base64
import hashlib
import uuid
from datetime import datetime, timezone

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.core.config import get_settings
from app.core.db import Base

SECURITY_PSK = "PSK"  # one shared password (home/office/hotspot)
SECURITY_EAP = "EAP"  # WPA2-Enterprise: a username and password (PEAP)

# The band keeps at most this many server networks (NVS space, scan time).
MAX_NETWORKS = 8


class WifiNetwork(Base):
    __tablename__ = "wifi_networks"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    label: Mapped[str] = mapped_column(String(100), nullable=False)
    ssid: Mapped[str] = mapped_column(String(32), nullable=False)
    security: Mapped[str] = mapped_column(String(8), nullable=False, default=SECURITY_PSK)
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    identity: Mapped[str | None] = mapped_column(String(64), nullable=True)
    password_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )


class WifiError(Exception):
    """Safe to show."""


def _fernet() -> Fernet:
    settings = get_settings()
    if settings.wifi_secret_key:
        return Fernet(settings.wifi_secret_key.encode())
    key = HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=b"safehaven-wifi-networks").derive(
        settings.jwt_secret_key.encode()
    )
    return Fernet(base64.urlsafe_b64encode(key))


def encrypt(password: str) -> str:
    return _fernet().encrypt(password.encode()).decode()


def decrypt(token: str) -> str | None:
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken:
        return None  # key changed: the network is skipped until re-entered


def list_networks(db: Session) -> list[WifiNetwork]:
    return db.query(WifiNetwork).order_by(WifiNetwork.created_at.asc()).all()


def version(db: Session) -> str:
    """Changes whenever the list changes; the band re-fetches when it does."""
    rows = list_networks(db)
    digest = hashlib.sha256("|".join(f"{n.id}:{n.created_at.isoformat()}" for n in rows).encode()).hexdigest()
    return digest[:16] if rows else "empty"


def add_network(
    db: Session,
    created_by: uuid.UUID,
    *,
    label: str,
    ssid: str,
    security: str,
    password: str,
    username: str | None,
    identity: str | None,
) -> WifiNetwork:
    ssid = ssid.strip()
    label = label.strip() or ssid
    if not ssid or len(ssid.encode()) > 32:
        raise WifiError("A network name is 1 to 32 characters.")
    if security == SECURITY_PSK and not 8 <= len(password) <= 63:
        raise WifiError("A Wi-Fi password is 8 to 63 characters.")
    if security == SECURITY_EAP and (not username or not password):
        raise WifiError("A WPA2-Enterprise network needs a username and a password.")
    if len(list_networks(db)) >= MAX_NETWORKS:
        raise WifiError(f"Bands keep at most {MAX_NETWORKS} networks. Remove one first.")
    if db.query(WifiNetwork).filter(WifiNetwork.ssid == ssid).first() is not None:
        raise WifiError("That network is already on the list. Remove it and add it again to change it.")
    network = WifiNetwork(
        label=label[:100],
        ssid=ssid,
        security=security,
        username=(username or "").strip() or None,
        identity=(identity or "").strip() or None,
        password_encrypted=encrypt(password),
        created_by=created_by,
    )
    db.add(network)
    db.flush()
    return network


def remove_network(db: Session, network_id: uuid.UUID) -> WifiNetwork | None:
    network = db.get(WifiNetwork, network_id)
    if network is not None:
        db.delete(network)
        db.flush()
    return network


def for_band(db: Session) -> list[dict]:
    """The list as a band needs it, passwords included."""
    out = []
    for n in list_networks(db):
        password = decrypt(n.password_encrypted)
        if password is None:
            continue
        out.append(
            {"ssid": n.ssid, "security": n.security, "password": password, "username": n.username, "identity": n.identity}
        )
    return out
