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
from app.wearables.service import end_assignments_for_patient


def update_patient(db: Session, patient_id: uuid.UUID, data: PatientUpdate, updated_by: uuid.UUID) -> Patient:
    """The single business operation behind PATCH /patients/{id}. Discharging a
    patient (admission_status -> DISCHARGED) is not just a field update — it
    must also immediately invalidate every active patient-facing care link and
    end any wearable monitoring, in the same transaction, so neither outlives
    the discharge that should have killed it:

        mark patient DISCHARGED
              |
        revoke active care tokens
              |
        end active wearable assignments
              |
        write audit events
              |
        single commit

    For every other field update, this is equivalent to a plain field update —
    the cascade below only fires when admission_status is being set to
    DISCHARGED.

    Module 3 note: unassigning on discharge is automatic rather than requiring
    staff confirmation. The failure being prevented is a device that still
    believes it is monitoring a discharged patient — it would keep sending
    events, and the backend would keep resolving them to someone who has gone
    home. Making it automatic mirrors the care-token cascade directly above it,
    and the assignment row is retained (only closed out), so history stays
    resolvable."""
    patient = _update_patient_record(db, patient_id, data, updated_by, commit=False)

    if data.admission_status == AdmissionStatus.DISCHARGED:
        revoke_all_tokens_for_patient(db, patient_id, commit=False)
        end_assignments_for_patient(db, patient_id, commit=False)

    db.commit()
    db.refresh(patient)
    return patient
