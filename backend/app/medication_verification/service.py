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
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.ai.provider import ExtractionProviderError, RawImageIdentificationResponse, get_llm_provider
from app.allergies import service as allergies_service
from app.audit.models import ActorType, AuditEventType
from app.auth.provider import AuthError, get_auth_provider
from app.core.config import get_settings
from app.audit.service import record_event
from app.encounters.models import Encounter, EncounterStatus
from app.instructions import service as instructions_service
from app.instructions.models import CareInstruction, ClinicalStatus, InstructionStatus, InstructionType
from app.medication_verification.models import (
    AdministrationEvent,
    IdentificationMethod,
    NotGivenReason,
    VerificationResult,
)
from app.medication_verification.schemas import CheckResult, ConfirmedProductCandidate
from app.patients import service as patients_service
from app.patients.models import AdmissionStatus, Patient
from app.patients.service import PatientNotFoundError
from app.reference.drug_interactions import DrugInteraction, find_interaction
from app.reference.medication_products import (
    MedicationProduct,
    formulations_for_drug_family,
    lookup_medication_product,
)


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


class AdministrationReasonRequiredError(Exception):
    """Raised by administer() when an as-needed (PRN) dose is confirmed
    without a documented indication. A scheduled dose's justification is its
    schedule; a PRN dose has none unless someone records it, and without it
    nobody can later judge whether it worked or whether the patient is being
    dosed too often."""


class AlreadyResolvedError(Exception):
    """Raised when a verification already has an outcome — given or not given.
    Each verification resolves exactly once."""


class CoSignRequiredError(Exception):
    """Raised by administer() when the identified product is high-alert
    (see identified_high_alert) and no co-signer credentials were provided
    at all."""


class CoSignAuthenticationError(Exception):
    """Raised by administer() when co-signer credentials were provided but
    don't authenticate — never distinguishes "wrong password" from "no such
    user," same generic-failure principle as the main login endpoint."""


class CoSignSamePersonError(Exception):
    """Raised by administer() when the co-signer is the same person as the
    administering clinician — an independent double-check requires a
    genuinely different second person, not the same session re-entering
    their own credentials."""


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


# Below this length, a documented allergen is matched by exact equality only,
# never as a substring. Plain substring matching in both directions meant a
# stray one- or two-character allergy entry blocked unrelated drugs outright —
# "o" blocked Metoprolol, "in" blocked Lisinopril — presenting a typo as an
# ALLERGY ALERT the nurse had no way to distinguish from a real one. Short
# real allergens (e.g. "ASA") still match their own name exactly, so nothing
# genuine is silently dropped; only the substring behaviour is withdrawn where
# it cannot be meaningful.
_MIN_ALLERGEN_SUBSTRING_LENGTH = 4


def _allergen_matches(allergen: str, product_base_name: str) -> bool:
    normalized = allergen.strip().lower()
    if not normalized:
        return False
    if len(normalized) < _MIN_ALLERGEN_SUBSTRING_LENGTH or len(product_base_name) < _MIN_ALLERGEN_SUBSTRING_LENGTH:
        return normalized == product_base_name
    # Either direction: "Metoprolol" documented vs "Metoprolol Succinate ER"
    # scanned, and "metoprolol tartrate" documented vs "Metoprolol" scanned.
    return normalized in product_base_name or product_base_name in normalized


def _check_allergy(db: Session, patient_id: uuid.UUID, product: MedicationProduct) -> CheckResult:
    """Cross-references the scanned/confirmed product against the patient's
    documented allergy list (app/allergies) — checked independently of, and
    with priority over, every other check below. A match always forces
    BLOCKED regardless of what dose/route/formulation/time say, because a
    correctly-dosed dangerous allergen is not a safer outcome than an
    incorrectly-dosed safe one. See
    US_HOSPITAL_MARKET_STANDARDS_GAP_ANALYSIS.md item 2 — this is the single
    most basic medication-safety check a hospital system is expected to have,
    and previously didn't exist in this codebase at all.

    Free-text substring match on the base drug name only (no drug-class/
    cross-reactivity ontology) — same prototype-scale precedent as
    _drug_family_matches immediately below."""
    allergies = allergies_service.list_allergies(db, patient_id)
    product_base = product.medication_name.split()[0].strip().lower()
    match = next(
        (allergy for allergy in allergies if _allergen_matches(allergy.allergen, product_base)),
        None,
    )
    if match is not None:
        detail = f"ALLERGY ALERT: patient has a documented allergy to {match.allergen}"
        detail += f" ({match.reaction})." if match.reaction else "."
        return CheckResult(passed=False, detail=detail)
    return CheckResult(passed=True, detail="No documented allergy to this medication.")


