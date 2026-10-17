import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.encounters.models import EncounterStatus
from app.patients.models import AdmissionStatus, Language
from app.patients.schemas import _clean_email, _clean_phone

AppAccessStatus = Literal["NOT_INVITED", "INVITED", "ACTIVE", "REVOKED", "EXPIRED"]


# --- Staff side -------------------------------------------------------------


class AppAccessRead(BaseModel):
    status: AppAccessStatus
    email: str | None
    phone: str | None
    consent_at: datetime | None
    invited_at: datetime | None = None
    activated_at: datetime | None = None
    last_sign_in_at: datetime | None = None
    access_expires_at: datetime | None = None


class AppInviteRequest(BaseModel):
    email: str | None = Field(default=None, max_length=320)
    phone: str | None = Field(default=None, max_length=40)
    consent: bool = False

    _validate_email = field_validator("email")(_clean_email)
    _validate_phone = field_validator("phone")(_clean_phone)


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
