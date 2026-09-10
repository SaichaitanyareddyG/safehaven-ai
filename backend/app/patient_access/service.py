import hashlib
import logging
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.audit.models import ActorType, AuditEvent, AuditEventType
from app.audit.service import record_event
from app.core.config import get_settings
from app.instructions.models import (
    CareInstruction,
    ClinicalStatus,
    InstructionStatus,
    InstructionType,
    InstructionVersion,
    PatientOutput,
    StructuredExtraction,
    ValidationStatus,
)
from app.patient_access.models import PatientCareAccessToken
from app.patient_access.schemas import PatientCareInstructionView, PatientCarePlanResponse, WhyExplanation, WhyTier
from app.patients.models import Patient
from app.patients.service import get_patient
from app.reference.medication_purpose import lookup_medication_purpose

_GENERAL_PURPOSE_DISCLAIMER = (
    "This is general reference information, not reviewed by your care team, and may not be fully accurate for you. "
    "Please consult your doctor for confirmation."
)

# Fields holding "why" per instruction type — MedicationFacts/MobilityFacts/
# DietFacts/WoundCareFacts all use "reason"; FollowUpFacts already had its own
# "purpose" field from Step 5, predating and serving the same role here.
_REASON_FIELD_BY_TYPE = {
    InstructionType.MEDICATION: "reason",
    InstructionType.MOBILITY: "reason",
    InstructionType.DIET: "reason",
    InstructionType.WOUND_CARE: "reason",
    InstructionType.FOLLOW_UP: "purpose",
}


def resolve_why(extraction: StructuredExtraction | None) -> WhyExplanation | None:
    """The three-tier "why" decision — deterministic, not LLM-decided (same
    "AI proposes facts, application rules decide what to show" principle as
    completeness/fact-preservation elsewhere):

      Tier 1 (DOCUMENTED): the clinician's own instruction text stated a
        reason (extracted the same "never invent" way as every other fact) —
        show it directly, no disclaimer needed.
      Tier 2 (GENERAL): no documented reason, but a static, curated,
        non-patient-specific reference entry exists for this medication (see
        app/reference/medication_purpose.py) — show it with a disclaimer that
        it isn't confirmed as this patient's specific reason. Only built for
        MEDICATION in this prototype; other instruction types have no
        reference table yet and fall through to Tier 3 when undocumented.

        Deliberately NOT extended to match against a patient's documented
        conditions (e.g. "patient has Hypertension documented, and this
        medication commonly treats Hypertension, so show that"), even when
        there is exactly one condition on file. An earlier version of this
        feature did exactly that; it was removed as a product/safety
        correction: a diagnosis merely existing alongside a medication that
        happens to treat it is still an inference, not a documented fact —
        many medications treat multiple conditions, and "the only diagnosis
        on file" is not the same as "the clinician said this medication is
        for this diagnosis." Tier 1 above is the only path to a
        patient-specific reason, and it requires an explicit link (today:
        the clinician's own instruction text stating the reason; in a real
        EHR integration, a structured medication-to-indication field) — never
        a same-patient co-occurrence the system connects on its own.

        Also deliberately NOT backed by an LLM asked "what is this
        medication commonly used for" from its own general knowledge — an
        earlier version of this feature did that too (for medications
        outside this curated table), and it was removed for the same reason
        this module now only draws from a vetted, human-curated table: this
        tier's whole premise is "trusted general reference information," and
        an ungrounded model call has no source to be trusted against. A
        medication outside this table falls through to Tier 3 instead of
        guessing.
      Tier 3 (NONE): neither — show nothing. Never guess.

    English-only for now: DOCUMENTED comes from raw extracted English text,
    and GENERAL is a static English reference table — translating either
    through the same validated pipeline as the main instruction text is a
    real feature (structured translation + back-translation verification),
    not a one-line addition, and is intentionally left for a future step
    rather than shown untranslated or unvalidated."""
    if extraction is None or extraction.instruction_type is None:
        return None

    reason_field = _REASON_FIELD_BY_TYPE.get(extraction.instruction_type)
    reason = extraction.normalized_facts.get(reason_field) if reason_field else None
    if reason:
        return WhyExplanation(tier=WhyTier.DOCUMENTED, text=reason)

    if extraction.instruction_type == InstructionType.MEDICATION:
        medication_name = extraction.normalized_facts.get("medication_name")
        general_purpose = lookup_medication_purpose(medication_name)
        if general_purpose:
            return WhyExplanation(tier=WhyTier.GENERAL, text=general_purpose, disclaimer=_GENERAL_PURPOSE_DISCLAIMER)

    return None


