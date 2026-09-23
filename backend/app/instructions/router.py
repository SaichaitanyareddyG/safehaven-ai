import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy.orm import Session

from app.ai.provider import ExtractionProviderError, get_llm_provider
from app.auth.dependencies import get_current_user
from app.auth.provider import AuthenticatedUser
from app.core.db import get_db
from app.instructions import service
from app.instructions.models import CaptureMethod, ClinicalStatus, InstructionStatus
from app.instructions.schemas import (
    CareInstructionDetail,
    CareInstructionListResponse,
    CareInstructionRead,
    ClinicalStatusUpdate,
    DictationWarningRead,
    InstructionTextPayload,
    RejectionRequest,
    TranscriptionResponse,
    TranslationRequest,
    TranslationResultItem,
)
from app.validation.dictation_safety import check_dictation
from app.instructions.service import (
    ClinicalStatusNotAllowedError,
    GenerationNotAllowedError,
    InstructionNotFoundError,
    PatientNotActiveError,
    TranslationNotAllowedError,
)
from app.instructions.state import InvalidTransitionError
from app.patients.service import PatientNotFoundError

router = APIRouter(tags=["instructions"])


def _not_found(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail)


def _conflict(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail)


@router.post(
    "/patients/{patient_id}/instructions",
    response_model=CareInstructionRead,
    status_code=status.HTTP_201_CREATED,
)
def create_instruction(
    patient_id: uuid.UUID,
    payload: InstructionTextPayload,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> CareInstructionRead:
    try:
        return service.create_instruction(
            db,
            patient_id,
            payload.text,
            created_by=uuid.UUID(current_user.id),
            capture_method=CaptureMethod.DICTATED if payload.dictated else CaptureMethod.TYPED,
        )
    except PatientNotFoundError as exc:
        raise _not_found("Patient not found") from exc
    except PatientNotActiveError as exc:
        raise _conflict("Cannot create an instruction for a patient who is not ACTIVE") from exc


_MAX_DICTATION_BYTES = 10 * 1024 * 1024  # ~2 minutes of browser-recorded audio; an instruction is a sentence or two


@router.post("/instructions/transcribe", response_model=TranscriptionResponse)
async def transcribe_dictation(
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    file: UploadFile = File(...),
) -> TranscriptionResponse:
    """Transcribes dictated audio into an editable DRAFT. Creates nothing —
    no instruction, no version, no database row of any kind, and takes no
    patient_id precisely so that it cannot.

    That is the structural guarantee behind this whole feature: a transcript
    physically cannot become a clinical order without the clinician
    submitting it through the ordinary creation endpoint, because this
    endpoint has nothing to submit it to. See
    MODULE_1_VOICE_DICTATION_DESIGN.md §3 for why that matters — a mis-heard
    dose is invisible to every downstream validator, since the transcript
    becomes the very source of truth they all check against.

    The audio itself is never persisted: transcribed in-request, then
    dropped. Same posture as identify_from_image() and STORE_RAW_LLM_DATA.
    """
    audio_bytes = await file.read()
    if not audio_bytes:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No audio was received")
    if len(audio_bytes) > _MAX_DICTATION_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Recording is too long — dictate one instruction at a time",
        )

    try:
        result = get_llm_provider().transcribe_audio(audio_bytes, file.content_type or "audio/webm")
    except ExtractionProviderError as exc:
        # Never fabricate a transcript on failure — the clinician types
        # instead, exactly as they do today.
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail="Could not transcribe the recording — please type it"
        ) from exc

    return TranscriptionResponse(
        text=result.text,
        warnings=[DictationWarningRead(code=w.code, message=w.message, excerpt=w.excerpt) for w in check_dictation(result.text)],
    )


