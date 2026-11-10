"""The patient's reminder calendar: a private iCalendar feed their phone
subscribes to once and refreshes by itself.

Free on every phone, works offline, and follows changes: when a medicine is
stopped or its times change, the next refresh replaces the events (stable
UIDs), usually within a few hours. Built from the same approved dose
schedules as the app (app/schedules/), never from anything typed separately.

What leaves the hospital is generic on purpose (user decision 2026-11-09):
"Time for your medicines — open SafeHaven", never a medicine name. Calendar
providers (Apple, Google) store these events.

Medicine reminders only while the patient is at home: in hospital the nurse
gives the doses. Appointments always.
"""

import hashlib
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.appointments.models import STATUS_SCHEDULED, Appointment
from app.core.config import get_settings
from app.instructions.models import ClinicalStatus
from app.patient_app.doses import _medications
from app.patient_app.models import STATUS_ACTIVE, PatientAppAccount
from app.patients.models import AdmissionStatus, Patient
from app.schedules.instruction_schedule import approved_schedule

MEDICINE_TITLE = "Time for your medicines"
APPOINTMENT_TITLE = "Hospital appointment"


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def _fold(line: str) -> list[str]:
    """RFC 5545: lines over 75 octets continue on the next line after a space."""
    out, raw = [], line.encode("utf-8")
    while len(raw) > 75:
        cut = 75 if not out else 74
        while cut > 0 and (raw[cut] & 0xC0) == 0x80:  # never split a UTF-8 character
            cut -= 1
        out.append(raw[:cut].decode("utf-8"))
        raw = raw[cut:]
    out.append(raw.decode("utf-8"))
    return [out[0]] + [" " + part for part in out[1:]]


def _utc(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _uid(*parts: object) -> str:
    return hashlib.sha256("|".join(str(p) for p in parts).encode()).hexdigest()[:32] + "@safehaven"


def medicine_slots(db: Session, patient: Patient, today: date) -> list[tuple[time, date, date | None]]:
    """(time of day, first day, last day or None) for each daily reminder.
    The text is the same for every medicine, so medicines due at the same
    time share one reminder over the days any of them is due: overlapping
    courses merge, a gap between courses stays a gap."""
    if patient.admission_status != AdmissionStatus.DISCHARGED:
        return []
    slots: set[tuple[time, date, date | None]] = set()
    for instruction in _medications(db, patient.id):
        if instruction.clinical_status in (ClinicalStatus.COMPLETED, ClinicalStatus.STOPPED):
            continue
        found = approved_schedule(instruction)
        if found is None:
            continue
        schedule, start = found
        if schedule.kind != "SCHEDULED" or start is None:
            continue
        end = schedule.end_date(start)
        if end is not None and end < today:
            continue
        # Never earlier than today: no reminders back in time.
        first = max(start, today)
        for slot in schedule.times:
            slots.add((slot, first, end))

    merged: list[tuple[time, date, date | None]] = []
    for slot, first, last in sorted(slots, key=lambda s: (s[0], s[1], s[2] or date.max)):
        if merged and merged[-1][0] == slot:
            prev_first, prev_last = merged[-1][1], merged[-1][2]
            # Touching or overlapping (prev_last None = ongoing): one reminder.
            if prev_last is None or first <= prev_last + timedelta(days=1):
                longest = None if prev_last is None or last is None else max(prev_last, last)
                merged[-1] = (slot, prev_first, longest)
                continue
        merged.append((slot, first, last))
    return merged


def build_feed(db: Session, account: PatientAppAccount, app_url: str) -> str:
    settings = get_settings()
    zone = ZoneInfo(settings.hospital_timezone)
    now = datetime.now(timezone.utc)
    today = now.astimezone(zone).date()
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//SafeHaven//Patient reminders//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "X-WR-CALNAME:SafeHaven reminders",
        f"X-WR-TIMEZONE:{settings.hospital_timezone}",
        # Ask subscribing apps to refresh hourly (each app decides in the end).
        "REFRESH-INTERVAL;VALUE=DURATION:PT1H",
        "X-PUBLISHED-TTL:PT1H",
    ]
    patient = db.get(Patient, account.patient_id)
    usable = (
        patient is not None
        and account.status == STATUS_ACTIVE
        and (account.access_expires_at is None or account.access_expires_at > now)
    )
    if usable:
        description = _escape(f"Open SafeHaven to see which: {app_url}")
        for slot, first, last in medicine_slots(db, patient, today):
            start = datetime.combine(first, slot, tzinfo=zone)
            rule = "RRULE:FREQ=DAILY"
            if last is not None:
                rule += ";UNTIL=" + _utc(datetime.combine(last, time(23, 59, 59), tzinfo=zone))
            lines += [
                "BEGIN:VEVENT",
                f"UID:{_uid(account.id, 'dose', slot, first, last)}",
                f"DTSTAMP:{_utc(now)}",
                f"DTSTART;TZID={settings.hospital_timezone}:{start.strftime('%Y%m%dT%H%M%S')}",
                "DURATION:PT15M",
                rule,
                f"SUMMARY:{MEDICINE_TITLE}",
                f"DESCRIPTION:{description}",
                f"URL:{app_url}",
                "TRANSP:TRANSPARENT",
                "BEGIN:VALARM",
                "ACTION:DISPLAY",
                f"DESCRIPTION:{MEDICINE_TITLE}",
                "TRIGGER:PT0M",
                "END:VALARM",
                "END:VEVENT",
            ]
        appointments = (
            db.query(Appointment)
            .filter(
                Appointment.patient_id == patient.id,
                Appointment.starts_at >= now - timedelta(days=1),
                Appointment.status == STATUS_SCHEDULED,
            )
            .order_by(Appointment.starts_at)
            .all()
        )
        for appt in appointments:
            evening_before = datetime.combine(appt.starts_at.astimezone(zone).date() - timedelta(days=1), time(18, 0), tzinfo=zone)
            lines += [
                "BEGIN:VEVENT",
                f"UID:{_uid(account.id, 'appointment', appt.id)}",
                f"DTSTAMP:{_utc(now)}",
                f"DTSTART:{_utc(appt.starts_at)}",
                "DURATION:PT1H",
                f"SUMMARY:{APPOINTMENT_TITLE}",
                f"DESCRIPTION:{_escape(f'Open SafeHaven for the details: {app_url}')}",
                f"URL:{app_url}",
                # The evening before at 6 PM and 2 hours before, as the app's own reminders.
                "BEGIN:VALARM",
                "ACTION:DISPLAY",
                f"DESCRIPTION:{APPOINTMENT_TITLE} tomorrow",
                f"TRIGGER;VALUE=DATE-TIME:{_utc(evening_before)}",
                "END:VALARM",
                "BEGIN:VALARM",
                "ACTION:DISPLAY",
                f"DESCRIPTION:{APPOINTMENT_TITLE} in 2 hours",
                "TRIGGER:-PT2H",
                "END:VALARM",
                "END:VEVENT",
            ]
    lines.append("END:VCALENDAR")
    return "\r\n".join(folded for line in lines for folded in _fold(line)) + "\r\n"
