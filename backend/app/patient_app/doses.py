"""Which doses are due on a given day, and what the patient said about them.

Built from the same approved medication facts and dose schedules the
patient app shows (app/schedules/), never from anything typed separately.
"""

import uuid
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.instructions.models import CareInstruction, ClinicalStatus, InstructionStatus, InstructionType
from app.patient_app.models import DoseLog
from app.schedules.dose_schedule import format_time
from app.schedules.instruction_schedule import approved_schedule


@dataclass(frozen=True)
class DueDose:
    instruction_id: uuid.UUID
    medication_name: str
    dose: str | None
    with_food: bool | None
    time: str  # "08:00"
    time_display: str  # "8:00 AM"
    status: str | None = None  # TAKEN / SKIPPED / None (no answer yet)
    recorded_at: datetime | None = None


def hospital_now() -> datetime:
    return datetime.now(ZoneInfo(get_settings().hospital_timezone))


def _medications(db: Session, patient_id: uuid.UUID) -> list[CareInstruction]:
    rows = (
        db.query(CareInstruction)
        .filter(CareInstruction.patient_id == patient_id, CareInstruction.status == InstructionStatus.APPROVED)
        .all()
    )
    result = []
    for instruction in rows:
        version = instruction.current_version
        extraction = version.extraction if version else None
        if extraction is not None and extraction.instruction_type == InstructionType.MEDICATION:
            result.append(instruction)
    return result


def scheduled_doses(db: Session, patient_id: uuid.UUID, day: date, today: date) -> list[DueDose]:
    """Doses due on `day`, earliest first. A medicine counts only between its
    start (approval day) and end (course length), and never once it is
    stopped or completed: for today and later, any stop removes it at once;
    for a past day, it counts only before the day it was stopped."""
    doses: list[DueDose] = []
    for instruction in _medications(db, patient_id):
        facts = instruction.current_version.extraction.normalized_facts
        found = approved_schedule(instruction)
        if found is None:
            continue
        schedule, start = found
        if schedule.kind != "SCHEDULED":
            continue
        if start is None or day < start:
            continue
        end = schedule.end_date(start)
        if end is not None and day > end:
            continue
        if instruction.clinical_status in (ClinicalStatus.COMPLETED, ClinicalStatus.STOPPED):
            stopped_on = instruction.clinical_end_date
            if day >= today or stopped_on is None or day >= stopped_on:
                continue
        for slot in schedule.times:
            doses.append(
                DueDose(
                    instruction_id=instruction.id,
                    medication_name=facts.get("medication_name") or "Medicine",
                    dose=schedule.dose,
                    with_food=schedule.with_food,
                    time=slot.strftime("%H:%M"),
                    time_display=format_time(slot),
                )
            )
    doses.sort(key=lambda d: (d.time, d.medication_name.lower()))
    return doses


def doses_with_status(db: Session, patient_id: uuid.UUID, day: date, today: date) -> list[DueDose]:
    logs = {
        (log.instruction_id, log.dose_time): log
        for log in db.query(DoseLog).filter(DoseLog.patient_id == patient_id, DoseLog.dose_date == day).all()
    }
    result = []
    for dose in scheduled_doses(db, patient_id, day, today):
        log = logs.get((dose.instruction_id, dose.time))
        result.append(
            DueDose(**{**dose.__dict__, "status": log.status if log else None, "recorded_at": log.recorded_at if log else None})
        )
    return result


class DoseNotDueError(Exception):
    pass


