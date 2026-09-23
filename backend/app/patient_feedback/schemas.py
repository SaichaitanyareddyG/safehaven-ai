import uuid
from datetime import datetime

from pydantic import BaseModel, Field

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


class TeachBackSubmit(BaseModel):
    token: str
    instruction_id: uuid.UUID
    response_text: str = Field(min_length=1, max_length=2000)


class TeachBackResult(BaseModel):
    care_instruction_id: uuid.UUID
    passed: bool
    confirmed_facts: list[str]
    missing_facts: list[str]
    created_at: datetime

    model_config = {"from_attributes": True}
