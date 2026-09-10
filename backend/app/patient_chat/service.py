import re
import uuid

from sqlalchemy.orm import Session

from app.ai.prompts import PATIENT_CHAT_DECLINE_MESSAGE
from app.ai.provider import ChatTurn, ExtractionProviderError, get_llm_provider
from app.audit.models import ActorType, AuditEventType
from app.audit.service import record_event
from app.instructions.models import CareInstruction, ClinicalStatus, InstructionStatus, InstructionVersion
from app.patient_access.service import resolve_why, validate_care_access_token
from app.patient_chat.models import ChatRole, PatientChatMessage

# Two hard, deterministic gates that run BEFORE the AI is ever called — the
# same "never trust the LLM alone for a safety-critical decision" principle
# as the rest of this app. A match on either one is answered with a fixed,
# pre-written reply; the LLM never sees the message at all in that case.
_EMERGENCY_PATTERNS = [
    re.compile(p, re.IGNORECASE)
    for p in [
        r"\bchest pain\b",
        r"\bcan.?t breathe\b",
        r"\bdifficulty breathing\b",
        r"\bsevere bleeding\b",
        r"\bsuicid",
        r"\bunconscious\b",
        r"\bstroke\b",
        r"\bheart attack\b",
        r"\ballerg(y|ic) reaction\b",
        r"\banaphyla",
        r"\boverdose\b",
    ]
]

_TREATMENT_CHANGE_PATTERNS = [
    re.compile(p, re.IGNORECASE)
    for p in [
        r"\bstop taking\b",
        r"\bskip (a|my|this) dose\b",
        r"\bdouble.?up\b",
        r"\bdouble (my |your )?dose\b",
        r"\bchange my dose\b",
        r"\bincrease my dose\b",
        r"\bdecrease my dose\b",
        r"\btake less\b",
        r"\btake more\b",
        r"\bcan i stop\b",
        r"\bis it okay to (skip|double)\b",
    ]
]

_EMERGENCY_REPLY = (
    "This may be a medical emergency. Please call emergency services or go to the nearest emergency room right away."
)

_TREATMENT_CHANGE_REPLY = (
    "I can't advise on changing your medication or dose. Please contact your care team before making any change "
    "to how or when you take it."
)

_MAX_HISTORY_TURNS = 10

_FACTS_SKIP_KEYS = {"reason", "purpose"}  # already surfaced via resolve_why(), not repeated


def _matches_any(patterns: list[re.Pattern], text: str) -> bool:
    return any(p.search(text) for p in patterns)


def _facts_line(facts: dict) -> str:
    parts = [f"{key.replace('_', ' ')}: {value}" for key, value in facts.items() if value and key not in _FACTS_SKIP_KEYS]
    return ", ".join(parts)


def _build_care_plan_summary(db: Session, patient_id: uuid.UUID) -> str:
    """Only APPROVED, currently-active instructions — a stopped/completed
    medication must never be presented to the chat model as something the
    patient is currently taking (the same rule get_care_plan() applies to the
    patient-visible care plan itself). Uses the same resolve_why() as the
    care plan view, so "why" here is exactly as conservative — a documented
    reason or a curated general reference fact, never inferred from a
    diagnosis."""
    instructions = (
        db.query(CareInstruction)
        .filter(CareInstruction.patient_id == patient_id, CareInstruction.status == InstructionStatus.APPROVED)
        .order_by(CareInstruction.approved_at.desc())
        .all()
    )

    lines: list[str] = []
    for instruction in instructions:
        if instruction.clinical_status in (ClinicalStatus.COMPLETED, ClinicalStatus.STOPPED):
            continue
        version = db.get(InstructionVersion, instruction.current_version_id)
        extraction = version.extraction if version else None
        if extraction is None:
            continue

        facts = extraction.normalized_facts
        name = facts.get("medication_name") or extraction.instruction_type.value.replace("_", " ").title()
        line = f"- {name}: {_facts_line(facts)}"

        why = resolve_why(extraction)
        if why is not None:
            line += f" (reason/purpose: {why.text})"
        lines.append(line)

    if not lines:
        return "This patient currently has no approved active instructions on file."
    return "\n".join(lines)