TOKEN_BYTES = 32  # 256 bits of entropy — cryptographically strong, per requirement

logger = logging.getLogger(__name__)


class InvalidCareAccessTokenError(Exception):
    """Raised uniformly for "doesn't exist" / "expired" / "revoked" — the HTTP
    layer must never let a caller distinguish between these (see router.py),
    so this single exception type carries no distinguishing detail by design."""


class TokenNotFoundError(Exception):
    pass


def _hash_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def generate_care_access_token(
    db: Session, patient_id: uuid.UUID, created_by: uuid.UUID, expires_in_hours: int | None = None
) -> tuple[str, PatientCareAccessToken]:
    """Returns (raw_token, record). The raw token is never persisted or logged —
    only its hash is stored — and this is the only place it's ever available."""
    get_patient(db, patient_id)  # raises PatientNotFoundError if missing

    settings = get_settings()
    ttl_hours = settings.care_token_ttl_hours
    if expires_in_hours is not None:
        ttl_hours = max(1, min(expires_in_hours, settings.care_token_ttl_hours))

    raw_token = secrets.token_urlsafe(TOKEN_BYTES)
    record = PatientCareAccessToken(
        patient_id=patient_id,
        token_hash=_hash_token(raw_token),
        expires_at=datetime.now(timezone.utc) + timedelta(hours=ttl_hours),
        created_by=created_by,
    )
    db.add(record)
    db.flush()  # assigns record.id, needed as the audit event's entity_id below

    record_event(
        db,
        event_type=AuditEventType.CARE_ACCESS_TOKEN_CREATED,
        actor_type=ActorType.CLINICIAN,
        actor_id=created_by,
        patient_id=patient_id,
        entity_type="PatientCareAccessToken",
        entity_id=record.id,
        event_metadata={"expires_at": record.expires_at.isoformat(), "ttl_hours": ttl_hours},
    )
    db.commit()
    db.refresh(record)
    return raw_token, record


def list_care_access_tokens(db: Session, patient_id: uuid.UUID) -> list[PatientCareAccessToken]:
    get_patient(db, patient_id)  # raises PatientNotFoundError if missing
    return (
        db.query(PatientCareAccessToken)
        .filter(PatientCareAccessToken.patient_id == patient_id)
        .order_by(PatientCareAccessToken.created_at.desc())
        .all()
    )


def revoke_care_access_token(db: Session, token_id: uuid.UUID, revoked_by: uuid.UUID) -> PatientCareAccessToken:
    """Idempotent: revoking an already-revoked token is a safe no-op (returns the
    existing record, no duplicate audit event)."""
    record = db.get(PatientCareAccessToken, token_id)
    if record is None:
        raise TokenNotFoundError(str(token_id))

    if record.revoked_at is None:
        record.revoked_at = datetime.now(timezone.utc)
        record_event(
            db,
            event_type=AuditEventType.CARE_ACCESS_TOKEN_REVOKED,
            actor_type=ActorType.CLINICIAN,
            actor_id=revoked_by,
            patient_id=record.patient_id,
            entity_type="PatientCareAccessToken",
            entity_id=record.id,
        )

    db.commit()
    db.refresh(record)
    return record


def revoke_all_tokens_for_patient(
    db: Session, patient_id: uuid.UUID, commit: bool = True
) -> list[PatientCareAccessToken]:
    """Called by the discharge orchestration (see app/orchestration/) — bedside/
    patient-facing links must stop working immediately. Attributed to SYSTEM,
    not the clinician who discharged the patient: it's an automatic side
    effect of discharge, not a direct action on the token itself.

    commit=False lets the caller fold this into a larger single transaction."""
    active_tokens = (
        db.query(PatientCareAccessToken)
        .filter(PatientCareAccessToken.patient_id == patient_id, PatientCareAccessToken.revoked_at.is_(None))
        .all()
    )
    now = datetime.now(timezone.utc)
    for token in active_tokens:
        token.revoked_at = now
        record_event(
            db,
            event_type=AuditEventType.CARE_ACCESS_TOKEN_REVOKED,
            actor_type=ActorType.SYSTEM,
            patient_id=patient_id,
            entity_type="PatientCareAccessToken",
            entity_id=token.id,
            event_metadata={"reason": "patient_discharged"},
        )
    if commit:
        db.commit()
    else:
        db.flush()
    return active_tokens


