"""The deterministic medication-verification engine. No LLM anywhere in this
module's actual safety decision — every result is a rule-based comparison
against structured data already on file (see MODULE_2_DESIGN_REPORT.md
section 8). Vision/OCR (identify_from_image) is a text-extraction aid only,
used solely to help a nurse fill in a candidate product when a barcode can't
be read — its output always requires nurse confirmation and then flows
through the exact same deterministic comparison as a normal scan.

Nothing here is ever auto-approved on uncertainty: an unresolved barcode, an
order with no comparable structured fields, an unspecified formulation, or
multiple equally-plausible active orders all land on REVIEW_REQUIRED or
BLOCKED, never VERIFIED."""

import uuid
from datetime import datetime, time as time_of_day, timedelta, timezone

from sqlalchemy.orm import Session

from app.ai.provider import ExtractionProviderError, RawImageIdentificationResponse, get_llm_provider
from app.audit.models import ActorType, AuditEventType
from app.audit.service import record_event
from app.instructions import service as instructions_service
from app.instructions.models import CareInstruction, ClinicalStatus, InstructionStatus, InstructionType
from app.medication_verification.models import AdministrationEvent, IdentificationMethod, VerificationResult
from app.medication_verification.schemas import CheckResult, ConfirmedProductCandidate
from app.patients import service as patients_service
from app.patients.models import Patient
from app.patients.service import PatientNotFoundError
from app.reference.medication_products import MedicationProduct, lookup_medication_product


class VerificationNotFoundError(Exception):
    pass


class VerificationNotAdministrableError(Exception):
    """Raised when trying to confirm administration against a BLOCKED or
    REVIEW_REQUIRED verification — only VERIFIED or WARNING (after
    acknowledgment) may ever be administered. There is no override path in
    this build (see MODULE_2_DESIGN_REPORT.md section 17 — deferred)."""


class AlreadyAdministeredError(Exception):
    pass


class OrderChangedError(Exception):
    """Raised by administer() when a fresh revalidation, run right before
    marking a dose as given, disagrees with the result computed at scan
    time — the order was stopped, its facts changed, or it no longer exists.
    See MODULE_2_EDGE_CASE_REVIEW.md sections 5 and 8."""


class DuplicateAdministrationError(Exception):
    """Raised by administer() when the same order already has another
    administered AdministrationEvent within the duplicate-detection window.
    See MODULE_2_EDGE_CASE_REVIEW.md section 6."""


_FORMULATION_KEYWORDS = [
    "succinate",
    "tartrate",
    "extended-release",
    "extended release",
    "immediate-release",
    "immediate release",
    "sustained-release",
    "sustained release",
]

_TIME_OF_DAY_KEYWORDS: dict[str, time_of_day] = {
    "morning": time_of_day(8, 0),
    "afternoon": time_of_day(14, 0),
    "evening": time_of_day(20, 0),
    "night": time_of_day(22, 0),
}
# Prototype configuration only — not a universal clinical administration
# window standard. See MODULE_2_DESIGN_REPORT.md section 8.
_TIME_TOLERANCE_MINUTES = 60

# How recently the SAME order can have already been administered before a
# new confirmation is treated as a likely duplicate rather than the next
# legitimate scheduled dose. Deliberately wider than the time-of-day
# tolerance above (a real next dose is typically hours away) — prototype
# configuration, not a clinical scheduling standard. See
# MODULE_2_EDGE_CASE_REVIEW.md section 6.
_DUPLICATE_ADMINISTRATION_WINDOW_MINUTES = _TIME_TOLERANCE_MINUTES * 2

# Placeholder "barcode" recorded on an image-identified AdministrationEvent —
# there is no real barcode in that path (see IdentificationMethod.IMAGE).
_IMAGE_IDENTIFIED_PLACEHOLDER = "IMAGE-CONFIRMED"


def _find_medication_instructions(db: Session, patient_id: uuid.UUID) -> list[CareInstruction]:
    """All APPROVED MEDICATION-type instructions for a patient, at ANY
    clinical_status — STOPPED/COMPLETED ones are needed to build the
    "previous order is stopped" message rather than just saying "not found"."""
    _, instructions = instructions_service.list_patient_instructions(
        db, patient_id, status=InstructionStatus.APPROVED, limit=1000, offset=0, clinical_status=None
    )
    result = []
    for instruction in instructions:
        version = instruction.current_version
        if version is None or version.extraction is None:
            continue
        if version.extraction.instruction_type != InstructionType.MEDICATION:
            continue
        result.append(instruction)
    return result