@router.get("/patients/{patient_id}/instructions", response_model=CareInstructionListResponse)
def list_patient_instructions(
    patient_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    status_filter: Annotated[InstructionStatus | None, Query(alias="status")] = None,
    clinical_status: Annotated[ClinicalStatus | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> CareInstructionListResponse:
    try:
        total, results = service.list_patient_instructions(
            db, patient_id, status_filter, limit, offset, clinical_status
        )
    except PatientNotFoundError as exc:
        raise _not_found("Patient not found") from exc
    return CareInstructionListResponse(total=total, results=results)


@router.get("/instructions/{instruction_id}", response_model=CareInstructionDetail)
def get_instruction(
    instruction_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> CareInstructionDetail:
    try:
        return service.get_instruction(db, instruction_id)
    except InstructionNotFoundError as exc:
        raise _not_found("Instruction not found") from exc


@router.post("/instructions/{instruction_id}/analyze", response_model=CareInstructionDetail)
def analyze_instruction(
    instruction_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> CareInstructionDetail:
    """DRAFT -> PROCESSING, then runs AI extraction + deterministic completeness
    validation. Replaces Step 4's placeholder /submit (which just flipped status
    with no analysis) now that real analysis exists."""
    try:
        return service.analyze_instruction(db, instruction_id, actor_id=uuid.UUID(current_user.id))
    except InstructionNotFoundError as exc:
        raise _not_found("Instruction not found") from exc
    except InvalidTransitionError as exc:
        raise _conflict(str(exc)) from exc


@router.post("/instructions/{instruction_id}/clarify", response_model=CareInstructionDetail)
def clarify_instruction(
    instruction_id: uuid.UUID,
    payload: InstructionTextPayload,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> CareInstructionDetail:
    try:
        return service.create_clarification(
            db, instruction_id, payload.text, created_by=uuid.UUID(current_user.id)
        )
    except InstructionNotFoundError as exc:
        raise _not_found("Instruction not found") from exc
    except InvalidTransitionError as exc:
        raise _conflict(str(exc)) from exc


@router.post("/instructions/{instruction_id}/generate", response_model=CareInstructionDetail)
def generate_patient_output(
    instruction_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> CareInstructionDetail:
    """PROCESSING (with a PASSED extraction on the current version) -> generates
    patient-friendly text -> fact-preservation validation -> READY_FOR_APPROVAL
    on success, back to NEEDS_REVIEW (FACT_PRESERVATION_FAILED / AI_GENERATION_FAILED)
    on failure. Never auto-approves — a clinician still must approve explicitly."""
    try:
        return service.generate_patient_output(db, instruction_id, actor_id=uuid.UUID(current_user.id))
    except InstructionNotFoundError as exc:
        raise _not_found("Instruction not found") from exc
    except (InvalidTransitionError, GenerationNotAllowedError) as exc:
        raise _conflict(str(exc)) from exc


@router.post("/instructions/{instruction_id}/approve", response_model=CareInstructionRead)
def approve_instruction(
    instruction_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> CareInstructionRead:
    try:
        instruction = service.get_instruction(db, instruction_id)
    except InstructionNotFoundError as exc:
        raise _not_found("Instruction not found") from exc
    try:
        return service.approve(db, instruction, approved_by=uuid.UUID(current_user.id))
    except (InvalidTransitionError, GenerationNotAllowedError) as exc:
        raise _conflict(str(exc)) from exc


@router.patch("/instructions/{instruction_id}/clinical-status", response_model=CareInstructionRead)
def update_clinical_status(
    instruction_id: uuid.UUID,
    payload: ClinicalStatusUpdate,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> CareInstructionRead:
    """Medication-only — see ClinicalStatus's docstring. Rejects with 422 on
    any instruction whose clinical_status is still None (never a MEDICATION
    instruction that reached APPROVED, or not MEDICATION at all)."""
    try:
        instruction = service.get_instruction(db, instruction_id)
    except InstructionNotFoundError as exc:
        raise _not_found("Instruction not found") from exc
    try:
        return service.set_clinical_status(
            db, instruction, payload.status, changed_by=uuid.UUID(current_user.id)
        )
    except ClinicalStatusNotAllowedError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


@router.post("/instructions/{instruction_id}/translations", response_model=dict[str, TranslationResultItem])
def request_translations(
    instruction_id: uuid.UUID,
    payload: TranslationRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> dict[str, TranslationResultItem]:
    """Only allowed once the instruction is APPROVED and its current output is
    PASSED — translation never runs on unapproved/rejected AI output. Partial
    success is normal: one language failing (e.g. Telugu) never blocks another
    (e.g. Hindi) that already passed, or the already-approved English text."""
    try:
        results = service.create_translations(
            db, instruction_id, payload.languages, actor_id=uuid.UUID(current_user.id)
        )
    except InstructionNotFoundError as exc:
        raise _not_found("Instruction not found") from exc
    except TranslationNotAllowedError as exc:
        raise _conflict(str(exc)) from exc
    return {
        language.value: TranslationResultItem(status=translation.validation_status)
        for language, translation in results.items()
    }


@router.post("/instructions/{instruction_id}/reject", response_model=CareInstructionRead)
def reject_instruction(
    instruction_id: uuid.UUID,
    payload: RejectionRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> CareInstructionRead:
    try:
        instruction = service.get_instruction(db, instruction_id)
    except InstructionNotFoundError as exc:
        raise _not_found("Instruction not found") from exc
    try:
        return service.reject(db, instruction, payload.reason, actor_id=uuid.UUID(current_user.id))
    except InvalidTransitionError as exc:
        raise _conflict(str(exc)) from exc
