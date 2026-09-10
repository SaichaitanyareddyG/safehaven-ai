import uuid
from dataclasses import asdict
from datetime import datetime, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.ai.extraction_service import PROMPT_VERSION, ExtractionAttempt, run_extraction
from app.ai.generation_service import GENERATION_PROMPT_VERSION, GenerationAttempt, run_generation
from app.ai.provider import ExtractionProviderError, get_llm_provider
from app.ai.translation_service import TRANSLATION_PROMPT_VERSION, TranslationAttempt, run_translation
from app.audit.models import ActorType, AuditEventType
from app.audit.service import record_event
from app.instructions.models import (
    CareInstruction,
    ClinicalStatus,
    CompletenessStatus,
    InstructionStatus,
    InstructionType,
    InstructionVersion,
    PatientOutput,
    PatientOutputTranslation,
    StructuredExtraction,
    ValidationStatus,
    VersionSource,
)
from app.instructions.state import InvalidTransitionError, transition
from app.patients.models import AdmissionStatus, Language
from app.patients.service import get_patient
from app.validation.completeness import evaluate_completeness
from app.validation.fact_preservation import validate_fact_preservation
from app.validation.normalization import normalize_facts
from app.validation.translation_preservation import validate_translation_preservation


class InstructionNotFoundError(Exception):
    pass


class PatientNotActiveError(Exception):
    pass


class GenerationNotAllowedError(Exception):
    pass


class TranslationNotAllowedError(Exception):
    pass


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------


def get_instruction(db: Session, instruction_id: uuid.UUID) -> CareInstruction:
    instruction = db.get(CareInstruction, instruction_id)
    if instruction is None:
        raise InstructionNotFoundError(str(instruction_id))
    return instruction


def list_patient_instructions(
    db: Session,
    patient_id: uuid.UUID,
    status: InstructionStatus | None,
    limit: int,
    offset: int,
    clinical_status: ClinicalStatus | None = None,
) -> tuple[int, list[CareInstruction]]:
    get_patient(db, patient_id)  # raises PatientNotFoundError if missing

    query = db.query(CareInstruction).filter(CareInstruction.patient_id == patient_id)
    if status is not None:
        query = query.filter(CareInstruction.status == status)
    if clinical_status is not None:
        query = query.filter(CareInstruction.clinical_status == clinical_status)

    total = query.with_entities(func.count(CareInstruction.id)).scalar() or 0
    results = query.order_by(CareInstruction.created_at.desc()).limit(limit).offset(offset).all()
    return total, results


# ---------------------------------------------------------------------------
# Creation
# ---------------------------------------------------------------------------


def create_instruction(db: Session, patient_id: uuid.UUID, text: str, created_by: uuid.UUID) -> CareInstruction:
    patient = get_patient(db, patient_id)  # raises PatientNotFoundError if missing
    if patient.admission_status != AdmissionStatus.ACTIVE:
        raise PatientNotActiveError(str(patient_id))

    instruction = CareInstruction(patient_id=patient_id, created_by=created_by, status=InstructionStatus.DRAFT)
    db.add(instruction)
    db.flush()  # assigns instruction.id, needed as a FK target below

    version = InstructionVersion(
        care_instruction_id=instruction.id,
        version_number=1,
        raw_text=text,
        source=VersionSource.ORIGINAL,
        created_by=created_by,
    )
    db.add(version)
    db.flush()  # assigns version.id

    instruction.current_version_id = version.id

    record_event(
        db,
        event_type=AuditEventType.INSTRUCTION_CREATED,
        actor_type=ActorType.CLINICIAN,
        actor_id=created_by,
        patient_id=patient_id,
        entity_type="CareInstruction",
        entity_id=instruction.id,
    )

    db.commit()
    db.refresh(instruction)
    return instruction


def analyze_instruction(db: Session, instruction_id: uuid.UUID, actor_id: uuid.UUID) -> CareInstruction:
    """DRAFT -> PROCESSING, then runs AI extraction + validation against the
    current version's text. This is the sole entry point into analysis — the Step 4
    placeholder /submit (a blind status flip, no AI) is removed in favor of this."""
    instruction = (
        db.query(CareInstruction).filter(CareInstruction.id == instruction_id).with_for_update().first()
    )
    if instruction is None:
        raise InstructionNotFoundError(str(instruction_id))
    if instruction.status != InstructionStatus.DRAFT:
        raise InvalidTransitionError(instruction.status, InstructionStatus.PROCESSING)

    version = db.get(InstructionVersion, instruction.current_version_id)
    version_id = version.id
    text = version.raw_text

    transition(instruction, InstructionStatus.PROCESSING)
    record_event(
        db,
        event_type=AuditEventType.INSTRUCTION_ANALYSIS_STARTED,
        actor_type=ActorType.CLINICIAN,
        actor_id=actor_id,
        patient_id=instruction.patient_id,
        entity_type="CareInstruction",
        entity_id=instruction.id,
    )
    db.commit()  # transaction 1 ends here — `db` isn't touched again until after
    # the LLM call returns, so no transaction/connection is held during it.

    return _run_analysis_and_apply(db, instruction_id, version_id, text, actor_id)