def _drug_family_matches(order_medication_name: str | None, product_medication_name: str) -> bool:
    """Loose "same drug" check — does the product's base drug name (its first
    word, e.g. "Metoprolol" out of "Metoprolol Succinate ER") appear anywhere
    in whatever free text the clinician's order used? This is deliberately
    permissive (it's only step one of several checks) — see _check_formulation
    for the check that actually distinguishes salt form/release mechanism."""
    if not order_medication_name:
        return False
    product_base = product_medication_name.split()[0].lower()
    return product_base in order_medication_name.lower()


def _check_dose(order_facts: dict, product: MedicationProduct) -> CheckResult:
    order_value = order_facts.get("dose_value")
    order_unit = (order_facts.get("dose_unit") or "").strip().lower()
    if order_value is None or not order_unit:
        return CheckResult(passed=False, detail="Order does not have a structured dose to compare against.")
    if float(order_value) == product.strength_value and order_unit == product.strength_unit.strip().lower():
        return CheckResult(passed=True, detail=f"{product.strength_value}{product.strength_unit} matches the order.")
    return CheckResult(
        passed=False,
        detail=f"Order specifies {order_value}{order_unit}, scanned product is {product.strength_value}{product.strength_unit}.",
    )


def _check_route(order_facts: dict, product: MedicationProduct) -> CheckResult:
    order_route = (order_facts.get("route") or "").strip().lower()
    if not order_route:
        return CheckResult(passed=False, detail="Order does not have a documented route to compare against.")
    if order_route == product.route.strip().lower():
        return CheckResult(passed=True, detail=f"Route matches ({product.route}).")
    return CheckResult(
        passed=False, detail=f"Order specifies route '{order_route}', scanned product route is '{product.route}'."
    )


def _check_formulation(order_medication_name: str | None, product: MedicationProduct) -> tuple[CheckResult, bool]:
    """Returns (check, is_ambiguous). Ambiguous means the order simply never
    stated a formulation/release signal — that is a data-quality gap, never
    treated the same as an actually-detected contradiction (see
    MODULE_2_DESIGN_REPORT.md section 4's CareInstruction caveat)."""
    lowered = (order_medication_name or "").lower()
    signal = next((keyword for keyword in _FORMULATION_KEYWORDS if keyword in lowered), None)

    if signal is None:
        return (
            CheckResult(
                passed=False,
                detail="Order does not specify a formulation/release type — cannot confirm formulation match.",
            ),
            True,
        )

    product_identity = f"{product.medication_name} {product.formulation}".lower()
    if signal in product_identity:
        return CheckResult(passed=True, detail=f"Formulation consistent ({signal})."), False

    return (
        CheckResult(
            passed=False,
            detail=f"Order specifies '{signal}', but the scanned product is {product.medication_name} ({product.formulation}).",
        ),
        False,
    )


def _check_time(order_facts: dict, now: datetime) -> CheckResult:
    text = f"{order_facts.get('timing') or ''} {order_facts.get('frequency') or ''}".lower()
    scheduled = next((t for keyword, t in _TIME_OF_DAY_KEYWORDS.items() if keyword in text), None)

    if scheduled is None:
        return CheckResult(
            passed=True,
            detail="No specific administration time documented — time check skipped (prototype configuration).",
        )

    scheduled_minutes = scheduled.hour * 60 + scheduled.minute
    now_minutes = now.hour * 60 + now.minute
    diff = abs(now_minutes - scheduled_minutes)
    diff = min(diff, 24 * 60 - diff)  # wrap around midnight

    if diff <= _TIME_TOLERANCE_MINUTES:
        return CheckResult(
            passed=True,
            detail=f"Within {_TIME_TOLERANCE_MINUTES} minutes of the scheduled {scheduled.strftime('%H:%M')} (prototype configuration).",
        )
    return CheckResult(
        passed=False,
        detail=f"Outside the configured {_TIME_TOLERANCE_MINUTES}-minute window around {scheduled.strftime('%H:%M')} (prototype configuration).",
    )


