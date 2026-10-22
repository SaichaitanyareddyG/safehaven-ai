import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.encounters.models import EncounterStatus
from app.patients.models import AdmissionStatus, Language
from app.patients.schemas import _clean_email, _clean_phone

AppAccessStatus = Literal["NOT_INVITED", "INVITED", "ACTIVE", "REVOKED", "EXPIRED"]


# --- Staff side -------------------------------------------------------------


class CaregiverRead(BaseModel):
    id: uuid.UUID
    display_name: str | None
    relationship: str | None
    email: str | None
    status: AppAccessStatus
    invited_at: datetime | None
    last_sign_in_at: datetime | None


class AppAccessRead(BaseModel):
    status: AppAccessStatus
    email: str | None
    phone: str | None
    consent_at: datetime | None
    invited_at: datetime | None = None
    activated_at: datetime | None = None
    last_sign_in_at: datetime | None = None
    access_expires_at: datetime | None = None
    caregivers: list[CaregiverRead] = []


class AppInviteRequest(BaseModel):
    email: str | None = Field(default=None, max_length=320)
    phone: str | None = Field(default=None, max_length=40)
    consent: bool = False

    _validate_email = field_validator("email")(_clean_email)
    _validate_phone = field_validator("phone")(_clean_phone)


class CaregiverInviteRequest(BaseModel):
    email: str = Field(max_length=320)
    name: str = Field(min_length=1, max_length=200)
    relationship: str | None = Field(default=None, max_length=100)
    # The patient agreed to share their care information with this person.
    consent: bool = False

    _validate_email = field_validator("email")(_clean_email)


class CaregiverInviteResponse(BaseModel):
    caregiver: CaregiverRead
    emailed: bool
    problem: str | None = None
    link: str | None = None


class AppInviteResponse(BaseModel):
    access: AppAccessRead
    emailed: bool
    problem: str | None = None
    link: str | None = None


# --- Patient side -----------------------------------------------------------


class SignInLinkRequest(BaseModel):
    email: str = Field(max_length=320)


class ExchangeRequest(BaseModel):
    token: str = Field(max_length=200)


class PatientSessionResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_at: datetime


class MyProfile(BaseModel):
    # Whose login this is: the patient, or a caregiver viewing their care.
    viewer_role: Literal["PATIENT", "CAREGIVER"] = "PATIENT"
    viewer_name: str | None = None
    first_name: str
    last_name: str
    preferred_language: Language
    admission_status: AdmissionStatus
    room_number: str | None
    access_expires_at: datetime | None


class MyVisit(BaseModel):
    id: uuid.UUID
    reason_for_visit: str | None
    encounter_type: str | None
    planned_procedure: str | None
    nil_by_mouth_from: datetime | None
    admission_date: date
    discharge_date: date | None
    status: EncounterStatus


class MyVisitsResponse(BaseModel):
    visits: list[MyVisit]


# --- Doses, reminders, adherence --------------------------------------------


class DoseRead(BaseModel):
    instruction_id: uuid.UUID
    medication_name: str
    dose: str | None
    with_food: bool | None
    time: str
    time_display: str
    status: Literal["TAKEN", "SKIPPED"] | None
    recorded_at: datetime | None


class MyDosesResponse(BaseModel):
    date: date
    # False while admitted: nurses give the doses, the app only lists them.
    at_home: bool
    doses: list[DoseRead]


class DoseRecordRequest(BaseModel):
    instruction_id: uuid.UUID
    date: date
    time: str = Field(pattern=r"^\d{2}:\d{2}$")
    # None = undo.
    status: Literal["TAKEN", "SKIPPED"] | None


class PushKeys(BaseModel):
    p256dh: str = Field(max_length=200)
    auth: str = Field(max_length=100)


class PushSubscribeRequest(BaseModel):
    endpoint: str = Field(max_length=2000)
    keys: PushKeys


class PushUnsubscribeRequest(BaseModel):
    endpoint: str = Field(max_length=2000)


class PushStatus(BaseModel):
    available: bool
    public_key: str | None


class AdherenceDayRead(BaseModel):
    date: date
    due: int
    taken: int
    skipped: int


class AdherenceResponse(BaseModel):
    days: list[AdherenceDayRead]
    total_due: int
    total_taken: int
    total_skipped: int



class MyChatSend(BaseModel):
    text: str = Field(min_length=1, max_length=1000)


class MyAudioRequest(BaseModel):
    """Only text the app is already showing (approved, validated) — this
    turns it into speech, it never produces new content. English only."""

    text: str = Field(min_length=1, max_length=2000)