def create_clarification(
    db: Session, instruction_id: uuid.UUID, text: str, created_by: uuid.UUID
) -> CareInstruction:
    """Creates an immutable new version from the clinician's clarification, then —
    per the chosen design — automatically re-runs analysis against it in the same
    business operation, so the clinician gets an updated status back in one call."""
    # Locks the row so two concurrent clarifications can't both compute the same
    # "next version number" — the second waits, then sees the first's committed row.
    instruction = (
        db.query(CareInstruction).filter(CareInstruction.id == instruction_id).with_for_update().first()
    )
    if instruction is None:
        raise InstructionNotFoundError(str(instruction_id))

    # Clarify is only meaningful from NEEDS_REVIEW. NEEDS_REVIEW -> PROCESSING is a
    # legal graph edge (see state.py), but so is DRAFT -> PROCESSING (analyze's own
    # edge) — the graph alone can't tell the two operations apart, so this endpoint
    # enforces its own, narrower precondition before deferring to the shared graph
    # check for the actual mutation.
    if instruction.status != InstructionStatus.NEEDS_REVIEW:
        raise InvalidTransitionError(instruction.status, InstructionStatus.PROCESSING)
    transition(instruction, InstructionStatus.PROCESSING)
    instruction.review_reason = None

    next_version_number = (
        db.query(func.max(InstructionVersion.version_number))
        .filter(InstructionVersion.care_instruction_id == instruction.id)
        .scalar()
        or 0
    ) + 1

    version = InstructionVersion(
        care_instruction_id=instruction.id,
        version_number=next_version_number,
        raw_text=text,
        source=VersionSource.CLARIFICATION,
        created_by=created_by,
    )
    db.add(version)
    db.flush()
    new_version_id = version.id  # captured before commit expires the attribute
    instruction.current_version_id = new_version_id

    record_event(
        db,
        event_type=AuditEventType.CLARIFICATION_CREATED,
        actor_type=ActorType.CLINICIAN,
        actor_id=created_by,
        patient_id=instruction.patient_id,
        entity_type="CareInstruction",
        entity_id=instruction.id,
        event_metadata={"version_number": next_version_number},
    )
    record_event(
        db,
        event_type=AuditEventType.INSTRUCTION_ANALYSIS_STARTED,
        actor_type=ActorType.CLINICIAN,
        actor_id=created_by,
        patient_id=instruction.patient_id,
        entity_type="CareInstruction",
        entity_id=instruction.id,
    )

    db.commit()  # transaction 1 ends here: new version + PROCESSING status
    # committed. `db` isn't touched again until after the LLM call returns.

    return _run_analysis_and_apply(db, instruction_id, new_version_id, text, created_by)


def _run_analysis_and_apply(
    db: Session, instruction_id: uuid.UUID, version_id: uuid.UUID, text: str, actor_id: uuid.UUID
) -> CareInstruction:
    """Shared by analyze_instruction and create_clarification: calls the LLM with
    no open transaction, then persists the result in a short follow-up
    transaction — see _apply_extraction_result for the stale-version guard.

    get_llm_provider() itself can fail (e.g. a missing API key) — that's just as
    much an extraction failure as a bad response, and must flow through the same
    NEEDS_REVIEW/FAILED path. Left uncaught, it would both 500 and strand the
    instruction in PROCESSING with no route back to DRAFT to retry."""
    try:
        provider = get_llm_provider()
        attempt = run_extraction(provider, text)
    except ExtractionProviderError as exc:
        attempt = ExtractionAttempt(
            succeeded=False, result=None, metadata=None, prompt_version=PROMPT_VERSION, failure_reason=str(exc)
        )
    return _apply_extraction_result(db, instruction_id, version_id, attempt, actor_id)


