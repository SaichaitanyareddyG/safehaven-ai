import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, field_validator

from app.patients.models import AdmissionStatus, Language


def _validate_not_future(value: date | None) -> date | None:
    if value is not None and value > date.today():
        raise ValueError("date_of_birth cannot be in the future")
    return value


class PatientCreate(BaseModel):
    first_name: str
    last_name: str
    date_of_birth: date
    room_number: str | None = None
    preferred_language: Language = Language.ENGLISH

    _validate_dob = field_validator("date_of_birth")(_validate_not_future)


class PatientUpdate(BaseModel):
    first_name: str | None = None
    last_name: str | None = None
    date_of_birth: date | None = None
    room_number: str | None = None
    preferred_language: Language | None = None
    admission_status: AdmissionStatus | None = None

    _validate_dob = field_validator("date_of_birth")(_validate_not_future)


class PatientRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    patient_code: str
    first_name: str
    last_name: str
    date_of_birth: date
    room_number: str | None
    preferred_language: Language
    admission_status: AdmissionStatus
    created_at: datetime
    updated_at: datetime


class PatientListResponse(BaseModel):
    total: int
    results: list[PatientRead]
