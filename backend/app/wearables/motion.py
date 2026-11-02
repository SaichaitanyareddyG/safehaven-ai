"""The fall detector's own log, for tuning it on real bands.

Every movement the band's fall detector looks at — an alert, an "Are you
OK?", or a near-miss it let go — is summarised on the band (drop height,
impact, how far and around which axis it turned, stillness after) and sent
here. Staff mark what really happened (a flip, a drop, a fall), and the
Bands page counts how each kind was treated. Raw motion stays on the band;
these rows carry no patient identity.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

OUTCOMES = ("ALERT", "CHECK", "NONE", "MUTED")
LABELS = ("FLIP", "DROP", "FALL", "ACTIVITY", "OTHER")
# Kept per band; older rows are removed as new ones arrive.
KEEP_PER_DEVICE = 500


class MotionEvent(Base):
    __tablename__ = "motion_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    device_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("wearable_devices.id", ondelete="CASCADE"), nullable=False, index=True
    )
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    firmware_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    outcome: Mapped[str] = mapped_column(String(8), nullable=False)
    freefall_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    drop_cm: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    peak_g: Mapped[float] = mapped_column(Float, nullable=False)
    turned_deg: Mapped[float] = mapped_column(Float, nullable=False)
    tilt_change_deg: Mapped[float] = mapped_column(Float, nullable=False)
    spin_dps: Mapped[float] = mapped_column(Float, nullable=False)
    axis: Mapped[str] = mapped_column(String(1), nullable=False)
    still_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    label: Mapped[str | None] = mapped_column(String(16), nullable=True)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