# Routes that "nil by mouth" actually restricts. An NPO patient can still
# receive IV, subcutaneous or topical medication — blocking those would be
# clinically wrong and would train staff to click past the warning.
_ORAL_ROUTES = {"oral", "po", "by mouth", "sublingual", "enteral"}


def _check_nil_by_mouth(db: Session, patient_id: uuid.UUID, product: MedicationProduct) -> CheckResult:
    """Is this patient nil by mouth, and is this an oral medication?

    Before surgery a patient is kept NPO and oral doses are deliberately held —
    but the order remains ACTIVE and every other check still passes, so the
    engine previously returned VERIFIED for a dose that must not be given. The
    same shape of gap as the discharged patient, and clinically more dangerous:
    a held anticoagulant is one of the commonest pre-operative instructions
    there is, and Warfarin is already in this catalogue.

    Deliberately route-aware: NPO restricts what goes through the gut, not what
    goes into a vein."""
    encounter = (
        db.query(Encounter)
        .filter(Encounter.patient_id == patient_id, Encounter.status == EncounterStatus.OPEN)
        .order_by(Encounter.admission_date.desc())
        .first()
    )
    if encounter is None or encounter.nil_by_mouth_from is None:
        return CheckResult(passed=True, detail="Patient is not nil by mouth.")

    npo_from = encounter.nil_by_mouth_from
    if npo_from.tzinfo is None:
        npo_from = npo_from.replace(tzinfo=timezone.utc)
    if datetime.now(timezone.utc) < npo_from:
        return CheckResult(
            passed=True,
            detail=f"Nil by mouth begins at {npo_from.astimezone(ZoneInfo(get_settings().hospital_timezone)).strftime('%H:%M')}.",
        )

    if product.route.strip().lower() not in _ORAL_ROUTES:
        return CheckResult(
            passed=True,
            detail=f"Patient is nil by mouth, but this is given by {product.route} — not restricted.",
        )

    procedure = f" ahead of {encounter.planned_procedure}" if encounter.planned_procedure else ""
    return CheckResult(
        passed=False,
        detail=f"Patient is nil by mouth{procedure} — oral medication must be held.",
    )


def _check_drug_interactions(
    db: Session, patient_id: uuid.UUID, product: MedicationProduct, exclude_instruction_id: uuid.UUID
) -> tuple[CheckResult, str | None]:
    """Cross-references the scanned product against the patient's OTHER
    active medications for known dangerous drug-drug interactions (see
    app/reference/drug_interactions.py). Only meaningful within the main
    "found a single matching active order" path in _resolve_and_compare —
    every other branch there already lands on BLOCKED/REVIEW_REQUIRED for
    unrelated reasons, so this is deliberately not threaded into those (an
    interaction check can only ever make an outcome more restrictive, never
    less, so it adds nothing on a path that's already non-administrable).

    Returns (check, severity) — severity is None when nothing was found,
    "MODERATE", or "SEVERE" (see DrugInteraction.severity). A SEVERE match
    is treated exactly like an allergy match (forces BLOCKED); MODERATE
    forces WARNING, requiring the same "Acknowledge & Confirm" step a WARNING
    already requires — never silently ignored, never treated as absolute."""
    other_instructions = [
        i
        for i in _find_medication_instructions(db, patient_id)
        if i.clinical_status == ClinicalStatus.ACTIVE and i.id != exclude_instruction_id
    ]

    worst: DrugInteraction | None = None
    worst_other_name: str | None = None
    for instruction in other_instructions:
        other_name = instruction.current_version.extraction.normalized_facts.get("medication_name")
        interaction = find_interaction(product.medication_name, other_name)
        if interaction is None:
            continue
        if worst is None or (interaction.severity == "SEVERE" and worst.severity != "SEVERE"):
            worst = interaction
            worst_other_name = other_name

    if worst is None:
        return (
            CheckResult(passed=True, detail="No known interactions with this patient's other active medications."),
            None,
        )

    return (
        CheckResult(
            passed=False,
            detail=f"{worst.severity.title()} interaction with {worst_other_name}: {worst.description}",
        ),
        worst.severity,
    )


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
    """Returns (check, is_ambiguous). Ambiguous means the order never stated a
    formulation/release signal AND the scanned drug actually has more than one
    formulation that could be confused — a data-quality gap, never treated the
    same as an actually-detected contradiction (see MODULE_2_DESIGN_REPORT.md
    section 4's CareInstruction caveat).

    That second condition matters more than it sounds. Requiring every order
    to state a release type made three of the five catalog drugs
    (Lisinopril, Metformin, Warfarin) permanently un-VERIFIABLE — they have no
    salt-form or release qualifier in their name, so a perfectly correct,
    perfectly matching scan still landed on REVIEW_REQUIRED, where the
    confirm-administration button doesn't even render. Since most real drug
    names carry no such qualifier, that would send the majority of scans to
    clinician review for a distinction that doesn't exist for those drugs —
    and an alert that fires on correct work is how alert fatigue starts, which
    is itself a patient-safety problem.

    So the question asked here is not "did the order state a formulation?" but
    "could this scan be confused with a DIFFERENT formulation of the same
    drug?" — which formulations_for_drug_family() answers exactly, because the
    catalog is a closed world (an unrecognized barcode never reaches this
    check at all). The check still fires in full for Metoprolol, where
    Succinate ER vs Tartrate is a genuine and dangerous distinction; it stops
    firing where there is nothing to distinguish."""
    lowered = (order_medication_name or "").lower()
    signal = next((keyword for keyword in _FORMULATION_KEYWORDS if keyword in lowered), None)

    if signal is None:
        known_formulations = formulations_for_drug_family(product.medication_name)
        if len(known_formulations) == 1:
            return (
                CheckResult(
                    passed=True,
                    detail=(
                        f"Order does not specify a formulation, but {product.medication_name.split()[0]} is stocked "
                        f"in only one form ({product.formulation}) — nothing to confuse it with."
                    ),
                ),
                False,
            )
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


