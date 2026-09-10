import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.auth.provider import AuthenticatedUser
from app.core.db import get_db
from app.medication_verification import service
from app.medication_verification.schemas import (
    AdministerRequest,
    ImageIdentificationResponse,
    MedicationProductRead,
    VerifyConfirmedRequest,
    VerifyRequest,
    VerifyResponse,
)
from app.medication_verification.service import (
    AlreadyAdministeredError,
    DuplicateAdministrationError,
    OrderChangedError,
    VerificationNotAdministrableError,
    VerificationNotFoundError,
)
from app.reference.medication_products import lookup_medication_product

router = APIRouter(tags=["medication-verification"])


def _to_verify_response(event, product: MedicationProductRead | None) -> VerifyResponse:
    return VerifyResponse(
        id=event.id,
        result=event.verification_result,
        identification_method=event.identification_method,
        checks=event.checks,
        mismatch_reasons=event.mismatch_reasons,
        care_instruction_id=event.care_instruction_id,
        product=product,
        created_at=event.created_at,
    )


@router.get("/medication-products/{barcode}", response_model=MedicationProductRead)
def get_medication_product(
    barcode: str,
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> MedicationProductRead:
    product = lookup_medication_product(barcode)
    if product is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unrecognized medication barcode")
    return MedicationProductRead(**product.__dict__)


@router.post("/medication-verification/verify", response_model=VerifyResponse)
def verify(
    payload: VerifyRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> VerifyResponse:
    event = service.verify(db, payload.patient_code, payload.barcode, performed_by=uuid.UUID(current_user.id))
    if event is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Patient not found")
    product = lookup_medication_product(payload.barcode)
    return _to_verify_response(event, MedicationProductRead(**product.__dict__) if product else None)


@router.post("/medication-verification/administer")
def administer(
    payload: AdministerRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> dict:
    try:
        event = service.administer(db, payload.verification_id, administered_by=uuid.UUID(current_user.id))
    except VerificationNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Verification not found") from exc
    except VerificationNotAdministrableError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Cannot confirm administration for a {exc} result",
        ) from exc
    except AlreadyAdministeredError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Already administered") from exc
    except DuplicateAdministrationError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except OrderChangedError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    return {"id": str(event.id), "administered_at": event.administered_at.isoformat()}


@router.post("/medication-verification/identify-from-image", response_model=ImageIdentificationResponse)
async def identify_from_image(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    file: UploadFile = File(...),
    patient_id: Annotated[uuid.UUID | None, Form()] = None,
) -> ImageIdentificationResponse:
    """Barcode-failure fallback, step one. Returns an UNCONFIRMED candidate
    only — see identify_from_image()'s docstring in service.py. The nurse
    must review this and call verify-confirmed themselves; nothing here is
    ever treated as a verification result. patient_id is optional (the
    frontend has usually already resolved the patient by this step, but
    identification itself doesn't require it) and is only used to attribute
    the MEDICATION_SCAN_FAILED/MEDICATION_IMAGE_IDENTIFIED audit events to
    the right patient's timeline."""
    image_bytes = await file.read()
    result = service.identify_from_image(
        db, image_bytes, file.content_type or "image/jpeg", performed_by=uuid.UUID(current_user.id), patient_id=patient_id
    )
    return ImageIdentificationResponse(
        medication_name=result.medication_name,
        strength_value=result.strength_value,
        strength_unit=result.strength_unit,
        formulation=result.formulation,
        route=result.route,
        confidence=result.confidence,
    )


@router.post("/medication-verification/verify-confirmed", response_model=VerifyResponse)
def verify_confirmed(
    payload: VerifyConfirmedRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> VerifyResponse:
    """Barcode-failure fallback, step two — only nurse-confirmed fields
    reach this endpoint (see verify_confirmed()'s docstring in service.py)."""
    event = service.verify_confirmed(db, payload.patient_code, payload.candidate, performed_by=uuid.UUID(current_user.id))
    if event is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Patient not found")
    confirmed_product = MedicationProductRead(
        barcode=event.product_barcode,
        medication_name=payload.candidate.medication_name,
        strength_value=payload.candidate.strength_value,
        strength_unit=payload.candidate.strength_unit,
        formulation=payload.candidate.formulation,
        route=payload.candidate.route,
    )
    return _to_verify_response(event, confirmed_product)
