import uuid

from sqlalchemy.orm import Session

from app.audit.models import ActorType, AuditEventType
from app.audit.service import record_event
from app.instructions.models import CareInstruction, InstructionStatus
from app.patient_access.service import validate_care_access_token
from app.patient_feedback.models import ComprehensionResponse, PatientComprehensionFeedback


class InstructionNotFoundForPatientError(Exception):
    """Raised when the given instruction doesn't belong to this patient (or
    isn't approved) — never leaks whether the instruction exists at all for
    a different patient, same generic-failure principle as
    InvalidCareAccessTokenError."""


def record_feedback_by_token(
    db: Session, raw_token: str, instruction_id: uuid.UUID, response: ComprehensionResponse
) -> PatientComprehensionFeedback:
    record = validate_care_access_token(db, raw_token)
    return record_feedback(db, record.patient_id, instruction_id, response)


def record_feedback(
    db: Session, patient_id: uuid.UUID, instruction_id: uuid.UUID, response: ComprehensionResponse
) -> PatientComprehensionFeedback:
    instruction = (
        db.query(CareInstruction)
        .filter(
            CareInstruction.id == instruction_id,
            CareInstruction.patient_id == patient_id,
            CareInstruction.status == InstructionStatus.APPROVED,
        )
        .first()
    )
    if instruction is None:
        raise InstructionNotFoundForPatientError(str(instruction_id))

    feedback = PatientComprehensionFeedback(patient_id=patient_id, care_instruction_id=instruction_id, response=response)
    db.add(feedback)
    db.flush()

    if response != ComprehensionResponse.UNDERSTOOD:
        record_event(
            db,
            event_type=AuditEventType.PATIENT_COMPREHENSION_NEEDS_ATTENTION,
            actor_type=ActorType.PATIENT,
            patient_id=patient_id,
            entity_type="CareInstruction",
            entity_id=instruction_id,
            event_metadata={"response": response.value},
        )

    db.commit()
    db.refresh(feedback)
    return feedback