def _build_structured_extraction(version_id: uuid.UUID, attempt: ExtractionAttempt) -> StructuredExtraction:
    if not attempt.succeeded:
        return StructuredExtraction(
            instruction_version_id=version_id,
            instruction_type=None,
            extracted_facts={},
            normalized_facts={},
            missing_fields=[],
            ambiguous_fields=[],
            clarification_required_fields=[],
            validation_messages=[attempt.failure_reason or "AI extraction failed."],
            completeness_status=CompletenessStatus.FAILED,
            provider=attempt.metadata.provider if attempt.metadata else "unknown",
            model=attempt.metadata.model if attempt.metadata else "unknown",
            prompt_version=attempt.prompt_version,
            provider_request_id=attempt.metadata.request_id if attempt.metadata else None,
            latency_ms=attempt.metadata.latency_ms if attempt.metadata else None,
            token_usage=attempt.metadata.token_usage if attempt.metadata else None,
        )

    result = attempt.result
    extracted_facts = result.facts.model_dump()
    normalized_facts, _changes = normalize_facts(result.instruction_type, extracted_facts)
    completeness = evaluate_completeness(result.instruction_type, normalized_facts, result.ambiguities)

    return StructuredExtraction(
        instruction_version_id=version_id,
        instruction_type=result.instruction_type,
        extracted_facts=extracted_facts,
        normalized_facts=normalized_facts,
        missing_fields=completeness.missing_fields,
        ambiguous_fields=completeness.ambiguous_fields,
        clarification_required_fields=completeness.clarification_required_fields,
        validation_messages=completeness.validation_messages,
        completeness_status=completeness.completeness_status,
        provider=attempt.metadata.provider,
        model=attempt.metadata.model,
        prompt_version=attempt.prompt_version,
        provider_request_id=attempt.metadata.request_id,
        latency_ms=attempt.metadata.latency_ms,
        token_usage=attempt.metadata.token_usage,
    )


def _apply_extraction_result(
    db: Session,
    instruction_id: uuid.UUID,
    version_id_at_start: uuid.UUID,
    attempt: ExtractionAttempt,
    actor_id: uuid.UUID,
) -> CareInstruction:
    instruction = (
        db.query(CareInstruction).filter(CareInstruction.id == instruction_id).with_for_update().first()
    )
    if instruction is None:
        raise InstructionNotFoundError(str(instruction_id))

    # Stale-result protection: if a clarification created a newer version while
    # this analysis was in flight, current_version_id has moved on — this result no
    # longer applies to what the clinician is now looking at. Persist it for the
    # historical record, but never let it change current status.
    is_stale = instruction.current_version_id != version_id_at_start

    extraction = _build_structured_extraction(version_id_at_start, attempt)
    db.add(extraction)

    if is_stale:
        db.commit()
        db.refresh(instruction)
        return instruction

    if attempt.succeeded and extraction.completeness_status == CompletenessStatus.PASSED:
        # Stays PROCESSING — ready for Step 6 (patient-friendly generation).
        instruction.review_reason = None
        record_event(
            db,
            event_type=AuditEventType.INSTRUCTION_ANALYSIS_PASSED,
            actor_type=ActorType.CLINICIAN,
            actor_id=actor_id,
            patient_id=instruction.patient_id,
            entity_type="CareInstruction",
            entity_id=instruction.id,
        )
    elif attempt.succeeded:
        transition(instruction, InstructionStatus.NEEDS_REVIEW)
        instruction.review_reason = "; ".join(extraction.validation_messages) or "Clarification required."
        record_event(
            db,
            event_type=AuditEventType.INSTRUCTION_NEEDS_REVIEW,
            actor_type=ActorType.CLINICIAN,
            actor_id=actor_id,
            patient_id=instruction.patient_id,
            entity_type="CareInstruction",
            entity_id=instruction.id,
            event_metadata={
                "reason": "CLARIFICATION_REQUIRED",
                "missing_fields": extraction.missing_fields,
                "clarification_required_fields": extraction.clarification_required_fields,
            },
        )
    else:
        transition(instruction, InstructionStatus.NEEDS_REVIEW)
        instruction.review_reason = f"AI_EXTRACTION_FAILED: {attempt.failure_reason}"
        record_event(
            db,
            event_type=AuditEventType.INSTRUCTION_NEEDS_REVIEW,
            actor_type=ActorType.CLINICIAN,
            actor_id=actor_id,
            patient_id=instruction.patient_id,
            entity_type="CareInstruction",
            entity_id=instruction.id,
            event_metadata={"reason": "AI_EXTRACTION_FAILED"},
        )

    db.commit()
    db.refresh(instruction)
    return instruction


# ---------------------------------------------------------------------------
# Generation (Step 6): PROCESSING + PASSED extraction -> patient-friendly text
# -> fact-preservation validation -> READY_FOR_APPROVAL or back to NEEDS_REVIEW.
# Mirrors the analysis pipeline's shape: short transaction to gather what's
# needed, LLM calls with no transaction open, short transaction to persist.
# ---------------------------------------------------------------------------


