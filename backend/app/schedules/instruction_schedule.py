"""The dose schedule of an approved medication instruction: the copy saved
when it was approved, or (for instructions approved before copies were
saved) the same rules applied to its facts."""

from datetime import date, datetime
from zoneinfo import ZoneInfo

from app.core.config import get_settings
from app.instructions.models import CareInstruction, InstructionType
from app.schedules.dose_schedule import DoseSchedule, derive_schedule, from_snapshot, to_snapshot


def hospital_date(moment: datetime) -> date:
    """The hospital's calendar day at `moment` — approving at 1 AM in Delhi
    starts the course that day, not on the UTC day before."""
    return moment.astimezone(ZoneInfo(get_settings().hospital_timezone)).date()


def snapshot_at_approval(instruction: CareInstruction) -> dict | None:
    version = instruction.current_version
    extraction = version.extraction if version else None
    if extraction is None or extraction.instruction_type != InstructionType.MEDICATION or instruction.approved_at is None:
        return None
    schedule = derive_schedule(extraction.normalized_facts, version.raw_text)
    return to_snapshot(schedule, hospital_date(instruction.approved_at))


def approved_schedule(instruction: CareInstruction) -> tuple[DoseSchedule, date | None] | None:
    if instruction.dose_schedule:
        return from_snapshot(instruction.dose_schedule)
    version = instruction.current_version
    extraction = version.extraction if version else None
    if extraction is None or extraction.instruction_type != InstructionType.MEDICATION:
        return None
    start = instruction.clinical_start_date or (hospital_date(instruction.approved_at) if instruction.approved_at else None)
    return derive_schedule(extraction.normalized_facts, version.raw_text), start