def _persist_and_audit(
    db: Session,
    patient_id: uuid.UUID,
    care_instruction_id: uuid.UUID | None,
    barcode: str,
    identification_method: IdentificationMethod,
    result: VerificationResult,
    reasons: list[str],
    checks: dict[str, CheckResult],
    performed_by: uuid.UUID,
    product: MedicationProduct | None = None,
) -> AdministrationEvent:
    event = AdministrationEvent(
        patient_id=patient_id,
        care_instruction_id=care_instruction_id,
        product_barcode=barcode,
        identification_method=identification_method,
        verification_result=result,
        mismatch_reasons=reasons,
        checks={key: value.model_dump() for key, value in checks.items()},
        performed_by=performed_by,
        identified_medication_name=product.medication_name if product else None,
        identified_strength_value=product.strength_value if product else None,
        identified_strength_unit=product.strength_unit if product else None,
        identified_formulation=product.formulation if product else None,
        identified_route=product.route if product else None,
    )
    db.add(event)
    db.flush()

    audit_type = (
        AuditEventType.MEDICATION_VERIFIED
        if result in (VerificationResult.VERIFIED, VerificationResult.WARNING)
        else AuditEventType.MEDICATION_MISMATCH
    )
    record_event(
        db,
        event_type=audit_type,
        actor_type=ActorType.CLINICIAN,
        actor_id=performed_by,
        patient_id=patient_id,
        entity_type="AdministrationEvent",
        entity_id=event.id,
        event_metadata={"result": result.value, "reasons": reasons, "identification_method": identification_method.value},
    )
    db.commit()
    db.refresh(event)
    return event


