from datetime import date
from typing import Literal

from pydantic import BaseModel

from app.schedules.dose_schedule import DoseSchedule, format_time


class DoseScheduleRead(BaseModel):
    """A medicine's dose times, derived by fixed rules from the approved facts
    (app/schedules/dose_schedule.py) — never typed in, never AI-written."""

    kind: Literal["SCHEDULED", "AS_NEEDED", "NEEDS_REVIEW"]
    # "08:00" — 24-hour, hospital local time.
    times: list[str]
    # "8:00 AM", same order as times.
    times_display: list[str]
    dose: str | None
    with_food: bool | None
    # None = no end date (continues until the care team stops it).
    duration_days: int | None
    summary: str
    problem: str | None
    # Set once the order is approved (the start is the approval day).
    start_date: date | None = None
    end_date: date | None = None


def to_read(schedule: DoseSchedule, start: date | None = None) -> DoseScheduleRead:
    return DoseScheduleRead(
        kind=schedule.kind,
        times=[t.strftime("%H:%M") for t in schedule.times],
        times_display=[format_time(t) for t in schedule.times],
        dose=schedule.dose,
        with_food=schedule.with_food,
        duration_days=schedule.duration_days,
        summary=schedule.summary(),
        problem=schedule.problem,
        start_date=start,
        end_date=schedule.end_date(start) if start else None,
    )
