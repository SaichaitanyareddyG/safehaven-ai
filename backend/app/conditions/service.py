import uuid

from sqlalchemy.orm import Session

from app.audit.models import ActorType, AuditEventType
from app.audit.service import record_event
from app.conditions.models import PatientCondition
from app.conditions.schemas import PatientConditionCreate
from app.patients.service import get_patient


class ConditionNotFoundError(Exception):
    pass


def create_condition(
    db: Session, patient_id: uuid.UUID, data: PatientConditionCreate, documented_by: uuid.UUID
) -> PatientCondition:
    get_patient(db, patient_id)  # raises PatientNotFoundError if missing

    condition = PatientCondition(
        patient_id=patient_id,
        encounter_id=data.encounter_id,
        condition_name=data.condition_name.strip(),
        documented_by=documented_by,
    )
    db.add(condition)
    db.flush()  # assigns condition.id, needed as the audit event's entity_id below

    # Deliberately no condition_name in metadata — diagnosis text is
    # sensitive; the audit trail records THAT a condition was documented, not
    # WHAT it was, matching the same redaction rule as every other audit
    # event (see audit/service.py's record_event docstring).
    record_event(
        db,
        event_type=AuditEventType.PATIENT_CONDITION_ADDED,
        actor_type=ActorType.CLINICIAN,
        actor_id=documented_by,
        patient_id=patient_id,
        entity_type="PatientCondition",
        entity_id=condition.id,
    )

    db.commit()
    db.refresh(condition)
    return condition


def list_conditions(db: Session, patient_id: uuid.UUID) -> list[PatientCondition]:
    get_patient(db, patient_id)  # raises PatientNotFoundError if missing
    return (
        db.query(PatientCondition)
        .filter(PatientCondition.patient_id == patient_id)
        .order_by(PatientCondition.documented_at.desc())
        .all()
    )


def delete_condition(db: Session, patient_id: uuid.UUID, condition_id: uuid.UUID, removed_by: uuid.UUID) -> None:
    condition = (
        db.query(PatientCondition)
        .filter(PatientCondition.id == condition_id, PatientCondition.patient_id == patient_id)
        .first()
    )
    if condition is None:
        raise ConditionNotFoundError(str(condition_id))

    record_event(
        db,
        event_type=AuditEventType.PATIENT_CONDITION_REMOVED,
        actor_type=ActorType.CLINICIAN,
        actor_id=removed_by,
        patient_id=patient_id,
        entity_type="PatientCondition",
        entity_id=condition.id,
    )
    db.delete(condition)
    db.commit()