def _resolve_and_compare(
    db: Session,
    patient: Patient,
    product: MedicationProduct,
    barcode: str,
    identification_method: IdentificationMethod,
    performed_by: uuid.UUID,
) -> AdministrationEvent:
    """Shared by both the barcode path (verify) and the image-confirmed path
    (verify_confirmed) — once a product identity is in hand, by whatever
    means, the comparison against the patient's orders is identical."""
    instructions = _find_medication_instructions(db, patient.id)
    same_drug = [
        i for i in instructions if _drug_family_matches(i.current_version.extraction.normalized_facts.get("medication_name"), product.medication_name)
    ]

    if not same_drug:
        return _persist_and_audit(
            db, patient.id, None, barcode, identification_method, VerificationResult.BLOCKED, ["NO_MATCHING_ORDER"], {}, performed_by,
            product=product,
        )

    active = [i for i in same_drug if i.clinical_status == ClinicalStatus.ACTIVE]
    non_active = [i for i in same_drug if i.clinical_status in (ClinicalStatus.STOPPED, ClinicalStatus.COMPLETED)]

    # Does the scanned product's dose specifically match an old STOPPED/
    # COMPLETED order rather than (or in addition to) the current active
    # one(s)? Checked before falling through to a generic dose-mismatch
    # comparison, because "the nurse is holding the exact product that was
    # discontinued" deserves the specific, more informative message below —
    # the strongest demo scenario in MODULE_2_DESIGN_REPORT.md.
    non_active_dose_match = next((i for i in non_active if _check_dose(i.current_version.extraction.normalized_facts, product).passed), None)
    active_dose_matches = [i for i in active if _check_dose(i.current_version.extraction.normalized_facts, product).passed]

    patient_check = CheckResult(passed=True, detail=f"Wristband matches {patient.first_name} {patient.last_name} ({patient.patient_code}).")
    medication_check = CheckResult(passed=True, detail=f"{product.medication_name} matches this patient's medication history.")

    if not active:
        stopped = non_active_dose_match or same_drug[0]
        stopped_facts = stopped.current_version.extraction.normalized_facts
        checks = {
            "patient": patient_check,
            "medication": medication_check,
            "order_status": CheckResult(
                passed=False,
                detail=(
                    f"Previous {stopped_facts.get('dose_value')}{stopped_facts.get('dose_unit')} order is "
                    f"{stopped.clinical_status.value}. There is no active order for this medication."
                ),
            ),
        }
        return _persist_and_audit(
            db, patient.id, stopped.id, barcode, identification_method, VerificationResult.BLOCKED, ["STOPPED_ORDER_SCANNED"], checks, performed_by,
            product=product,
        )

    if non_active_dose_match is not None and not active_dose_matches:
        stopped_facts = non_active_dose_match.current_version.extraction.normalized_facts
        active_facts = active[0].current_version.extraction.normalized_facts
        checks = {
            "patient": patient_check,
            "medication": medication_check,
            "order_status": CheckResult(
                passed=False,
                detail=(
                    f"Previous {stopped_facts.get('dose_value')}{stopped_facts.get('dose_unit')} order is "
                    f"{non_active_dose_match.clinical_status.value}. Current active order is "
                    f"{active_facts.get('dose_value')}{active_facts.get('dose_unit')}."
                ),
            ),
        }
        return _persist_and_audit(
            db,
            patient.id,
            non_active_dose_match.id,
            barcode,
            identification_method,
            VerificationResult.BLOCKED,
            ["STOPPED_ORDER_SCANNED"],
            checks,
            performed_by,
            product=product,
        )

    # Multiple ACTIVE orders for the same drug family, all matching the
    # scanned dose — genuinely ambiguous which one this administration is
    # for. Never silently pick one (see MODULE_2_IMPLEMENTATION_PLAN.md
    # section 7 — this is the fix that plan called for).
    if len(active_dose_matches) > 1:
        checks = {
            "patient": patient_check,
            "medication": medication_check,
            "order_status": CheckResult(
                passed=False,
                detail=(
                    f"Multiple active orders for {product.medication_name} {product.strength_value}"
                    f"{product.strength_unit} were found for this patient — cannot determine which order this "
                    "administration is for. Please have a clinician review."
                ),
            ),
        }
        return _persist_and_audit(
            db, patient.id, None, barcode, identification_method, VerificationResult.REVIEW_REQUIRED, ["MULTIPLE_ACTIVE_ORDERS"], checks, performed_by,
            product=product,
        )

    order = active_dose_matches[0] if len(active_dose_matches) == 1 else active[0]
    order_facts = order.current_version.extraction.normalized_facts

    checks: dict[str, CheckResult] = {"patient": patient_check, "medication": medication_check}
    reasons: list[str] = []

    dose_check = _check_dose(order_facts, product)
    checks["dose"] = dose_check
    if not dose_check.passed:
        reasons.append("DOSE_MISMATCH")

    formulation_check, formulation_ambiguous = _check_formulation(order_facts.get("medication_name"), product)
    checks["formulation"] = formulation_check
    if not formulation_check.passed:
        reasons.append("FORMULATION_UNSPECIFIED" if formulation_ambiguous else "FORMULATION_MISMATCH")

    route_check = _check_route(order_facts, product)
    checks["route"] = route_check
    if not route_check.passed:
        reasons.append("ROUTE_MISMATCH")

    time_check = _check_time(order_facts, datetime.now(timezone.utc))
    checks["time"] = time_check
    if not time_check.passed:
        reasons.append("TIME_OUTSIDE_WINDOW")

    hard_failed = not dose_check.passed or not route_check.passed or (not formulation_check.passed and not formulation_ambiguous)

    if hard_failed:
        result = VerificationResult.BLOCKED
    elif formulation_ambiguous:
        result = VerificationResult.REVIEW_REQUIRED
    elif not time_check.passed:
        result = VerificationResult.WARNING
    else:
        result = VerificationResult.VERIFIED

    return _persist_and_audit(db, patient.id, order.id, barcode, identification_method, result, reasons, checks, performed_by, product=product)


