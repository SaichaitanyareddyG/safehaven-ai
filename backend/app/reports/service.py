import hashlib
import uuid
from datetime import date, datetime, timezone

from sqlalchemy.orm import Session, undefer

from app.audit.models import ActorType, AuditEventType
from app.audit.service import record_event
from app.patients.service import get_patient
from app.reports.models import PatientReport, ReportCategory

MAX_REPORT_BYTES = 10 * 1024 * 1024

# What the file really is, from its first bytes. Anything else is refused,
# whatever its name says: no HTML, scripts or office files that could carry
# active content.
_SIGNATURES = (
    (b"%PDF-", "application/pdf"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
)


class ReportError(Exception):
    """Safe to show."""


class ReportNotFoundError(Exception):
    pass


def sniff(data: bytes) -> str | None:
    for magic, content_type in _SIGNATURES:
        if data.startswith(magic):
            return content_type
    return None


def upload(
    db: Session,
    patient_id: uuid.UUID,
    uploaded_by: uuid.UUID,
    *,
    data: bytes,
    title: str,
    category: ReportCategory,
    report_date: date | None,
    shared_with_patient: bool,
) -> PatientReport:
    get_patient(db, patient_id)
    title = title.strip()
    if not title:
        raise ReportError("Give the report a title.")
    if not data:
        raise ReportError("The file is empty.")
    if len(data) > MAX_REPORT_BYTES:
        raise ReportError("The file is larger than 10 MB.")
    content_type = sniff(data)
    if content_type is None:
        raise ReportError("Only PDF, PNG or JPEG files can be uploaded.")
    report = PatientReport(
        patient_id=patient_id,
        title=title[:200],
        category=category.value,
        report_date=report_date,
        content_type=content_type,
        size=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        data=data,
        shared_with_patient=shared_with_patient,
        uploaded_by=uploaded_by,
    )
    db.add(report)
    db.flush()
    record_event(
        db,
        event_type=AuditEventType.REPORT_UPLOADED,
        actor_type=ActorType.CLINICIAN,
        actor_id=uploaded_by,
        patient_id=patient_id,
        entity_type="PatientReport",
        entity_id=report.id,
        event_metadata={"category": category.value, "shared_with_patient": shared_with_patient},
    )
    db.commit()
    db.refresh(report)
    return report


def list_reports(db: Session, patient_id: uuid.UUID, *, shared_only: bool = False) -> list[PatientReport]:
    get_patient(db, patient_id)
    query = db.query(PatientReport).filter(PatientReport.patient_id == patient_id, PatientReport.removed_at.is_(None))
    if shared_only:
        query = query.filter(PatientReport.shared_with_patient.is_(True))
    return query.order_by(PatientReport.report_date.desc().nullslast(), PatientReport.created_at.desc()).all()


def get_report(db: Session, report_id: uuid.UUID, *, with_data: bool = False) -> PatientReport:
    query = db.query(PatientReport).filter(PatientReport.id == report_id)
    if with_data:
        query = query.options(undefer(PatientReport.data))
    report = query.first()
    if report is None or report.removed_at is not None:
        raise ReportNotFoundError(str(report_id))
    return report


def record_view(
    db: Session, report: PatientReport, *, staff_id: uuid.UUID | None = None, viewer_role: str | None = None
) -> None:
    """Every opening, by anyone: who looked at a patient's document belongs
    on their record."""
    record_event(
        db,
        event_type=AuditEventType.REPORT_VIEWED,
        actor_type=ActorType.CLINICIAN if staff_id else ActorType.PATIENT,
        actor_id=staff_id,
        patient_id=report.patient_id,
        entity_type="PatientReport",
        entity_id=report.id,
        event_metadata={"viewer": viewer_role} if viewer_role else {},
    )
    db.commit()


def update(
    db: Session,
    report_id: uuid.UUID,
    updated_by: uuid.UUID,
    *,
    title: str | None = None,
    category: ReportCategory | None = None,
    report_date: date | None = None,
    shared_with_patient: bool | None = None,
    fields_set: set[str] = frozenset(),
) -> PatientReport:
    report = get_report(db, report_id)
    changed = []
    if "title" in fields_set and title is not None and title.strip():
        report.title = title.strip()[:200]
        changed.append("title")
    if "category" in fields_set and category is not None:
        report.category = category.value
        changed.append("category")
    if "report_date" in fields_set:
        report.report_date = report_date
        changed.append("report_date")
    sharing_changed = (
        "shared_with_patient" in fields_set
        and shared_with_patient is not None
        and shared_with_patient != report.shared_with_patient
    )
    if sharing_changed:
        report.shared_with_patient = shared_with_patient
        record_event(
            db,
            event_type=AuditEventType.REPORT_SHARED if shared_with_patient else AuditEventType.REPORT_UNSHARED,
            actor_type=ActorType.CLINICIAN,
            actor_id=updated_by,
            patient_id=report.patient_id,
            entity_type="PatientReport",
            entity_id=report.id,
        )
    if changed:
        record_event(
            db,
            event_type=AuditEventType.REPORT_UPDATED,
            actor_type=ActorType.CLINICIAN,
            actor_id=updated_by,
            patient_id=report.patient_id,
            entity_type="PatientReport",
            entity_id=report.id,
            event_metadata={"fields_updated": changed},
        )
    db.commit()
    db.refresh(report)
    return report


def remove(db: Session, report_id: uuid.UUID, removed_by: uuid.UUID) -> None:
    report = get_report(db, report_id)
    report.removed_at = datetime.now(timezone.utc)
    report.removed_by = removed_by
    report.data = b""  # the document itself is gone; the record of it stays
    report.shared_with_patient = False
    record_event(
        db,
        event_type=AuditEventType.REPORT_REMOVED,
        actor_type=ActorType.CLINICIAN,
        actor_id=removed_by,
        patient_id=report.patient_id,
        entity_type="PatientReport",
        entity_id=report.id,
    )
    db.commit()