def generate_patient_output(db: Session, instruction_id: uuid.UUID, actor_id: uuid.UUID) -> CareInstruction:
    instruction = (
        db.query(CareInstruction).filter(CareInstruction.id == instruction_id).with_for_update().first()
    )
    if instruction is None:
        raise InstructionNotFoundError(str(instruction_id))
    if instruction.status != InstructionStatus.PROCESSING:
        raise InvalidTransitionError(instruction.status, InstructionStatus.READY_FOR_APPROVAL)

    version_id = instruction.current_version_id
    version = db.get(InstructionVersion, version_id)
    original_text = version.raw_text

    extraction = (
        db.query(StructuredExtraction).filter(StructuredExtraction.instruction_version_id == version_id).first()
    )
    if extraction is None or extraction.completeness_status != CompletenessStatus.PASSED:
        raise GenerationNotAllowedError(
            "Cannot generate patient-friendly text: current version's extraction is not PASSED"
        )

    instruction_type = extraction.instruction_type
    normalized_facts = extraction.normalized_facts

    next_attempt_number = (
        db.query(func.max(PatientOutput.attempt_number))
        .filter(PatientOutput.instruction_version_id == version_id)
        .scalar()
        or 0
    ) + 1

    db.commit()  # closes the implicit read transaction above — no transaction or
    # connection is held during the LLM calls in _run_generation_and_apply below.

    return _run_generation_and_apply(
        db, instruction_id, version_id, next_attempt_number, original_text, normalized_facts, instruction_type, actor_id
    )


def _run_generation_and_apply(
    db: Session,
    instruction_id: uuid.UUID,
    version_id: uuid.UUID,
    attempt_number: int,
    original_text: str,
    normalized_facts: dict,
    instruction_type: InstructionType,
    actor_id: uuid.UUID,
) -> CareInstruction:
    try:
        provider = get_llm_provider()
    except ExtractionProviderError as exc:
        attempt = GenerationAttempt(
            succeeded=False,
            patient_text=None,
            metadata=None,
            prompt_version=GENERATION_PROMPT_VERSION,
            failure_reason=str(exc),
        )
        return _apply_generation_result(
            db, instruction_id, version_id, attempt_number, instruction_type, normalized_facts, attempt, None, actor_id
        )

    attempt = run_generation(provider, original_text, normalized_facts, instruction_type)

    # A second, independent AI call — re-extracting the text the first call just
    # generated — is the core of Layer B fact-preservation (see
    # validation/fact_preservation.py): never ask the LLM whether its own output
    # is safe, always re-derive facts from it the same way a real instruction
    # would be analyzed, then compare deterministically.
    reextraction_attempt = run_extraction(provider, attempt.patient_text) if attempt.succeeded else None

    return _apply_generation_result(
        db,
        instruction_id,
        version_id,
        attempt_number,
        instruction_type,
        normalized_facts,
        attempt,
        reextraction_attempt,
        actor_id,
    )


def _build_failed_patient_output(
    version_id: uuid.UUID, attempt_number: int, attempt: GenerationAttempt
) -> PatientOutput:
    return PatientOutput(
        instruction_version_id=version_id,
        attempt_number=attempt_number,
        patient_text_en=None,
        validation_status=ValidationStatus.FAILED,
        validation_diff=[],
        validation_messages=[attempt.failure_reason or "AI generation failed."],
        provider=attempt.metadata.provider if attempt.metadata else "unknown",
        model=attempt.metadata.model if attempt.metadata else "unknown",
        prompt_version=attempt.prompt_version,
        provider_request_id=attempt.metadata.request_id if attempt.metadata else None,
        latency_ms=attempt.metadata.latency_ms if attempt.metadata else None,
        token_usage=attempt.metadata.token_usage if attempt.metadata else None,
    )


