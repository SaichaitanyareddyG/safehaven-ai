import re
import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile, status
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.auth.provider import AuthenticatedUser
from app.core.db import get_db
from app.patients.service import PatientNotFoundError
from app.reports import service
from app.reports.models import ReportCategory
from app.reports.schemas import ReportListResponse, ReportRead, ReportUpdate

router = APIRouter(tags=["reports"])

_EXTENSION = {"application/pdf": "pdf", "image/png": "png", "image/jpeg": "jpg"}


def file_response(report) -> Response:
    """The document, never cached, never re-interpreted by the browser."""
    safe_title = re.sub(r"[^A-Za-z0-9 _-]", "", report.title).strip()[:60] or "report"
    return Response(
        content=report.data,
        media_type=report.content_type,
        headers={
            "Content-Disposition": f'inline; filename="{safe_title}.{_EXTENSION[report.content_type]}"',
            "Cache-Control": "no-store, private",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.post("/patients/{patient_id}/reports", response_model=ReportRead, status_code=status.HTTP_201_CREATED)
async def upload_report(
    patient_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    file: Annotated[UploadFile, File()],
    title: Annotated[str, Form(max_length=200)],
    category: Annotated[ReportCategory, Form()] = ReportCategory.OTHER,
    report_date: Annotated[date | None, Form()] = None,
    shared_with_patient: Annotated[bool, Form()] = False,
) -> ReportRead:
    # Read one byte past the limit: enough to know it is too big, never more.
    data = await file.read(service.MAX_REPORT_BYTES + 1)
    try:
        return service.upload(
            db,
            patient_id,
            uuid.UUID(current_user.id),
            data=data,
            title=title,
            category=category,
            report_date=report_date,
            shared_with_patient=shared_with_patient,
        )
    except PatientNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Patient not found") from exc
    except service.ReportError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


@router.get("/patients/{patient_id}/reports", response_model=ReportListResponse)
def list_reports(
    patient_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> ReportListResponse:
    try:
        return ReportListResponse(results=service.list_reports(db, patient_id))
    except PatientNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Patient not found") from exc


@router.get("/reports/{report_id}/file")
def open_report(
    report_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> Response:
    try:
        report = service.get_report(db, report_id, with_data=True)
    except service.ReportNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report not found") from exc
    service.record_view(db, report, staff_id=uuid.UUID(current_user.id))
    return file_response(report)


@router.patch("/reports/{report_id}", response_model=ReportRead)
def update_report(
    report_id: uuid.UUID,
    payload: ReportUpdate,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> ReportRead:
    """Rename, re-date, or share with / hide from the patient."""
    try:
        return service.update(
            db,
            report_id,
            uuid.UUID(current_user.id),
            title=payload.title,
            category=payload.category,
            report_date=payload.report_date,
            shared_with_patient=payload.shared_with_patient,
            fields_set=payload.model_fields_set,
        )
    except service.ReportNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report not found") from exc


@router.delete("/reports/{report_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_report(
    report_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> None:
    try:
        service.remove(db, report_id, uuid.UUID(current_user.id))
    except service.ReportNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report not found") from exc
