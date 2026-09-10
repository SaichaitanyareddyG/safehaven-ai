import uuid
from datetime import date, datetime

from pydantic import BaseModel

from app.encounters.models import EncounterStatus


class EncounterCreate(BaseModel):
    encounter_type: str | None = None
    reason_for_visit: str | None = None
    admission_date: date
    discharge_date: date | None = None
    status: EncounterStatus = EncounterStatus.OPEN


class EncounterRead(BaseModel):
    id: uuid.UUID
    encounter_type: str | None
    reason_for_visit: str | None
    admission_date: date
    discharge_date: date | None
    status: EncounterStatus
    created_at: datetime

    model_config = {"from_attributes": True}


class EncounterListResponse(BaseModel):
    total: int
    results: list[EncounterRead]


class EncounterSummary(BaseModel):
    """The minimal encounter context attached to a CareInstruction/instruction
    detail view — "which visit did this order originate from," not the full
    encounter record."""

    id: uuid.UUID
    reason_for_visit: str | None
    admission_date: date

    model_config = {"from_attributes": True}