def _apply_generation_result(
    db: Session,
    instruction_id: uuid.UUID,
    version_id_at_start: uuid.UUID,
    attempt_number: int,
    instruction_type: InstructionType,
    original_normalized_facts: dict,
    attempt: GenerationAttempt,
    reextraction_attempt: ExtractionAttempt | None,
    actor_id: uuid.UUID,
) -> CareInstruction:
    instruction = (
        db.query(CareInstruction).filter(CareInstruction.id == instruction_id).with_for_update().first()
    )
    if instruction is None:
        raise InstructionNotFoundError(str(instruction_id))

    # Stale-result protection — same rationale as _apply_extraction_result: if a
    # clarification moved current_version_id on while generation was in flight,
    # this result no longer applies to what the clinician is now looking at.
    is_stale = instruction.current_version_id != version_id_at_start

    if not attempt.succeeded:
        output = _build_failed_patient_output(version_id_at_start, attempt_number, attempt)
        db.add(output)
        if is_stale:
            db.commit()
            db.refresh(instruction)
            return instruction
        transition(instruction, InstructionStatus.NEEDS_REVIEW)
        instruction.review_reason = f"AI_GENERATION_FAILED: {attempt.failure_reason}"
        record_event(
            db,
            event_type=AuditEventType.FACT_VALIDATION_FAILED,
            actor_type=ActorType.CLINICIAN,
            actor_id=actor_id,
            patient_id=instruction.patient_id,
            entity_type="CareInstruction",
            entity_id=instruction.id,
            event_metadata={"reason": "AI_GENERATION_FAILED"},
        )
        db.commit()
        db.refresh(instruction)
        return instruction

    regenerated_instruction_type = None
    regenerated_facts = None
    regenerated_ambiguities = None
    if reextraction_attempt is not None and reextraction_attempt.succeeded:
        regenerated_instruction_type = reextraction_attempt.result.instruction_type
        regenerated_facts, _changes = normalize_facts(
            regenerated_instruction_type, reextraction_attempt.result.facts.model_dump()
        )
        regenerated_ambiguities = reextraction_attempt.result.ambiguities

    result = validate_fact_preservation(
        instruction_type=instruction_type,
        original_normalized_facts=original_normalized_facts,
        generated_text=attempt.patient_text,
        regenerated_instruction_type=regenerated_instruction_type,
        regenerated_facts=regenerated_facts,
        regenerated_ambiguities=regenerated_ambiguities,
    )

    output = PatientOutput(
        instruction_version_id=version_id_at_start,
        attempt_number=attempt_number,
        patient_text_en=attempt.patient_text,
        validation_status=ValidationStatus.PASSED if result.passed else ValidationStatus.FAILED,
        validation_diff=[asdict(d) for d in result.differences],
        validation_messages=result.messages,
        provider=attempt.metadata.provider,
        model=attempt.metadata.model,
        prompt_version=attempt.prompt_version,
        provider_request_id=attempt.metadata.request_id,
        latency_ms=attempt.metadata.latency_ms,
        token_usage=attempt.metadata.token_usage,
    )
    db.add(output)

    if is_stale:
        db.commit()
        db.refresh(instruction)
        return instruction

    record_event(
        db,
        event_type=AuditEventType.PATIENT_OUTPUT_GENERATED,
        actor_type=ActorType.CLINICIAN,
        actor_id=actor_id,
        patient_id=instruction.patient_id,
        entity_type="PatientOutput",
        entity_id=output.id,
        event_metadata={"attempt_number": attempt_number, "instruction_type": instruction_type.value},
    )

    if result.passed:
        transition(instruction, InstructionStatus.READY_FOR_APPROVAL)
        instruction.review_reason = None
        record_event(
            db,
            event_type=AuditEventType.FACT_VALIDATION_PASSED,
            actor_type=ActorType.CLINICIAN,
            actor_id=actor_id,
            patient_id=instruction.patient_id,
            entity_type="PatientOutput",
            entity_id=output.id,
        )
    else:
        transition(instruction, InstructionStatus.NEEDS_REVIEW)
        instruction.review_reason = "FACT_PRESERVATION_FAILED: " + (
            "; ".join(result.messages) if result.messages else "unspecified fact preservation failure"
        )
        record_event(
            db,
            event_type=AuditEventType.FACT_VALIDATION_FAILED,
            actor_type=ActorType.CLINICIAN,
            actor_id=actor_id,
            patient_id=instruction.patient_id,
            entity_type="PatientOutput",
            entity_id=output.id,
            event_metadata={
                "reason": "FACT_PRESERVATION_FAILED",
                "difference_count": len(result.differences),
                "difference_fields": [d.field for d in result.differences],
            },
        )

    db.commit()
    db.refresh(instruction)
    return instruction


# ---------------------------------------------------------------------------
# State-transition primitives. Both the analysis and generation pipelines above
# set NEEDS_REVIEW / READY_FOR_APPROVAL themselves (each needs that status change
# to commit atomically alongside its own StructuredExtraction/PatientOutput row,
# so neither reuses these primitives' own commit). These remain available for
# tests that need to place an instruction into a state nothing in the exposed
# API can reach directly (e.g. READY_FOR_APPROVAL without a real PASSED
# generation) — mark_ready_for_approval() in particular is not wired to any
# route, since the only real way to reach READY_FOR_APPROVAL is generate().
# ---------------------------------------------------------------------------


