"""Application-level orchestration for business operations that span more than
one bounded-context service. Routers call into this layer rather than owning
cross-module rules themselves, and no domain service imports another domain
service in the opposite direction — patients/service.py knows nothing about
patient_access, and patient_access/service.py's existing dependency on
patients/service.py (for get_patient) stays one-directional. This module sits
above both, so it can safely depend on either without creating a cycle.
"""

import uuid

from sqlalchemy.orm import Session

from app.patient_access.service import revoke_all_tokens_for_patient
from app.patients.models import AdmissionStatus, Patient
from app.patients.schemas import PatientUpdate
from app.patients.service import update_patient as _update_patient_record


def update_patient(db: Session, patient_id: uuid.UUID, data: PatientUpdate, updated_by: uuid.UUID) -> Patient:
    """The single business operation behind PATCH /patients/{id}. Discharging a
    patient (admission_status -> DISCHARGED) is not just a field update — it
    must also immediately invalidate every active patient-facing care link, in
    the same transaction, so a link never outlives the discharge that should
    have killed it:

        mark patient DISCHARGED
              |
        revoke active care tokens
              |
        write audit events
              |
        single commit

    For every other field update, this is equivalent to a plain field update —
    the cascade below only fires when admission_status is being set to
    DISCHARGED."""
    patient = _update_patient_record(db, patient_id, data, updated_by, commit=False)

    if data.admission_status == AdmissionStatus.DISCHARGED:
        revoke_all_tokens_for_patient(db, patient_id, commit=False)

    db.commit()
    db.refresh(patient)
    return patient
