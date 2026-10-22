import uuid

from sqlalchemy.orm import Session

from app.appointments.models import STATUS_CANCELLED, STATUS_SCHEDULED, Appointment, AppointmentReminderSent
from app.appointments.schemas import AppointmentCreate, AppointmentUpdate
from app.audit.models import ActorType, AuditEventType
from app.audit.service import record_event
from app.patients.service import get_patient


class AppointmentNotFoundError(Exception):
    pass


def create_appointment(db: Session, patient_id: uuid.UUID, data: AppointmentCreate, created_by: uuid.UUID) -> Appointment:
    get_patient(db, patient_id)  # raises PatientNotFoundError
    appointment = Appointment(
        patient_id=patient_id,
        title=data.title,
        starts_at=data.starts_at,
        location=data.location,
        notes=data.notes,
        created_by=created_by,
    )
    db.add(appointment)
    db.flush()
    record_event(
        db,
        event_type=AuditEventType.APPOINTMENT_CREATED,
        actor_type=ActorType.CLINICIAN,
        actor_id=created_by,
        patient_id=patient_id,
        entity_type="Appointment",
        entity_id=appointment.id,
    )
    db.commit()
    db.refresh(appointment)
    return appointment


def list_appointments(db: Session, patient_id: uuid.UUID, include_cancelled: bool = True) -> list[Appointment]:
    get_patient(db, patient_id)
    query = db.query(Appointment).filter(Appointment.patient_id == patient_id)
    if not include_cancelled:
        query = query.filter(Appointment.status == STATUS_SCHEDULED)
    return query.order_by(Appointment.starts_at.asc()).all()


def update_appointment(db: Session, appointment_id: uuid.UUID, data: AppointmentUpdate, updated_by: uuid.UUID) -> Appointment:
    appointment = db.get(Appointment, appointment_id)
    if appointment is None:
        raise AppointmentNotFoundError(str(appointment_id))
    changes = data.model_dump(exclude_unset=True)
    moved = "starts_at" in changes and changes["starts_at"] != appointment.starts_at
    for field, value in changes.items():
        if field == "title" and value is not None:
            value = value.strip()
        setattr(appointment, field, value)
    if moved:
        # A new time gets its own reminders.
        db.query(AppointmentReminderSent).filter(AppointmentReminderSent.appointment_id == appointment.id).delete()
    cancelled = changes.get("status") == STATUS_CANCELLED
    record_event(
        db,
        event_type=AuditEventType.APPOINTMENT_CANCELLED if cancelled else AuditEventType.APPOINTMENT_UPDATED,
        actor_type=ActorType.CLINICIAN,
        actor_id=updated_by,
        patient_id=appointment.patient_id,
        entity_type="Appointment",
        entity_id=appointment.id,
        # Field names only, like PATIENT_UPDATED.
        event_metadata={} if cancelled else {"fields_updated": sorted(changes)},
    )
    db.commit()
    db.refresh(appointment)
    return appointment
