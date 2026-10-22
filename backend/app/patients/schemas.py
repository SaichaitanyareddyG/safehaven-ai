import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.patients.models import AdmissionStatus, Language


def _validate_not_future(value: date | None) -> date | None:
    if value is not None and value > date.today():
        raise ValueError("date_of_birth cannot be in the future")
    return value


def _clean_email(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip().lower()
    if not value:
        return None
    local, _, domain = value.partition("@")
    if not local or "." not in domain or " " in value:
        raise ValueError("Enter a valid email address")
    return value


def _clean_phone(value: str | None) -> str | None:
    if value is None:
        return None
    return value.strip() or None


class PatientCreate(BaseModel):
    first_name: str
    last_name: str
    date_of_birth: date
    room_number: str | None = None
    preferred_language: Language = Language.ENGLISH
    # Why the patient has come in. Optional on the API so existing callers
    # keep working, but asked for in the registration form — the Encounter
    # model has carried reason_for_visit from the start and almost nothing
    # ever populated it, because the only way to set it was a separate panel
    # further down the patient page that nobody had reason to open. Supplying
    # it here opens the patient's first encounter in the same step.
    reason_for_visit: str | None = None
    # For the patient app. With app_consent, saving also emails the patient
    # an invite (see patients/router.py). Both optional: no email, no invite.
    email: str | None = Field(default=None, max_length=320)
    phone: str | None = Field(default=None, max_length=40)
    app_consent: bool = False

    _validate_dob = field_validator("date_of_birth")(_validate_not_future)
    _validate_email = field_validator("email")(_clean_email)
    _validate_phone = field_validator("phone")(_clean_phone)


class PatientUpdate(BaseModel):
    first_name: str | None = None
    last_name: str | None = None
    date_of_birth: date | None = None
    room_number: str | None = None
    preferred_language: Language | None = None
    admission_status: AdmissionStatus | None = None
    email: str | None = Field(default=None, max_length=320)
    phone: str | None = Field(default=None, max_length=40)

    _validate_dob = field_validator("date_of_birth")(_validate_not_future)
    _validate_email = field_validator("email")(_clean_email)
    _validate_phone = field_validator("phone")(_clean_phone)


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
    email: str | None = None
    phone: str | None = None
    created_at: datetime
    updated_at: datetime


class AppInviteOutcome(BaseModel):
    """What happened to the patient-app invite sent while registering."""

    emailed: bool
    problem: str | None = None
    link: str | None = None


class PatientCreateResponse(PatientRead):
    app_invite: AppInviteOutcome | None = None


class PatientListResponse(BaseModel):
    total: int
    results: list[PatientRead]


class MissedDosesFlag(BaseModel):
    patient_id: uuid.UUID
    date: date
    missed: int
    skipped: int


class MissedDosesResponse(BaseModel):
    flags: list[MissedDosesFlag]


class CarePlanPrintout(BaseModel):
    """Everything the printed care plan shows, in one call (staff)."""

    patient_first_name: str
    patient_last_name: str
    patient_code: str
    date_of_birth: date
    care_plan: "PatientCarePlanResponse"
    appointments: list["AppointmentRead"]
    printed_at: datetime


from app.appointments.schemas import AppointmentRead  # noqa: E402
from app.patient_access.schemas import PatientCarePlanResponse  # noqa: E402

CarePlanPrintout.model_rebuild()