def verify(db: Session, patient_code: str, barcode: str, performed_by: uuid.UUID) -> AdministrationEvent | None:
    """Returns None only when the wristband itself doesn't resolve to any
    patient — there is no patient_id to attach a persisted AdministrationEvent
    to in that case (see the model's docstring); the attempt is still
    recorded on the generic audit trail with patient_id=None."""
    try:
        patient = patients_service.get_patient_by_code(db, patient_code)
    except PatientNotFoundError:
        record_event(
            db,
            event_type=AuditEventType.PATIENT_SCANNED,
            actor_type=ActorType.CLINICIAN,
            actor_id=performed_by,
            patient_id=None,
            event_metadata={"patient_code": patient_code, "resolved": False},
        )
        db.commit()
        return None

    record_event(
        db,
        event_type=AuditEventType.PATIENT_SCANNED,
        actor_type=ActorType.CLINICIAN,
        actor_id=performed_by,
        patient_id=patient.id,
        event_metadata={"patient_code": patient_code, "resolved": True},
    )

    product = lookup_medication_product(barcode)
    record_event(
        db,
        event_type=AuditEventType.MEDICATION_SCANNED,
        actor_type=ActorType.CLINICIAN,
        actor_id=performed_by,
        patient_id=patient.id,
        event_metadata={"barcode": barcode, "resolved": product is not None},
    )

    if product is None:
        return _persist_and_audit(
            db, patient.id, None, barcode, IdentificationMethod.BARCODE, VerificationResult.REVIEW_REQUIRED, ["PRODUCT_NOT_FOUND"], {}, performed_by
        )

    return _resolve_and_compare(db, patient, product, barcode, IdentificationMethod.BARCODE, performed_by)


def identify_from_image(
    db: Session, image_bytes: bytes, mime_type: str, performed_by: uuid.UUID, patient_id: uuid.UUID | None = None
) -> RawImageIdentificationResponse:
    """Barcode-failure fallback, step one: read the label photo and return an
    UNCONFIRMED candidate. Never persists an AdministrationEvent — nothing
    has been verified or even confirmed yet. See verify_confirmed() for step
    two, which only runs after the nurse explicitly confirms these fields."""
    record_event(
        db,
        event_type=AuditEventType.MEDICATION_SCAN_FAILED,
        actor_type=ActorType.CLINICIAN,
        actor_id=performed_by,
        patient_id=patient_id,
    )

    provider = get_llm_provider()
    try:
        result = provider.identify_medication_from_image(image_bytes, mime_type)
    except ExtractionProviderError:
        result = RawImageIdentificationResponse(
            medication_name=None,
            strength_value=None,
            strength_unit=None,
            formulation=None,
            route=None,
            confidence="low",
            metadata=None,  # type: ignore[arg-type]
        )

    record_event(
        db,
        event_type=AuditEventType.MEDICATION_IMAGE_IDENTIFIED,
        actor_type=ActorType.CLINICIAN,
        actor_id=performed_by,
        patient_id=patient_id,
        event_metadata={
            "medication_name": result.medication_name,
            "confidence": result.confidence,
        },
    )
    db.commit()
    return result


def verify_confirmed(
    db: Session, patient_code: str, candidate: ConfirmedProductCandidate, performed_by: uuid.UUID
) -> AdministrationEvent | None:
    """Barcode-failure fallback, step two: the nurse has reviewed and
    confirmed (possibly corrected) the candidate from identify_from_image(),
    or entered it manually — either way, ONLY nurse-confirmed fields ever
    reach this function. From here on the confirmed fields are treated as a
    normal MedicationProduct and go through the exact same deterministic
    engine as a barcode scan (_resolve_and_compare) — the only difference is
    identification_method=IMAGE, which the UI must always disclose."""
    try:
        patient = patients_service.get_patient_by_code(db, patient_code)
    except PatientNotFoundError:
        record_event(
            db,
            event_type=AuditEventType.PATIENT_SCANNED,
            actor_type=ActorType.CLINICIAN,
            actor_id=performed_by,
            patient_id=None,
            event_metadata={"patient_code": patient_code, "resolved": False},
        )
        db.commit()
        return None

    record_event(
        db,
        event_type=AuditEventType.MEDICATION_MANUALLY_CONFIRMED,
        actor_type=ActorType.CLINICIAN,
        actor_id=performed_by,
        patient_id=patient.id,
        event_metadata={"medication_name": candidate.medication_name},
    )

    product = MedicationProduct(
        barcode=_IMAGE_IDENTIFIED_PLACEHOLDER,
        medication_name=candidate.medication_name,
        strength_value=candidate.strength_value,
        strength_unit=candidate.strength_unit,
        formulation=candidate.formulation,
        route=candidate.route,
    )
    return _resolve_and_compare(db, patient, product, _IMAGE_IDENTIFIED_PLACEHOLDER, IdentificationMethod.IMAGE, performed_by)