def mark_needs_review(db: Session, instruction: CareInstruction, reason: str) -> CareInstruction:
    transition(instruction, InstructionStatus.NEEDS_REVIEW)
    instruction.review_reason = reason
    db.commit()
    db.refresh(instruction)
    return instruction


def mark_ready_for_approval(db: Session, instruction: CareInstruction) -> CareInstruction:
    transition(instruction, InstructionStatus.READY_FOR_APPROVAL)
    instruction.review_reason = None
    db.commit()
    db.refresh(instruction)
    return instruction


def approve(db: Session, instruction: CareInstruction, approved_by: uuid.UUID) -> CareInstruction:
    # Defense in depth: READY_FOR_APPROVAL should only ever exist alongside a
    # PASSED PatientOutput (generate_patient_output() guarantees that), but this
    # is checked again independently here — an output that failed validation
    # must never become approvable even if instruction.status were somehow
    # corrupted separately from that invariant.
    latest_output = (
        db.query(PatientOutput)
        .filter(PatientOutput.instruction_version_id == instruction.current_version_id)
        .order_by(PatientOutput.attempt_number.desc())
        .first()
    )
    if latest_output is None or latest_output.validation_status != ValidationStatus.PASSED:
        raise GenerationNotAllowedError(
            "Cannot approve: current version has no validated (PASSED) patient output"
        )

    transition(instruction, InstructionStatus.APPROVED)
    instruction.approved_by = approved_by
    instruction.approved_at = datetime.now(timezone.utc)

    # Medication clinical lifecycle starts here, and ONLY here for a
    # MEDICATION-type instruction — see ClinicalStatus's docstring for why
    # every other instruction type must never have this column touched.
    # clinical_start_date uses approved_at's date, not created_at: the
    # moment a clinician actually signs off is a meaningfully different,
    # more clinically relevant timestamp than "when the draft record was
    # first created" (which could be much earlier, e.g. across a long
    # clarification back-and-forth).
    extraction = (
        db.query(StructuredExtraction)
        .filter(StructuredExtraction.instruction_version_id == instruction.current_version_id)
        .first()
    )
    if extraction is not None and extraction.instruction_type == InstructionType.MEDICATION:
        instruction.clinical_status = ClinicalStatus.ACTIVE
        instruction.clinical_start_date = instruction.approved_at.date()

    record_event(
        db,
        event_type=AuditEventType.INSTRUCTION_APPROVED,
        actor_type=ActorType.CLINICIAN,
        actor_id=approved_by,
        patient_id=instruction.patient_id,
        entity_type="CareInstruction",
        entity_id=instruction.id,
    )
    db.commit()
    db.refresh(instruction)
    return instruction


class ClinicalStatusNotAllowedError(Exception):
    """Raised when a clinical-status change is attempted on a non-MEDICATION
    instruction, or an instruction that was never approved as MEDICATION in
    the first place (clinical_status is still NULL) — see ClinicalStatus's
    docstring for why this must never be set for other instruction types."""


def set_clinical_status(
    db: Session, instruction: CareInstruction, new_status: ClinicalStatus, changed_by: uuid.UUID
) -> CareInstruction:
    if instruction.clinical_status is None:
        raise ClinicalStatusNotAllowedError(
            "This instruction has no medication clinical status to change "
            "(either it isn't a MEDICATION instruction, or it hasn't been approved yet)."
        )

    now = datetime.now(timezone.utc)
    instruction.clinical_status = new_status
    instruction.clinical_status_changed_at = now
    instruction.clinical_status_changed_by = changed_by
    if new_status in (ClinicalStatus.COMPLETED, ClinicalStatus.STOPPED):
        instruction.clinical_end_date = now.date()
    elif new_status == ClinicalStatus.ACTIVE:
        instruction.clinical_end_date = None  # reactivated — no longer "ended"

    record_event(
        db,
        event_type=AuditEventType.MEDICATION_CLINICAL_STATUS_CHANGED,
        actor_type=ActorType.CLINICIAN,
        actor_id=changed_by,
        patient_id=instruction.patient_id,
        entity_type="CareInstruction",
        entity_id=instruction.id,
        event_metadata={"new_status": new_status.value},
    )
    db.commit()
    db.refresh(instruction)
    return instruction