def record_dose(
    db: Session, patient_id: uuid.UUID, instruction_id: uuid.UUID, day: date, slot: str, status: str | None
) -> None:
    """Taken / Skipped, or None to undo. Only today's and yesterday's doses,
    and only a dose that really is on the schedule."""
    today = hospital_now().date()
    if day not in (today, today - timedelta(days=1)):
        raise DoseNotDueError()
    if not any(d.instruction_id == instruction_id and d.time == slot for d in scheduled_doses(db, patient_id, day, today)):
        raise DoseNotDueError()
    slot_filter = (DoseLog.instruction_id == instruction_id, DoseLog.dose_date == day, DoseLog.dose_time == slot)
    if status is None:
        db.query(DoseLog).filter(*slot_filter).delete()
    else:
        # One statement, so a double tap or a retried request on a weak signal
        # updates the answer instead of failing on the one-per-dose rule.
        statement = pg_insert(DoseLog).values(
            id=uuid.uuid4(),
            patient_id=patient_id,
            instruction_id=instruction_id,
            dose_date=day,
            dose_time=slot,
            status=status,
            recorded_at=datetime.now(timezone.utc),
        )
        db.execute(
            statement.on_conflict_do_update(
                constraint="uq_dose_log_slot",
                set_={"status": statement.excluded.status, "recorded_at": statement.excluded.recorded_at},
            )
        )
    db.commit()


@dataclass(frozen=True)
class AdherenceDay:
    day: date
    due: int
    taken: int
    skipped: int


def adherence(db: Session, patient_id: uuid.UUID, days: int) -> list[AdherenceDay]:
    """Per day, oldest first: doses due, taken, skipped (the rest: no answer)."""
    now = hospital_now()
    today = now.date()
    first = today - timedelta(days=days - 1)
    logs = db.query(DoseLog).filter(DoseLog.patient_id == patient_id, DoseLog.dose_date >= first).all()
    result = []
    for offset in range(days):
        day = first + timedelta(days=offset)
        # Today, only doses whose time has come: a 8 PM dose is not "no
        # answer" at noon.
        due = {
            (d.instruction_id, d.time)
            for d in scheduled_doses(db, patient_id, day, today)
            if day < today or slot_time(d.time) <= now.time()
        }
        day_logs = [log for log in logs if log.dose_date == day and (log.instruction_id, log.dose_time) in due]
        result.append(
            AdherenceDay(
                day=day,
                due=len(due),
                taken=sum(1 for log in day_logs if log.status == "TAKEN"),
                skipped=sum(1 for log in day_logs if log.status == "SKIPPED"),
            )
        )
    return result


def slot_time(value: str) -> time:
    hour, minute = value.split(":")
    return time(int(hour), int(minute))


# A dose counts as missed only this long after its time: nobody is flagged at
# 8:01 for an 8:00 dose.
MISSED_GRACE = timedelta(hours=2)
# Two missed doses in a day is worth a call from the care team.
MISSED_FLAG_THRESHOLD = 2


@dataclass(frozen=True)
class MissedDoses:
    patient_id: uuid.UUID
    day: date
    missed: int  # skipped + no answer
    skipped: int


def missed_doses_flags(db: Session) -> list[MissedDoses]:
    """Patients at home using the app who missed 2+ doses today (counting
    only doses more than 2 hours past) or yesterday. Patient-reported: a
    prompt for a phone call, not a clinical record."""
    from app.patient_app.models import STATUS_ACTIVE, PatientAppAccount
    from app.patients.models import AdmissionStatus, Patient

    now = hospital_now()
    today = now.date()
    patient_ids = [
        pid
        for (pid,) in db.query(Patient.id)
        .join(PatientAppAccount, PatientAppAccount.patient_id == Patient.id)
        .filter(PatientAppAccount.status == STATUS_ACTIVE, Patient.admission_status == AdmissionStatus.DISCHARGED)
        .all()
    ]
    flags = []
    for patient_id in patient_ids:
        for day in (today, today - timedelta(days=1)):
            doses = [
                d
                for d in doses_with_status(db, patient_id, day, today)
                if day < today or datetime.combine(day, slot_time(d.time), now.tzinfo) + MISSED_GRACE <= now
            ]
            skipped = sum(1 for d in doses if d.status == "SKIPPED")
            missed = skipped + sum(1 for d in doses if d.status is None)
            if missed >= MISSED_FLAG_THRESHOLD:
                flags.append(MissedDoses(patient_id=patient_id, day=day, missed=missed, skipped=skipped))
                break  # today's flag first; one per patient
    return flags