def _maybe_record_view_event(db: Session, record: PatientCareAccessToken) -> None:
    """CARE_PLAN_VIEWED, deduplicated per-token within a configurable window so
    a patient reopening/refreshing their care link doesn't spam the timeline."""
    settings = get_settings()
    window_start = datetime.now(timezone.utc) - timedelta(minutes=settings.care_plan_view_dedup_minutes)
    recent = (
        db.query(AuditEvent)
        .filter(
            AuditEvent.event_type == AuditEventType.CARE_PLAN_VIEWED.value,
            AuditEvent.entity_id == record.id,
            AuditEvent.created_at >= window_start,
        )
        .first()
    )
    if recent is not None:
        return
    record_event(
        db,
        event_type=AuditEventType.CARE_PLAN_VIEWED,
        actor_type=ActorType.PATIENT,
        patient_id=record.patient_id,
        entity_type="PatientCareAccessToken",
        entity_id=record.id,
    )


def validate_care_access_token(db: Session, raw_token: str) -> PatientCareAccessToken:
    """Shared by get_care_plan and any other patient-facing, token-gated
    endpoint (e.g. the audio endpoint) — same generic failure for every
    invalid reason, same no-audit-row-for-invalid-tokens behavior, see
    InvalidCareAccessTokenError's docstring."""
    record = (
        db.query(PatientCareAccessToken).filter(PatientCareAccessToken.token_hash == _hash_token(raw_token)).first()
    )
    if record is None:
        logger.warning("Care plan requested with a token that does not match any issued token.")
        raise InvalidCareAccessTokenError("not found")
    if record.revoked_at is not None:
        logger.warning("Care plan requested with a revoked token.")
        raise InvalidCareAccessTokenError("revoked")
    if record.expires_at < datetime.now(timezone.utc):
        logger.warning("Care plan requested with an expired token.")
        raise InvalidCareAccessTokenError("expired")
    return record


def get_care_plan(db: Session, raw_token: str) -> PatientCarePlanResponse:
    record = validate_care_access_token(db, raw_token)
    patient = db.get(Patient, record.patient_id)

    approved_instructions = (
        db.query(CareInstruction)
        .filter(CareInstruction.patient_id == patient.id, CareInstruction.status == InstructionStatus.APPROVED)
        .order_by(CareInstruction.approved_at.desc())
        .all()
    )

    views: list[PatientCareInstructionView] = []
    past_medication_views: list[PatientCareInstructionView] = []
    for instruction in approved_instructions:
        version = db.get(InstructionVersion, instruction.current_version_id)
        output = (
            db.query(PatientOutput)
            .filter(
                PatientOutput.instruction_version_id == version.id,
                PatientOutput.validation_status == ValidationStatus.PASSED,
            )
            .order_by(PatientOutput.attempt_number.desc())
            .first()
        )
        if output is None:
            # Shouldn't happen given approve()'s own invariant, but the patient
            # must never see a failed/unvalidated generation regardless.
            continue

        text_by_language = {"ENGLISH": output.patient_text_en}
        for translation in output.translations:
            if translation.validation_status == ValidationStatus.PASSED:
                text_by_language[translation.language.value] = translation.translated_text

        view = PatientCareInstructionView(
            id=instruction.id,
            instruction_type=version.extraction.instruction_type if version.extraction else None,
            text_by_language=text_by_language,
            approved_at=instruction.approved_at,
            why=resolve_why(version.extraction),
        )

        # Only a MEDICATION instruction ever carries a clinical_status at all
        # (see ClinicalStatus's docstring) — every other instruction type
        # keeps showing exactly as before, undifferentiated. A completed or
        # stopped medication moves to the separate past-medications list
        # instead of the current one; it is never simply hidden, and its
        # historical CareInstruction row is never touched or deleted.
        if instruction.clinical_status in (ClinicalStatus.COMPLETED, ClinicalStatus.STOPPED):
            past_medication_views.append(view)
        else:
            views.append(view)

    _maybe_record_view_event(db, record)
    db.commit()

    return PatientCarePlanResponse(
        patient_first_name=patient.first_name,
        preferred_language=patient.preferred_language,
        past_medications=past_medication_views,
        instructions=views,
    )
