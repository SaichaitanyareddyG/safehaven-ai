import uuid

from sqlalchemy.orm import Session

from app.audit.models import ActorType, AuditEventType
from app.audit.service import record_event
from app.encounters.models import Encounter
from app.encounters.schemas import EncounterCreate
from app.patients.service import get_patient


def create_encounter(db: Session, patient_id: uuid.UUID, data: EncounterCreate, created_by: uuid.UUID) -> Encounter:
    get_patient(db, patient_id)  # raises PatientNotFoundError if missing

    encounter = Encounter(
        patient_id=patient_id,
        encounter_type=data.encounter_type,
        reason_for_visit=data.reason_for_visit,
        admission_date=data.admission_date,
        discharge_date=data.discharge_date,
        status=data.status,
        created_by=created_by,
    )
    db.add(encounter)
    db.flush()  # assigns encounter.id, needed as the audit event's entity_id below

    # Deliberately no reason_for_visit in metadata — same PHI-redaction rule
    # as every other audit event (e.g. PATIENT_CONDITION_ADDED never
    # includes condition_name).
    record_event(
        db,
        event_type=AuditEventType.ENCOUNTER_CREATED,
        actor_type=ActorType.CLINICIAN,
        actor_id=created_by,
        patient_id=patient_id,
        entity_type="Encounter",
        entity_id=encounter.id,
    )

    db.commit()
    db.refresh(encounter)
    return encounter


def list_encounters(db: Session, patient_id: uuid.UUID) -> list[Encounter]:
    get_patient(db, patient_id)  # raises PatientNotFoundError if missing
    return (
        db.query(Encounter)
        .filter(Encounter.patient_id == patient_id)
        .order_by(Encounter.admission_date.desc())
        .all()
    )
