import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class PatientConditionCreate(BaseModel):
    condition_name: str = Field(min_length=1, max_length=255)
    # Optional — a condition can be documented during a specific visit, or as
    # general/historical patient context not tied to any visit. Either way,
    # never used to infer a medication's indication (see the model's
    # docstring).
    encounter_id: uuid.UUID | None = None


class PatientConditionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    patient_id: uuid.UUID
    encounter_id: uuid.UUID | None
    condition_name: str
    documented_by: uuid.UUID
    documented_at: datetime


class PatientConditionListResponse(BaseModel):
    total: int
    results: list[PatientConditionRead]