def _recent_history_for_context(db: Session, patient_id: uuid.UUID) -> list[ChatTurn]:
    messages = (
        db.query(PatientChatMessage)
        .filter(PatientChatMessage.patient_id == patient_id)
        .order_by(PatientChatMessage.created_at.desc())
        .limit(_MAX_HISTORY_TURNS)
        .all()
    )
    messages.reverse()
    return [ChatTurn(role="user" if m.role == ChatRole.PATIENT else "assistant", text=m.text) for m in messages]


def list_chat_messages(db: Session, patient_id: uuid.UUID) -> list[PatientChatMessage]:
    return (
        db.query(PatientChatMessage)
        .filter(PatientChatMessage.patient_id == patient_id)
        .order_by(PatientChatMessage.created_at.asc())
        .all()
    )


def send_chat_message_by_token(db: Session, raw_token: str, text: str) -> tuple[PatientChatMessage, PatientChatMessage]:
    record = validate_care_access_token(db, raw_token)
    return send_chat_message(db, record.patient_id, text)


def send_chat_message(db: Session, patient_id: uuid.UUID, text: str) -> tuple[PatientChatMessage, PatientChatMessage]:
    emergency = _matches_any(_EMERGENCY_PATTERNS, text)
    treatment_change = not emergency and _matches_any(_TREATMENT_CHANGE_PATTERNS, text)

    patient_message = PatientChatMessage(
        patient_id=patient_id,
        role=ChatRole.PATIENT,
        text=text,
        emergency_flagged=emergency,
        redirect_flagged=treatment_change,
    )
    db.add(patient_message)
    db.flush()  # assigns patient_message.id for the audit event below

    web_search_used = False

    if emergency:
        reply_text = _EMERGENCY_REPLY
        record_event(
            db,
            event_type=AuditEventType.PATIENT_CHAT_EMERGENCY_FLAGGED,
            actor_type=ActorType.PATIENT,
            patient_id=patient_id,
            entity_type="PatientChatMessage",
            entity_id=patient_message.id,
        )
    elif treatment_change:
        reply_text = _TREATMENT_CHANGE_REPLY
        record_event(
            db,
            event_type=AuditEventType.PATIENT_CHAT_TREATMENT_CHANGE_REDIRECTED,
            actor_type=ActorType.PATIENT,
            patient_id=patient_id,
            entity_type="PatientChatMessage",
            entity_id=patient_message.id,
        )
    else:
        care_plan_summary = _build_care_plan_summary(db, patient_id)
        history = _recent_history_for_context(db, patient_id)
        provider = get_llm_provider()
        try:
            response = provider.chat_with_patient(care_plan_summary, history)
            reply_text = response.reply_text
            web_search_used = response.web_search_used
        except ExtractionProviderError:
            # Provider outage — fail safe with the same fixed decline the
            # prompt itself would give for "not enough information," never a
            # guess composed without a working model call.
            reply_text = PATIENT_CHAT_DECLINE_MESSAGE

        if web_search_used:
            record_event(
                db,
                event_type=AuditEventType.PATIENT_CHAT_WEB_SEARCH_USED,
                actor_type=ActorType.PATIENT,
                patient_id=patient_id,
                entity_type="PatientChatMessage",
                entity_id=patient_message.id,
            )

    assistant_message = PatientChatMessage(
        patient_id=patient_id,
        role=ChatRole.ASSISTANT,
        text=reply_text,
        emergency_flagged=False,
        redirect_flagged=False,
        web_search_used=web_search_used,
    )
    db.add(assistant_message)
    db.commit()
    db.refresh(patient_message)
    db.refresh(assistant_message)
    return patient_message, assistant_message
