import uuid

from sqlalchemy.orm import Session

from app.allergies.models import PatientAllergy
from app.allergies.schemas import PatientAllergyCreate
from app.audit.models import ActorType, AuditEventType
from app.audit.service import record_event
from app.patients.service import get_patient


class AllergyNotFoundError(Exception):
    pass


def create_allergy(
    db: Session, patient_id: uuid.UUID, data: PatientAllergyCreate, documented_by: uuid.UUID
) -> PatientAllergy:
    get_patient(db, patient_id)  # raises PatientNotFoundError if missing

    allergy = PatientAllergy(
        patient_id=patient_id,
        allergen=data.allergen.strip(),
        reaction=data.reaction.strip() if data.reaction else None,
        severity=data.severity.strip() if data.severity else None,
        documented_by=documented_by,
    )
    db.add(allergy)
    db.flush()  # assigns allergy.id, needed as the audit event's entity_id below

    # Deliberately no allergen in metadata — same redaction rule as every
    # other audit event involving clinical content (see PatientCondition's
    # create_condition and audit/service.py's record_event docstring).
    record_event(
        db,
        event_type=AuditEventType.PATIENT_ALLERGY_ADDED,
        actor_type=ActorType.CLINICIAN,
        actor_id=documented_by,
        patient_id=patient_id,
        entity_type="PatientAllergy",
        entity_id=allergy.id,
    )

    db.commit()
    db.refresh(allergy)
    return allergy


def list_allergies(db: Session, patient_id: uuid.UUID) -> list[PatientAllergy]:
    get_patient(db, patient_id)  # raises PatientNotFoundError if missing
    return (
        db.query(PatientAllergy)
        .filter(PatientAllergy.patient_id == patient_id)
        .order_by(PatientAllergy.documented_at.desc())
        .all()
    )


def delete_allergy(db: Session, patient_id: uuid.UUID, allergy_id: uuid.UUID, removed_by: uuid.UUID) -> None:
    allergy = (
        db.query(PatientAllergy)
        .filter(PatientAllergy.id == allergy_id, PatientAllergy.patient_id == patient_id)
        .first()
    )
    if allergy is None:
        raise AllergyNotFoundError(str(allergy_id))

    record_event(
        db,
        event_type=AuditEventType.PATIENT_ALLERGY_REMOVED,
        actor_type=ActorType.CLINICIAN,
        actor_id=removed_by,
        patient_id=patient_id,
        entity_type="PatientAllergy",
        entity_id=allergy.id,
    )
    db.delete(allergy)
    db.commit()