_PRN_MARKERS = ("as needed", "prn", "when required")


def _order_is_prn(order_facts: dict, raw_order_text: str | None = None) -> bool:
    """Is this an as-needed order rather than a scheduled one?

    Checks the extracted frequency/timing AND the clinician's original order
    text, because the structured fields alone are not reliable here: asked to
    extract "every 6 hours as needed for pain", the production model returns
    frequency="every 6 hours", timing=None and drops "as needed" altogether.
    Reading only the structured fields meant PRN was never detected outside
    the test double — a feature that passed its tests precisely because the
    mock had been taught to emit the shape the code expected.

    Checking the raw text is safe in the false-positive direction: "as
    needed"/"PRN" are specific phrases that do not appear in a scheduled
    order, so this does not add friction to ordinary doses. A structured
    `prn` flag on MedicationFacts would be cleaner still, but that changes
    the extraction schema and the fact-preservation diff, so it is a separate
    piece of work rather than a fix smuggled in here.

    Deliberately does NOT feed the time check: a PRN dose has no scheduled
    time to be early or late for, and _check_time already passes when no
    time-of-day keyword is present."""
    text = " ".join(
        [
            str(order_facts.get("frequency") or ""),
            str(order_facts.get("timing") or ""),
            raw_order_text or "",
        ]
    ).lower()
    return any(marker in text for marker in _PRN_MARKERS)


