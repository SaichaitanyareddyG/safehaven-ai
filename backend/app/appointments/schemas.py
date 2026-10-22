import uuid
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _aware(value: datetime | None) -> datetime | None:
    if value is not None and value.tzinfo is None:
        raise ValueError("Give the time with its time zone")
    return value


def _not_past(value: datetime | None) -> datetime | None:
    if value is not None and value < datetime.now(timezone.utc):
        raise ValueError("The appointment time is in the past")
    return value


def _strip(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


class AppointmentCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    starts_at: datetime
    location: str | None = Field(default=None, max_length=300)
    notes: str | None = Field(default=None, max_length=2000)

    _check_time = field_validator("starts_at")(lambda v: _not_past(_aware(v)))
    _clean = field_validator("location", "notes")(_strip)

    @field_validator("title")
    @classmethod
    def _title(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Say what the appointment is for")
        return value


class AppointmentUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    starts_at: datetime | None = None
    location: str | None = Field(default=None, max_length=300)
    notes: str | None = Field(default=None, max_length=2000)
    status: Literal["SCHEDULED", "CANCELLED"] | None = None

    _check_time = field_validator("starts_at")(lambda v: _not_past(_aware(v)))
    _clean = field_validator("location", "notes")(_strip)


class AppointmentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    patient_id: uuid.UUID
    title: str
    starts_at: datetime
    location: str | None
    notes: str | None
    status: str
    created_at: datetime
    updated_at: datetime


class AppointmentListResponse(BaseModel):
    results: list[AppointmentRead]
