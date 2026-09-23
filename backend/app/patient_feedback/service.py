import re
import uuid

from sqlalchemy.orm import Session

from app.audit.models import ActorType, AuditEventType
from app.audit.service import record_event
from app.instructions.models import CareInstruction, InstructionStatus, StructuredExtraction
from app.patient_access.schemas import WhyTier
from app.patient_access.service import resolve_why, validate_care_access_token
from app.patient_feedback.models import ComprehensionResponse, PatientComprehensionFeedback, PatientTeachBackResponse

_WORD_RE = re.compile(r"[a-zA-Z]+")


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


def _words(text: str | None) -> set[str]:
    return {w.lower() for w in _WORD_RE.findall(text or "") if len(w) >= 3}


def _check_teach_back(response_text: str, extraction: StructuredExtraction) -> tuple[bool, list[str], list[str]]:
    """Deterministic, prototype-scale word-overlap check of the patient's own
    explanation against the order's structured facts — never a claim of true
    language understanding, the same honesty this codebase already applies
    to formulation/dose matching elsewhere (see
    medication_verification/service.py's prototype-configuration comments).

    Only checks facts that are actually documented on the order — an
    undocumented reason is never required to be mentioned (same rule
    resolve_why already enforces: only a Tier 1/DOCUMENTED reason counts,
    never Tier 2/GENERAL, and never inferred from a condition). An
    instruction type/order with nothing checkable (e.g. no medication_name,
    no timing, no documented reason) vacuously passes — there is nothing to
    contradict."""
    facts = extraction.normalized_facts
    response_words = _words(response_text)
    response_lower = response_text.lower()

    confirmed: list[str] = []
    missing: list[str] = []

    medication_name = facts.get("medication_name")
    if medication_name:
        base_drug = str(medication_name).split()[0].lower()
        (confirmed if base_drug in response_lower else missing).append("medication_name")

    timing_words = _words(f"{facts.get('frequency') or ''} {facts.get('timing') or ''}")
    if timing_words:
        (confirmed if timing_words & response_words else missing).append("timing")

    why = resolve_why(extraction)
    if why is not None and why.tier == WhyTier.DOCUMENTED:
        reason_words = _words(why.text)
        if reason_words:
            (confirmed if reason_words & response_words else missing).append("reason")

    return (len(missing) == 0, confirmed, missing)


def record_teach_back_by_token(
    db: Session, raw_token: str, instruction_id: uuid.UUID, response_text: str
) -> PatientTeachBackResponse:
    record = validate_care_access_token(db, raw_token)
    return record_teach_back(db, record.patient_id, instruction_id, response_text)


def record_teach_back(
    db: Session, patient_id: uuid.UUID, instruction_id: uuid.UUID, response_text: str
) -> PatientTeachBackResponse:
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

    extraction = instruction.current_version.extraction if instruction.current_version else None
    if extraction is None:
        passed, confirmed, missing = True, [], []
    else:
        passed, confirmed, missing = _check_teach_back(response_text, extraction)

    record = PatientTeachBackResponse(
        patient_id=patient_id,
        care_instruction_id=instruction_id,
        response_text=response_text.strip(),
        passed=passed,
        confirmed_facts=confirmed,
        missing_facts=missing,
    )
    db.add(record)
    db.flush()

    if not passed:
        # Same pattern as HAS_QUESTION/ASK_CARE_TEAM above — never blocks the
        # patient from anything, only flags the clinician's Activity
        # Timeline. Deliberately no response_text in metadata: free-text
        # patient input may contain PHI, same redaction rule as every other
        # audit event (see audit/service.py's record_event docstring).
        record_event(
            db,
            event_type=AuditEventType.PATIENT_TEACH_BACK_NEEDS_ATTENTION,
            actor_type=ActorType.PATIENT,
            patient_id=patient_id,
            entity_type="CareInstruction",
            entity_id=instruction_id,
            event_metadata={"missing_facts": missing},
        )

    db.commit()
    db.refresh(record)
    return record
