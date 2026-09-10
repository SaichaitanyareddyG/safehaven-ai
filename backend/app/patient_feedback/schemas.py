import uuid
from datetime import datetime

from pydantic import BaseModel

from app.patient_feedback.models import ComprehensionResponse


class ComprehensionFeedbackCreate(BaseModel):
    token: str
    instruction_id: uuid.UUID
    response: ComprehensionResponse


class ComprehensionFeedbackRead(BaseModel):
    care_instruction_id: uuid.UUID
    response: ComprehensionResponse
    created_at: datetime

    model_config = {"from_attributes": True}
