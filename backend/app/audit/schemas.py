import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.audit.models import ActorType


class AuditEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    event_type: str
    actor_type: ActorType
    actor_id: uuid.UUID | None
    patient_id: uuid.UUID | None
    entity_type: str | None
    entity_id: uuid.UUID | None
    event_metadata: dict
    created_at: datetime


class AuditEventListResponse(BaseModel):
    total: int
    results: list[AuditEventRead]
