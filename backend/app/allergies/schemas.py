import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class PatientAllergyCreate(BaseModel):
    allergen: str = Field(min_length=1, max_length=255)
    reaction: str | None = Field(default=None, max_length=255)
    severity: str | None = Field(default=None, max_length=50)


class PatientAllergyRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    patient_id: uuid.UUID
    allergen: str
    reaction: str | None
    severity: str | None
    documented_by: uuid.UUID
    documented_at: datetime


class PatientAllergyListResponse(BaseModel):
    total: int
    results: list[PatientAllergyRead]
