"""Web Push: dose reminders to the patient's phone.

The notification says only that it is time for medicines — never which
medicines. It shows on a lock screen anyone nearby can read.
"""

import json
import logging
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.patient_app.doses import hospital_now, scheduled_doses, slot_time
from app.schedules.dose_schedule import POSSIBLE_DOSE_TIMES
from app.patient_app.models import (
    STATUS_ACTIVE,
    DoseLog,
    DoseReminderSent,
    PatientAppAccount,
    PushSubscription,
)
from app.patients.models import AdmissionStatus, Patient

logger = logging.getLogger(__name__)


def push_enabled() -> bool:
    settings = get_settings()
    return bool(settings.vapid_public_key and settings.vapid_private_key)


def send_to_subscription(db: Session, subscription: PushSubscription, payload: dict) -> bool:
    """True if the push service accepted it. A subscription the browser has
    dropped (404/410) is deleted, so it is never tried again."""
    from pywebpush import WebPushException, webpush

    settings = get_settings()
    try:
        webpush(
            subscription_info={
                "endpoint": subscription.endpoint,
                "keys": {"p256dh": subscription.p256dh, "auth": subscription.auth},
            },
            data=json.dumps(payload),
            vapid_private_key=settings.vapid_private_key,
            vapid_claims={"sub": settings.vapid_subject},
            ttl=60 * 60,
            timeout=10,
        )
    except WebPushException as exc:
        status = exc.response.status_code if exc.response is not None else None
        if status in (404, 410):
            db.delete(subscription)
        else:
            # Status only: the response body can echo the endpoint.
            logger.warning("Push not delivered: HTTP %s", status)
        return False
    except Exception as exc:  # network trouble: try again at the next dose
        logger.warning("Push not delivered: %s", type(exc).__name__)
        return False
    subscription.last_sent_at = datetime.now(timezone.utc)
    return True


def send_to_patient(db: Session, patient_id: uuid.UUID, payload: dict) -> int:
    subscriptions = db.query(PushSubscription).filter(PushSubscription.patient_id == patient_id).all()
    sent = sum(1 for s in subscriptions if send_to_subscription(db, s, payload))
    db.commit()
    return sent


def reminder_payload(time_display: str, count: int) -> dict:
    return {
        "title": f"Time for your {time_display} medicine{'s' if count > 1 else ''}",
        "body": "Open SafeHaven to see which, and mark them taken."
        if count > 1
        else "Open SafeHaven to see which, and mark it taken.",
        "url": "/my",
        "tag": f"dose-{time_display}",
    }


def run_reminders(db: Session, now: datetime | None = None) -> int:
    """Remind every patient at home whose dose time has come (within the
    window) and who has not answered it yet. Safe to run as often as wanted:
    each patient gets one reminder per dose time per day."""
    if not push_enabled():
        return 0
    now = now or hospital_now()
    today = now.date()
    window = timedelta(minutes=get_settings().reminder_window_minutes)
    # Most minutes are nowhere near a dose time: skip the database entirely.
    minutes_now = now.hour * 60 + now.minute
    if not any(0 <= minutes_now - (t.hour * 60 + t.minute) < window.total_seconds() / 60 for t in POSSIBLE_DOSE_TIMES):
        return 0

    patient_ids = [
        pid
        for (pid,) in db.query(PatientAppAccount.patient_id)
        .join(Patient, Patient.id == PatientAppAccount.patient_id)
        .join(PushSubscription, PushSubscription.patient_id == PatientAppAccount.patient_id)
        .filter(
            PatientAppAccount.status == STATUS_ACTIVE,
            # In hospital, nurses give the doses: no reminders.
            Patient.admission_status == AdmissionStatus.DISCHARGED,
        )
        .distinct()
        .all()
    ]
    sent = 0
    for patient_id in patient_ids:
        account = db.query(PatientAppAccount).filter(PatientAppAccount.patient_id == patient_id).first()
        if account.access_expires_at is not None and account.access_expires_at <= datetime.now(timezone.utc):
            continue
        answered = {
            (log.instruction_id, log.dose_time)
            for log in db.query(DoseLog).filter(DoseLog.patient_id == patient_id, DoseLog.dose_date == today)
        }
        by_time: dict[str, list] = {}
        for dose in scheduled_doses(db, patient_id, today, today):
            due_at = now.replace(hour=slot_time(dose.time).hour, minute=slot_time(dose.time).minute, second=0, microsecond=0)
            if due_at <= now < due_at + window and (dose.instruction_id, dose.time) not in answered:
                by_time.setdefault(dose.time, []).append(dose)
        for slot, doses in by_time.items():
            already = (
                db.query(DoseReminderSent.id)
                .filter(
                    DoseReminderSent.patient_id == patient_id,
                    DoseReminderSent.dose_date == today,
                    DoseReminderSent.dose_time == slot,
                )
                .first()
            )
            if already is not None:
                continue
            # Saved before sending: if two runs overlap, the unique constraint
            # stops the second, so a dose is never reminded twice.
            db.add(DoseReminderSent(patient_id=patient_id, dose_date=today, dose_time=slot))
            try:
                db.commit()
            except IntegrityError:
                db.rollback()
                continue
            if send_to_patient(db, patient_id, reminder_payload(doses[0].time_display, len(doses))):
                sent += 1
            else:
                # Nothing delivered (push service down, network): forget the
                # marker so the next run, still inside the window, tries again.
                db.query(DoseReminderSent).filter(
                    DoseReminderSent.patient_id == patient_id,
                    DoseReminderSent.dose_date == today,
                    DoseReminderSent.dose_time == slot,
                ).delete()
                db.commit()
    db.commit()
    return sent