def reject(db: Session, instruction: CareInstruction, reason: str, actor_id: uuid.UUID) -> CareInstruction:
    transition(instruction, InstructionStatus.REJECTED)
    instruction.review_reason = reason
    record_event(
        db,
        event_type=AuditEventType.INSTRUCTION_REJECTED,
        actor_type=ActorType.CLINICIAN,
        actor_id=actor_id,
        patient_id=instruction.patient_id,
        entity_type="CareInstruction",
        entity_id=instruction.id,
        event_metadata={"reason": reason},
    )
    db.commit()
    db.refresh(instruction)
    return instruction


# ---------------------------------------------------------------------------
# Translation (Step 8): approved English -> Telugu/Hindi -> independent safety
# validation -> patient visibility. Never runs before clinician approval (an
# unapproved/rejected AI generation is never translated). Each requested
# language is fully independent: one language failing never blocks another,
# and a language that already has a translation row is returned as-is rather
# than re-translated (rows are immutable — see PatientOutputTranslation).
# ---------------------------------------------------------------------------


def create_translations(
    db: Session, instruction_id: uuid.UUID, languages: list[Language], actor_id: uuid.UUID
) -> dict[Language, PatientOutputTranslation]:
    instruction = (
        db.query(CareInstruction).filter(CareInstruction.id == instruction_id).with_for_update().first()
    )
    if instruction is None:
        raise InstructionNotFoundError(str(instruction_id))
    if instruction.status != InstructionStatus.APPROVED:
        raise TranslationNotAllowedError("Instruction must be APPROVED before it can be translated")

    version_id = instruction.current_version_id
    output = (
        db.query(PatientOutput)
        .filter(PatientOutput.instruction_version_id == version_id)
        .order_by(PatientOutput.attempt_number.desc())
        .first()
    )
    if output is None or output.validation_status != ValidationStatus.PASSED:
        raise TranslationNotAllowedError(
            "Cannot translate: current version has no validated (PASSED) patient output"
        )

    output_id = output.id
    english_text = output.patient_text_en
    extraction = (
        db.query(StructuredExtraction).filter(StructuredExtraction.instruction_version_id == version_id).first()
    )
    instruction_type = extraction.instruction_type
    normalized_facts = extraction.normalized_facts

    existing = {
        row.language: row
        for row in db.query(PatientOutputTranslation)
        .filter(PatientOutputTranslation.patient_output_id == output_id)
        .all()
    }

    db.commit()  # release before any LLM calls below

    results: dict[Language, PatientOutputTranslation] = {}
    for language in languages:
        if language in existing:
            # Immutable — a repeat request for an already-translated language
            # returns the existing row rather than re-translating.
            results[language] = existing[language]
            continue
        results[language] = _run_translation_and_apply(
            db, instruction_id, version_id, output_id, language, english_text, normalized_facts, instruction_type, actor_id
        )
    return results


def _run_translation_and_apply(
    db: Session,
    instruction_id: uuid.UUID,
    version_id: uuid.UUID,
    output_id: uuid.UUID,
    language: Language,
    english_text: str,
    normalized_facts: dict,
    instruction_type: InstructionType,
    actor_id: uuid.UUID,
) -> PatientOutputTranslation:
    try:
        provider = get_llm_provider()
    except ExtractionProviderError as exc:
        attempt = TranslationAttempt(
            succeeded=False,
            translated_text=None,
            metadata=None,
            prompt_version=TRANSLATION_PROMPT_VERSION,
            failure_reason=str(exc),
        )
        return _apply_translation_result(db, instruction_id, version_id, output_id, language, attempt, None, actor_id)

    attempt = run_translation(provider, english_text, language, normalized_facts)

    # Layer B (secondary, per spec — never the sole mechanism): back-translate
    # to English and re-extract it through the same pipeline used on clinical
    # instructions, so it can be compared against the canonical English facts
    # with the exact same deterministic comparator fact-preservation uses.
    back_translation_attempt = None
    if attempt.succeeded:
        back_translation_attempt = run_translation(provider, attempt.translated_text, Language.ENGLISH, {})

    return _apply_translation_result(
        db, instruction_id, version_id, output_id, language, attempt, back_translation_attempt, actor_id
    )


def _build_failed_translation(
    output_id: uuid.UUID, language: Language, attempt: TranslationAttempt
) -> PatientOutputTranslation:
    return PatientOutputTranslation(
        patient_output_id=output_id,
        language=language,
        translated_text=None,
        validation_status=ValidationStatus.FAILED,
        validation_diff=[],
        validation_messages=[attempt.failure_reason or "AI translation failed."],
        provider=attempt.metadata.provider if attempt.metadata else "unknown",
        model=attempt.metadata.model if attempt.metadata else "unknown",
        prompt_version=attempt.prompt_version,
        provider_request_id=attempt.metadata.request_id if attempt.metadata else None,
        latency_ms=attempt.metadata.latency_ms if attempt.metadata else None,
        token_usage=attempt.metadata.token_usage if attempt.metadata else None,
    )