def _check_time(order_facts: dict, now: datetime) -> CheckResult:
    """"In the morning" is a wall-clock instruction, so it has to be compared
    against the HOSPITAL's wall clock, not the server's UTC offset.

    This previously compared _TIME_OF_DAY_KEYWORDS (08:00, 14:00, …) directly
    against datetime.now(timezone.utc).hour, which is only correct in a UTC±0
    hospital. In Hyderabad (UTC+5:30) — where this prototype's own demo
    patients and Telugu/Hindi support point — an 8am dose given at exactly 8am
    was reported as 5.5 hours outside its window. Every morning medication,
    every day, warning on correct work. The timezone now comes from
    HOSPITAL_TIMEZONE and is named in the message, so a misconfiguration is
    visible at the bedside instead of silently mistimed."""
    text = f"{order_facts.get('timing') or ''} {order_facts.get('frequency') or ''}".lower()
    scheduled = next((t for keyword, t in _TIME_OF_DAY_KEYWORDS.items() if keyword in text), None)

    if scheduled is None:
        return CheckResult(
            passed=True,
            detail="No specific administration time documented — time check skipped (prototype configuration).",
        )

    hospital_tz = get_settings().hospital_timezone
    local_now = now.astimezone(ZoneInfo(hospital_tz))

    scheduled_minutes = scheduled.hour * 60 + scheduled.minute
    now_minutes = local_now.hour * 60 + local_now.minute
    diff = abs(now_minutes - scheduled_minutes)
    diff = min(diff, 24 * 60 - diff)  # wrap around midnight

    if diff <= _TIME_TOLERANCE_MINUTES:
        return CheckResult(
            passed=True,
            detail=(
                f"Within {_TIME_TOLERANCE_MINUTES} minutes of the scheduled "
                f"{scheduled.strftime('%H:%M')} {hospital_tz} (prototype configuration)."
            ),
        )
    return CheckResult(
        passed=False,
        detail=(
            f"Outside the configured {_TIME_TOLERANCE_MINUTES}-minute window around "
            f"{scheduled.strftime('%H:%M')} {hospital_tz} — it is currently "
            f"{local_now.strftime('%H:%M')} there (prototype configuration)."
        ),
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
    order_is_prn: bool = False,
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
        identified_high_alert=product.high_alert if product else False,
        order_is_prn=order_is_prn,
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
    # Before anything else: is this patient still admitted? Discharge does not
    # stop their orders (they stay ACTIVE so the record of what was prescribed
    # survives), so without this check every order of a discharged patient
    # still verified normally and could be administered — with nothing on the
    # nurse's screen to hint the patient had left. Blocked rather than
    # flagged for review because giving a drug to someone the record says has
    # gone home is not a judgement call; if the discharge itself is wrong,
    # the fix is to correct the record, not to push past this.
    if patient.admission_status != AdmissionStatus.ACTIVE:
        admission_check = CheckResult(
            passed=False,
            detail=(
                f"{patient.first_name} {patient.last_name} is recorded as "
                f"{patient.admission_status.value}, not currently admitted."
            ),
        )
        return _persist_and_audit(
            db,
            patient.id,
            None,
            barcode,
            identification_method,
            VerificationResult.BLOCKED,
            ["PATIENT_NOT_ADMITTED"],
            {"admission": admission_check},
            performed_by,
            product=product,
        )

    # Checked first, unconditionally — an allergy match forces BLOCKED no
    # matter what the order-matching logic below concludes (see
    # _check_allergy's docstring).
    allergy_check = _check_allergy(db, patient.id, product)
    npo_check = _check_nil_by_mouth(db, patient.id, product)

    instructions = _find_medication_instructions(db, patient.id)
    same_drug = [
        i for i in instructions if _drug_family_matches(i.current_version.extraction.normalized_facts.get("medication_name"), product.medication_name)
    ]

    if not same_drug:
        reasons = ["NO_MATCHING_ORDER"] if allergy_check.passed else ["ALLERGY_ALERT", "NO_MATCHING_ORDER"]
        return _persist_and_audit(
            db, patient.id, None, barcode, identification_method, VerificationResult.BLOCKED, reasons,
            {"allergy": allergy_check}, performed_by,
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
            "allergy": allergy_check,
            "order_status": CheckResult(
                passed=False,
                detail=(
                    f"Previous {stopped_facts.get('dose_value')}{stopped_facts.get('dose_unit')} order is "
                    f"{stopped.clinical_status.value}. There is no active order for this medication."
                ),
            ),
        }
        reasons = ["STOPPED_ORDER_SCANNED"] if allergy_check.passed else ["ALLERGY_ALERT", "STOPPED_ORDER_SCANNED"]
        return _persist_and_audit(
            db, patient.id, stopped.id, barcode, identification_method, VerificationResult.BLOCKED, reasons, checks, performed_by,
            product=product,
        )

    if non_active_dose_match is not None and not active_dose_matches:
        stopped_facts = non_active_dose_match.current_version.extraction.normalized_facts
        active_facts = active[0].current_version.extraction.normalized_facts
        checks = {
            "patient": patient_check,
            "medication": medication_check,
            "allergy": allergy_check,
            "order_status": CheckResult(
                passed=False,
                detail=(
                    f"Previous {stopped_facts.get('dose_value')}{stopped_facts.get('dose_unit')} order is "
                    f"{non_active_dose_match.clinical_status.value}. Current active order is "
                    f"{active_facts.get('dose_value')}{active_facts.get('dose_unit')}."
                ),
            ),
        }
        reasons = ["STOPPED_ORDER_SCANNED"] if allergy_check.passed else ["ALLERGY_ALERT", "STOPPED_ORDER_SCANNED"]
        return _persist_and_audit(
            db,
            patient.id,
            non_active_dose_match.id,
            barcode,
            identification_method,
            VerificationResult.BLOCKED,
            reasons,
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
            "allergy": allergy_check,
            "order_status": CheckResult(
                passed=False,
                detail=(
                    f"Multiple active orders for {product.medication_name} {product.strength_value}"
                    f"{product.strength_unit} were found for this patient — cannot determine which order this "
                    "administration is for. Please have a clinician review."
                ),
            ),
        }
        # An allergy match escalates this from "ambiguous, needs review" to a
        # hard block — never let order-ambiguity soften an allergy alert.
        result = VerificationResult.REVIEW_REQUIRED if allergy_check.passed else VerificationResult.BLOCKED
        reasons = ["MULTIPLE_ACTIVE_ORDERS"] if allergy_check.passed else ["ALLERGY_ALERT", "MULTIPLE_ACTIVE_ORDERS"]
        return _persist_and_audit(
            db, patient.id, None, barcode, identification_method, result, reasons, checks, performed_by,
            product=product,
        )

    order = active_dose_matches[0] if len(active_dose_matches) == 1 else active[0]
    order_facts = order.current_version.extraction.normalized_facts

    checks: dict[str, CheckResult] = {
        "patient": patient_check,
        "medication": medication_check,
        "allergy": allergy_check,
        "nil_by_mouth": npo_check,
    }
    reasons: list[str] = [] if allergy_check.passed else ["ALLERGY_ALERT"]
    if not npo_check.passed:
        reasons.append("PATIENT_NIL_BY_MOUTH")

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

    interaction_check, interaction_severity = _check_drug_interactions(db, patient.id, product, order.id)
    checks["interactions"] = interaction_check
    if interaction_severity == "SEVERE":
        reasons.append("SEVERE_DRUG_INTERACTION")
    elif interaction_severity == "MODERATE":
        reasons.append("MODERATE_DRUG_INTERACTION")

    hard_failed = not dose_check.passed or not route_check.passed or (not formulation_check.passed and not formulation_ambiguous)

    if not allergy_check.passed:
        # An allergy match overrides everything else — even a perfectly
        # dosed, perfectly timed administration of a drug the patient is
        # allergic to is never VERIFIED.
        result = VerificationResult.BLOCKED
    elif not npo_check.passed:
        # Held pre-operatively. Blocked rather than warned: the nurse's next
        # step is to document it as HELD, which the not-given flow supports.
        result = VerificationResult.BLOCKED
    elif interaction_severity == "SEVERE":
        # Treated exactly like an allergy match — an absolute block, never
        # softened by an otherwise-clean dose/route/time match.
        result = VerificationResult.BLOCKED
    elif hard_failed:
        result = VerificationResult.BLOCKED
    elif formulation_ambiguous:
        result = VerificationResult.REVIEW_REQUIRED
    elif interaction_severity == "MODERATE" or not time_check.passed:
        result = VerificationResult.WARNING
    else:
        result = VerificationResult.VERIFIED

    return _persist_and_audit(
        db,
        patient.id,
        order.id,
        barcode,
        identification_method,
        result,
        reasons,
        checks,
        performed_by,
        product=product,
        order_is_prn=_order_is_prn(order_facts, order.current_version.raw_text),
    )


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

    # A new allergy could have been documented for this patient between the
    # original scan and this confirm — re-check it fresh, same as every
    # other fact here, rather than trusting the allergy_check computed at
    # verify() time.
    allergy_check = _check_allergy(db, event.patient_id, product)
    if not allergy_check.passed:
        raise OrderChangedError(allergy_check.detail)

    # Same reasoning for a newly-started interacting medication — only a
    # SEVERE interaction re-blocks here; a MODERATE one only ever required a
    # WARNING acknowledgment, which the nurse already gave at verify() time.
    _, interaction_severity = _check_drug_interactions(db, event.patient_id, product, instruction.id)
    if interaction_severity == "SEVERE":
        raise OrderChangedError("A newly-documented medication now has a severe interaction with this drug.")

    dose_check = _check_dose(order_facts, product)
    route_check = _check_route(order_facts, product)
    formulation_check, formulation_ambiguous = _check_formulation(order_facts.get("medication_name"), product)

    if not dose_check.passed or not route_check.passed or (not formulation_check.passed and not formulation_ambiguous):
        raise OrderChangedError("The order's details have changed since this medication was verified.")


def administer(
    db: Session,
    verification_id: uuid.UUID,
    administered_by: uuid.UUID,
    co_signer_email: str | None = None,
    co_signer_password: str | None = None,
    administration_reason: str | None = None,
) -> AdministrationEvent:
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
    # A verification resolves exactly once. Without this a dose already
    # documented as refused or held could still be marked given, producing a
    # row that claims both — the precise contradiction not_given_reason exists
    # to prevent.
    if event.not_given_reason is not None:
        raise AlreadyResolvedError(str(verification_id))

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

    # An as-needed dose needs its indication recorded — see
    # AdministrationReasonRequiredError. Checked before the co-sign gate so a
    # nurse isn't asked to fetch a second clinician only to then be told the
    # reason field was missing.
    if event.order_is_prn:
        if not administration_reason or not administration_reason.strip():
            raise AdministrationReasonRequiredError(
                "This is an as-needed (PRN) medication — record why it is being given."
            )
        event.administration_reason = administration_reason.strip()

    # ISMP's recommended mitigation for high-alert medications (insulin,
    # anticoagulants, opioids, etc. — see medication_products.py's
    # high_alert flag): require a second, independently-authenticated
    # clinician before recording the dose. Deliberately full credentials
    # (email + password), not just picking a name from a list — a real
    # independent check requires the second person to actually be present
    # and authenticate themselves, not merely be named by the first.
    if event.identified_high_alert:
        if not co_signer_email or not co_signer_password:
            raise CoSignRequiredError("This is a high-alert medication and requires a second clinician's co-sign.")
        try:
            co_signer = get_auth_provider(db).authenticate(co_signer_email, co_signer_password)
        except AuthError as exc:
            raise CoSignAuthenticationError("Co-signer credentials could not be verified.") from exc
        if co_signer.id == str(administered_by):
            raise CoSignSamePersonError("The co-signer must be a different clinician from the one administering.")
        event.co_signed_by = uuid.UUID(co_signer.id)

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


def record_not_given(
    db: Session,
    verification_id: uuid.UUID,
    recorded_by: uuid.UUID,
    reason: NotGivenReason,
    note: str | None = None,
) -> AdministrationEvent:
    """Records that a verified dose was deliberately NOT given.

    This is documentation of care, not an error path. Without it the only way
    a dose could fail to happen was silently: the row stayed VERIFIED with
    administered_at NULL, indistinguishable from a nurse who was interrupted
    and never came back. Nobody could see that a decision had been made, let
    alone what it was.

    Deliberately permitted for any verification that has not already resolved,
    including BLOCKED and REVIEW_REQUIRED ones — "the scan was blocked, so I
    held the dose and told the doctor" is exactly the sort of thing that
    should be on the record, and refusing to let a nurse document it would
    push that decision off the system entirely."""
    event = db.query(AdministrationEvent).filter(AdministrationEvent.id == verification_id).with_for_update().first()
    if event is None:
        raise VerificationNotFoundError(str(verification_id))
    if event.administered_at is not None or event.not_given_reason is not None:
        raise AlreadyResolvedError(str(verification_id))

    event.not_given_reason = reason
    event.not_given_note = note.strip() if note and note.strip() else None
    event.not_given_by = recorded_by
    event.not_given_at = datetime.now(timezone.utc)

    record_event(
        db,
        event_type=AuditEventType.ADMINISTRATION_NOT_GIVEN,
        actor_type=ActorType.CLINICIAN,
        actor_id=recorded_by,
        patient_id=event.patient_id,
        entity_type="AdministrationEvent",
        entity_id=event.id,
        event_metadata={"reason": reason.value},
    )
    db.commit()
    db.refresh(event)
    return event


def list_administration_history(db: Session, patient_id: uuid.UUID, limit: int = 100) -> list[AdministrationEvent]:
    """Every bedside verification for a patient, newest first — the record
    that previously existed only as write-only rows.

    Includes blocked and review-required attempts on purpose: "a wrong drug
    was caught at this patient's bedside" is exactly the kind of thing the
    next shift and any reviewer need to see, and hiding it would leave the
    safety net invisible."""
    return (
        db.query(AdministrationEvent)
        .filter(AdministrationEvent.patient_id == patient_id)
        .order_by(AdministrationEvent.created_at.desc())
        .limit(limit)
        .all()
    )
