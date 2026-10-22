import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.reports.models import ReportCategory


class ReportRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    category: ReportCategory
    report_date: date | None
    content_type: str
    size: int
    shared_with_patient: bool
    created_at: datetime


class ReportListResponse(BaseModel):
    results: list[ReportRead]


class ReportUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    category: ReportCategory | None = None
    report_date: date | None = None
    shared_with_patient: bool | None = None