def _revalidate_order_still_matches(db: Session, event: AdministrationEvent) -> None:
    """Re-runs the hard checks (order still exists, still ACTIVE, dose/route/
    formulation still consistent) against a FRESH read of the order, using
    the product identity persisted at verify() time — never the possibly-
    stale in-memory result computed then. Raises OrderChangedError if
    anything has moved since the original verification. See
    MODULE_2_EDGE_CASE_REVIEW.md sections 5 and 8.

    VERIFIED/WARNING always have a care_instruction_id (see
    _resolve_and_compare — that branch is the only source of those two
    results, and it always sets one), so this never needs to handle a null
    care_instruction_id itself."""
    instruction = db.get(CareInstruction, event.care_instruction_id)
    if instruction is None or instruction.current_version is None or instruction.current_version.extraction is None:
        raise OrderChangedError("The original order no longer exists.")

    if instruction.clinical_status != ClinicalStatus.ACTIVE:
        raise OrderChangedError(
            f"The order is no longer active (now {instruction.clinical_status.value if instruction.clinical_status else 'unknown'})."
        )

    product = MedicationProduct(
        barcode=event.product_barcode,
        medication_name=event.identified_medication_name or "",
        strength_value=event.identified_strength_value or 0.0,
        strength_unit=event.identified_strength_unit or "",
        formulation=event.identified_formulation or "",
        route=event.identified_route or "",
    )
    order_facts = instruction.current_version.extraction.normalized_facts

    dose_check = _check_dose(order_facts, product)
    route_check = _check_route(order_facts, product)
    formulation_check, formulation_ambiguous = _check_formulation(order_facts.get("medication_name"), product)

    if not dose_check.passed or not route_check.passed or (not formulation_check.passed and not formulation_ambiguous):
        raise OrderChangedError("The order's details have changed since this medication was verified.")


def administer(db: Session, verification_id: uuid.UUID, administered_by: uuid.UUID) -> AdministrationEvent:
    # Row lock: makes the read-check-write below safe against two concurrent
    # confirm requests for the SAME verification_id (see
    # MODULE_2_EDGE_CASE_REVIEW.md section 7) — the second request blocks
    # here until the first transaction commits, then correctly sees
    # administered_at already set.
    event = db.query(AdministrationEvent).filter(AdministrationEvent.id == verification_id).with_for_update().first()
    if event is None:
        raise VerificationNotFoundError(str(verification_id))
    if event.verification_result not in (VerificationResult.VERIFIED, VerificationResult.WARNING):
        raise VerificationNotAdministrableError(event.verification_result.value)
    if event.administered_at is not None:
        raise AlreadyAdministeredError(str(verification_id))

    # Duplicate-administration check: has this SAME order already been given
    # via a different verification, recently? See section 6 — deliberately a
    # simple recency window, not a full scheduled-dose/eMAR model.
    if event.care_instruction_id is not None:
        window_start = datetime.now(timezone.utc) - timedelta(minutes=_DUPLICATE_ADMINISTRATION_WINDOW_MINUTES)
        duplicate = (
            db.query(AdministrationEvent)
            .filter(
                AdministrationEvent.care_instruction_id == event.care_instruction_id,
                AdministrationEvent.id != event.id,
                AdministrationEvent.administered_at.isnot(None),
                AdministrationEvent.administered_at >= window_start,
            )
            .first()
        )
        if duplicate is not None:
            raise DuplicateAdministrationError(
                f"Already administered at {duplicate.administered_at.isoformat()} by a separate confirmation."
            )

    # Revalidation: the order may have been stopped or changed since the
    # nurse's original scan — never trust that stale result at the moment
    # administration is actually recorded.
    _revalidate_order_still_matches(db, event)

    event.administered_by = administered_by
    event.administered_at = datetime.now(timezone.utc)

    record_event(
        db,
        event_type=AuditEventType.ADMINISTRATION_CONFIRMED,
        actor_type=ActorType.CLINICIAN,
        actor_id=administered_by,
        patient_id=event.patient_id,
        entity_type="AdministrationEvent",
        entity_id=event.id,
        event_metadata={"result": event.verification_result.value},
    )
    db.commit()
    db.refresh(event)
    return event
