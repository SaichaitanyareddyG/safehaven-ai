import uuid
from datetime import datetime

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.audit.models import ActorType, AuditEvent, AuditEventType


def record_event(
    db: Session,
    *,
    event_type: AuditEventType,
    actor_type: ActorType,
    patient_id: uuid.UUID | None = None,
    actor_id: uuid.UUID | None = None,
    entity_type: str | None = None,
    entity_id: uuid.UUID | None = None,
    event_metadata: dict | None = None,
) -> AuditEvent:
    """The single writer of audit rows. Business services call this explicitly at
    the boundary of a business operation, alongside their own domain changes —
    never from an ORM/ `after_insert` hook — so every audit row can be traced to
    an intentional call site in the code that describes what actually happened.

    Adds the row to `db` but does not commit: callers should add this alongside
    their own domain changes and let their existing `db.commit()` cover both, so
    the audit entry lands in the same transaction as the action it describes.

    `event_metadata` must never contain: API keys, raw access tokens or token
    hashes, LLM chain-of-thought, raw provider responses, or full clinical/
    patient instruction text. Small structured summaries (field names that
    changed, a validation reason, a language code, a difference count) are fine.
    """
    event = AuditEvent(
        event_type=event_type.value,
        actor_type=actor_type,
        actor_id=actor_id,
        patient_id=patient_id,
        entity_type=entity_type,
        entity_id=entity_id,
        event_metadata=event_metadata or {},
    )
    db.add(event)
    return event


def list_patient_audit_events(
    db: Session,
    patient_id: uuid.UUID,
    event_type: str | None,
    from_time: datetime | None,
    to_time: datetime | None,
    limit: int,
    offset: int,
) -> tuple[int, list[AuditEvent]]:
    query = db.query(AuditEvent).filter(AuditEvent.patient_id == patient_id)

    if event_type:
        query = query.filter(AuditEvent.event_type == event_type)
    if from_time is not None:
        query = query.filter(AuditEvent.created_at >= from_time)
    if to_time is not None:
        query = query.filter(AuditEvent.created_at <= to_time)

    total = query.with_entities(func.count(AuditEvent.id)).scalar() or 0
    results = query.order_by(AuditEvent.created_at.asc()).limit(limit).offset(offset).all()
    return total, results