def _apply_translation_result(
    db: Session,
    instruction_id: uuid.UUID,
    version_id_at_start: uuid.UUID,
    output_id: uuid.UUID,
    language: Language,
    attempt: TranslationAttempt,
    back_translation_attempt: TranslationAttempt | None,
    actor_id: uuid.UUID,
) -> PatientOutputTranslation:
    instruction = (
        db.query(CareInstruction).filter(CareInstruction.id == instruction_id).with_for_update().first()
    )
    if instruction is None:
        raise InstructionNotFoundError(str(instruction_id))

    # Stale protection: a translation must never attach itself to a newer
    # clinical instruction — verify the instruction is still APPROVED and the
    # version (and therefore the approved output) hasn't moved on.
    is_stale = (
        instruction.status != InstructionStatus.APPROVED or instruction.current_version_id != version_id_at_start
    )

    if not attempt.succeeded:
        translation = _build_failed_translation(output_id, language, attempt)
        db.add(translation)
        db.flush()  # assigns translation.id, needed as the audit event's entity_id below
        if not is_stale:
            record_event(
                db,
                event_type=AuditEventType.TRANSLATION_VALIDATION_FAILED,
                actor_type=ActorType.CLINICIAN,
                actor_id=actor_id,
                patient_id=instruction.patient_id,
                entity_type="PatientOutputTranslation",
                entity_id=translation.id,
                event_metadata={"language": language.value, "reason": "AI_TRANSLATION_FAILED"},
            )
        db.commit()
        db.refresh(translation)
        return translation

    extraction = db.query(StructuredExtraction).filter(
        StructuredExtraction.instruction_version_id == version_id_at_start
    ).first()
    instruction_type = extraction.instruction_type
    original_normalized_facts = extraction.normalized_facts

    back_translated_instruction_type = None
    back_translated_facts = None
    back_translated_ambiguities = None
    if back_translation_attempt is not None and back_translation_attempt.succeeded:
        reextraction = run_extraction(get_llm_provider(), back_translation_attempt.translated_text)
        if reextraction.succeeded:
            back_translated_instruction_type = reextraction.result.instruction_type
            back_translated_facts, _changes = normalize_facts(
                back_translated_instruction_type, reextraction.result.facts.model_dump()
            )
            back_translated_ambiguities = reextraction.result.ambiguities

    result = validate_translation_preservation(
        instruction_type=instruction_type,
        original_normalized_facts=original_normalized_facts,
        translated_text=attempt.translated_text,
        back_translated_instruction_type=back_translated_instruction_type,
        back_translated_facts=back_translated_facts,
        back_translated_ambiguities=back_translated_ambiguities,
    )

    translation = PatientOutputTranslation(
        patient_output_id=output_id,
        language=language,
        translated_text=attempt.translated_text,
        validation_status=ValidationStatus.PASSED if result.passed else ValidationStatus.FAILED,
        validation_diff=[asdict(d) for d in result.differences],
        validation_messages=result.messages,
        provider=attempt.metadata.provider,
        model=attempt.metadata.model,
        prompt_version=attempt.prompt_version,
        provider_request_id=attempt.metadata.request_id,
        latency_ms=attempt.metadata.latency_ms,
        token_usage=attempt.metadata.token_usage,
    )
    db.add(translation)
    db.flush()  # assigns translation.id, needed for the audit events below

    if not is_stale:
        record_event(
            db,
            event_type=AuditEventType.TRANSLATION_CREATED,
            actor_type=ActorType.CLINICIAN,
            actor_id=actor_id,
            patient_id=instruction.patient_id,
            entity_type="PatientOutputTranslation",
            entity_id=translation.id,
            event_metadata={"language": language.value},
        )
        record_event(
            db,
            event_type=(
                AuditEventType.TRANSLATION_VALIDATION_PASSED
                if result.passed
                else AuditEventType.TRANSLATION_VALIDATION_FAILED
            ),
            actor_type=ActorType.CLINICIAN,
            actor_id=actor_id,
            patient_id=instruction.patient_id,
            entity_type="PatientOutputTranslation",
            entity_id=translation.id,
            event_metadata=(
                {}
                if result.passed
                else {
                    "language": language.value,
                    "difference_count": len(result.differences),
                    "difference_fields": [d.field for d in result.differences],
                }
            ),
        )

    db.commit()
    db.refresh(translation)
    return translation
