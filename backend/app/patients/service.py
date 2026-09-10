import uuid

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.audit.models import ActorType, AuditEventType
from app.audit.service import record_event
from app.patients.models import AdmissionStatus, Patient
from app.patients.schemas import PatientCreate, PatientUpdate


class PatientNotFoundError(Exception):
    pass


def create_patient(db: Session, data: PatientCreate, created_by: uuid.UUID) -> Patient:
    patient = Patient(
        first_name=data.first_name,
        last_name=data.last_name,
        date_of_birth=data.date_of_birth,
        room_number=data.room_number,
        preferred_language=data.preferred_language,
        created_by=created_by,
    )
    db.add(patient)
    db.flush()  # assigns patient.id, needed as the audit event's patient_id below

    record_event(
        db,
        event_type=AuditEventType.PATIENT_CREATED,
        actor_type=ActorType.CLINICIAN,
        actor_id=created_by,
        patient_id=patient.id,
        entity_type="Patient",
        entity_id=patient.id,
        event_metadata={"preferred_language": data.preferred_language.value},
    )
    db.commit()
    db.refresh(patient)
    return patient


def get_patient(db: Session, patient_id: uuid.UUID) -> Patient:
    patient = db.get(Patient, patient_id)
    if patient is None:
        raise PatientNotFoundError(str(patient_id))
    return patient


def get_patient_by_code(db: Session, patient_code: str) -> Patient:
    """Exact-match lookup for a scanned wristband code (e.g. "P1001") — used
    by Module 2's patient-scan step. Deliberately separate from the fuzzy
    `search` filter on list_patients(), which is a paginated substring match
    meant for a clinician typing into a search box, not a single scan
    result."""
    patient = db.query(Patient).filter(Patient.patient_code == patient_code).first()
    if patient is None:
        raise PatientNotFoundError(patient_code)
    return patient


def list_patients(
    db: Session,
    status: AdmissionStatus | None,
    search: str | None,
    limit: int,
    offset: int,
) -> tuple[int, list[Patient]]:
    query = db.query(Patient)

    if status is not None:
        query = query.filter(Patient.admission_status == status)

    if search:
        pattern = f"%{search}%"
        query = query.filter(
            or_(
                Patient.patient_code.ilike(pattern),
                Patient.first_name.ilike(pattern),
                Patient.last_name.ilike(pattern),
            )
        )

    total = query.with_entities(func.count(Patient.id)).scalar() or 0
    results = query.order_by(Patient.created_at.desc()).limit(limit).offset(offset).all()
    return total, results


def update_patient(
    db: Session, patient_id: uuid.UUID, data: PatientUpdate, updated_by: uuid.UUID, commit: bool = True
) -> Patient:
    """commit=False lets an orchestration layer (see app/orchestration/) fold
    this into a larger single transaction — e.g. discharge, which must also
    revoke care-access tokens atomically. Every other caller keeps the
    default, unchanged auto-commit behavior."""
    patient = get_patient(db, patient_id)
    was_active = patient.admission_status == AdmissionStatus.ACTIVE
    changed_fields = list(data.model_dump(exclude_unset=True).keys())
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(patient, field, value)

    # Discharge gets its own, more specific event rather than a generic
    # PATIENT_UPDATED — it's the one field change with a real safety
    # consequence (see patients/router.py, which revokes care-access tokens
    # when it sees this transition).
    if was_active and patient.admission_status == AdmissionStatus.DISCHARGED:
        record_event(
            db,
            event_type=AuditEventType.PATIENT_DISCHARGED,
            actor_type=ActorType.CLINICIAN,
            actor_id=updated_by,
            patient_id=patient.id,
            entity_type="Patient",
            entity_id=patient.id,
        )
    elif changed_fields:
        # Field names only — values (name, DOB, room) may be sensitive and add
        # no forensic value beyond "this patient's record was edited".
        record_event(
            db,
            event_type=AuditEventType.PATIENT_UPDATED,
            actor_type=ActorType.CLINICIAN,
            actor_id=updated_by,
            patient_id=patient.id,
            entity_type="Patient",
            entity_id=patient.id,
            event_metadata={"fields_updated": changed_fields},
        )

    if commit:
        db.commit()
        db.refresh(patient)
    else:
        db.flush()
    return patient
