import uuid
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.auth.provider import AuthenticatedUser
from app.core.db import get_db
from app.patient_access import service
from app.patient_access.schemas import (
    CareAccessTokenCreate,
    CareAccessTokenCreateResponse,
    CareAccessTokenListResponse,
    CareAccessTokenStatus,
    CareAccessTokenSummary,
    CarePlanAudioRequest,
    PatientCarePlanResponse,
)
from app.patient_access.service import InvalidCareAccessTokenError, TokenNotFoundError
from app.patient_chat import service as chat_service
from app.patient_chat.schemas import ChatMessageListResponse, ChatMessageRead, ChatSendRequest, ChatSendResponse
from app.patient_feedback import service as feedback_service
from app.patient_feedback.schemas import ComprehensionFeedbackCreate, ComprehensionFeedbackRead
from app.patient_feedback.service import InstructionNotFoundForPatientError
from app.patients.service import PatientNotFoundError
from app.tts.service import TextTooLongError, synthesize_speech

router = APIRouter(tags=["patient-access"])


def _token_status(record) -> CareAccessTokenStatus:
    if record.revoked_at is not None:
        return CareAccessTokenStatus.REVOKED
    if record.expires_at < datetime.now(timezone.utc):
        return CareAccessTokenStatus.EXPIRED
    return CareAccessTokenStatus.ACTIVE


def _to_summary(record) -> CareAccessTokenSummary:
    return CareAccessTokenSummary(
        id=record.id,
        created_at=record.created_at,
        expires_at=record.expires_at,
        revoked_at=record.revoked_at,
        status=_token_status(record),
    )


@router.post(
    "/patients/{patient_id}/care-access-tokens",
    response_model=CareAccessTokenCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_care_access_token(
    patient_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    payload: CareAccessTokenCreate = CareAccessTokenCreate(),
) -> CareAccessTokenCreateResponse:
    """Clinician-authenticated. Returns the raw token exactly once — it is
    never retrievable again (only its hash is stored)."""
    try:
        raw_token, record = service.generate_care_access_token(
            db, patient_id, uuid.UUID(current_user.id), expires_in_hours=payload.expires_in_hours
        )
    except PatientNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Patient not found") from exc
    return CareAccessTokenCreateResponse(token=raw_token, expires_at=record.expires_at)


@router.get("/patients/{patient_id}/care-access-tokens", response_model=CareAccessTokenListResponse)
def list_care_access_tokens(
    patient_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> CareAccessTokenListResponse:
    try:
        records = service.list_care_access_tokens(db, patient_id)
    except PatientNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Patient not found") from exc
    return CareAccessTokenListResponse(total=len(records), results=[_to_summary(r) for r in records])


@router.post("/care-access-tokens/{token_id}/revoke", response_model=CareAccessTokenSummary)
def revoke_care_access_token(
    token_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> CareAccessTokenSummary:
    """Clinician-authenticated. Idempotent — revoking an already-revoked token
    succeeds and returns its (already-revoked) state rather than erroring."""
    try:
        record = service.revoke_care_access_token(db, token_id, revoked_by=uuid.UUID(current_user.id))
    except TokenNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Token not found") from exc
    return _to_summary(record)


@router.get("/care-plan", response_model=PatientCarePlanResponse)
def get_care_plan(token: str, db: Annotated[Session, Depends(get_db)]) -> PatientCarePlanResponse:
    """Public — no clinician auth. Access is gated entirely by possession of an
    unguessable token. Every failure mode (token doesn't exist, expired,
    revoked) returns the identical generic error, so a caller probing tokens
    can't use the response to distinguish which case applies."""
    try:
        return service.get_care_plan(db, token)
    except InvalidCareAccessTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired access link"
        ) from exc


@router.post("/care-plan/audio")
async def get_care_plan_audio(payload: CarePlanAudioRequest, db: Annotated[Session, Depends(get_db)]) -> Response:
    """Public, same token gate as /care-plan. Only ever converts text the
    patient's browser is already displaying to speech — audio is an
    accessibility aid, never a separate source of patient-facing content."""
    try:
        service.validate_care_access_token(db, payload.token)
    except InvalidCareAccessTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired access link"
        ) from exc

    try:
        audio_bytes = await synthesize_speech(payload.text, payload.language)
    except TextTooLongError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except Exception as exc:  # upstream TTS failure — audio is best-effort, never fatal to the page
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Speech synthesis failed") from exc

    return Response(content=audio_bytes, media_type="audio/mpeg")


@router.get("/care-plan/chat", response_model=ChatMessageListResponse)
def get_care_plan_chat(token: str, db: Annotated[Session, Depends(get_db)]) -> ChatMessageListResponse:
    """Public, same token gate as /care-plan — returns this patient's chat
    history so far, so the conversation persists across a page reload."""
    try:
        record = service.validate_care_access_token(db, token)
    except InvalidCareAccessTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired access link"
        ) from exc
    messages = chat_service.list_chat_messages(db, record.patient_id)
    return ChatMessageListResponse(messages=[ChatMessageRead.model_validate(m) for m in messages])


@router.post("/care-plan/chat", response_model=ChatSendResponse)
def post_care_plan_chat(payload: ChatSendRequest, db: Annotated[Session, Depends(get_db)]) -> ChatSendResponse:
    """Public, same token gate as /care-plan. See app/patient_chat/service.py
    for the two hard, deterministic safety gates every message passes
    through before the AI is ever involved."""
    try:
        patient_message, assistant_message = chat_service.send_chat_message_by_token(db, payload.token, payload.text)
    except InvalidCareAccessTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired access link"
        ) from exc
    return ChatSendResponse(
        patient_message=ChatMessageRead.model_validate(patient_message),
        assistant_message=ChatMessageRead.model_validate(assistant_message),
    )


@router.post("/care-plan/feedback", response_model=ComprehensionFeedbackRead)
def post_care_plan_feedback(
    payload: ComprehensionFeedbackCreate, db: Annotated[Session, Depends(get_db)]
) -> ComprehensionFeedbackRead:
    """Public, same token gate as /care-plan. "Did this explanation help?" —
    see app/patient_feedback/models.py for why HAS_QUESTION/ASK_CARE_TEAM
    surface to the clinician and UNDERSTOOD doesn't."""
    try:
        feedback = feedback_service.record_feedback_by_token(db, payload.token, payload.instruction_id, payload.response)
    except InvalidCareAccessTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired access link"
        ) from exc
    except InstructionNotFoundForPatientError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Instruction not found") from exc
    return ComprehensionFeedbackRead.model_validate(feedback)
