"""Module 2 — medication administration verification. Every result here is a
deterministic comparison (see app/medication_verification/service.py) against
real CareInstruction/StructuredExtraction rows created through the normal
Module 1 API — no separate order model, no LLM in the decision path."""

import uuid as uuid_module

MEDICATION_SUCCINATE_25 = "Take Metoprolol Succinate ER 25 mg orally twice daily."
MEDICATION_SUCCINATE_50 = "Take Metoprolol Succinate ER 50 mg orally twice daily."
MEDICATION_PLAIN = "Take Metoprolol 25 mg orally twice daily."
MEDICATION_LISINOPRIL = "Take Lisinopril 10 mg orally once daily."

BARCODE_SUCCINATE_25 = "MED-METOPROLOL-SUCCINATE-25"
BARCODE_SUCCINATE_50 = "MED-METOPROLOL-SUCCINATE-50"
BARCODE_TARTRATE_25 = "MED-METOPROLOL-TARTRATE-25"
BARCODE_LISINOPRIL_10 = "MED-LISINOPRIL-10"


def _register_and_login(client, email="nurse@example.com", password="supersecret123"):
    client.post("/auth/register", json={"email": email, "password": password, "full_name": "Test Nurse"})
    login_resp = client.post("/auth/login", json={"email": email, "password": password})
    token = login_resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _create_active_patient(client, headers, **overrides) -> dict:
    payload = {
        "first_name": "John",
        "last_name": "Doe",
        "date_of_birth": "1950-01-01",
        "preferred_language": "ENGLISH",
    }
    payload.update(overrides)
    return client.post("/patients", json=payload, headers=headers).json()


def _create_analyze_generate_approve(client, headers, patient_id, text) -> dict:
    created = client.post(f"/patients/{patient_id}/instructions", json={"text": text}, headers=headers).json()
    client.post(f"/instructions/{created['id']}/analyze", headers=headers)
    generated = client.post(f"/instructions/{created['id']}/generate", headers=headers).json()
    assert generated["status"] == "READY_FOR_APPROVAL", generated
    approved = client.post(f"/instructions/{created['id']}/approve", headers=headers).json()
    assert approved["status"] == "APPROVED"
    return created


def _verify(client, headers, patient_code, barcode):
    return client.post(
        "/medication-verification/verify", json={"patient_code": patient_code, "barcode": barcode}, headers=headers
    )


def _add_allergy(client, headers, patient_id, allergen):
    resp = client.post(f"/patients/{patient_id}/allergies", json={"allergen": allergen}, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()


# ---------------------------------------------------------------------------
# Core demo scenarios (MODULE_2_DESIGN_REPORT.md section 15)
# ---------------------------------------------------------------------------


def test_scenario_1_correct_patient_and_medication_is_verified(client):
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)
    _create_analyze_generate_approve(client, headers, patient["id"], MEDICATION_SUCCINATE_25)

    resp = _verify(client, headers, patient["patient_code"], BARCODE_SUCCINATE_25)

    assert resp.status_code == 200
    body = resp.json()
    assert body["result"] == "VERIFIED"
    assert all(check["passed"] for check in body["checks"].values())
    assert body["mismatch_reasons"] == []


def test_scenario_2_no_matching_order_for_scanned_medication_is_blocked(client):
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)
    _create_analyze_generate_approve(client, headers, patient["id"], MEDICATION_LISINOPRIL)

    # This patient only has a Lisinopril order — scanning a Metoprolol
    # product for them is exactly the "wrong medication for this patient" case.
    resp = _verify(client, headers, patient["patient_code"], BARCODE_SUCCINATE_25)

    assert resp.status_code == 200
    body = resp.json()
    assert body["result"] == "BLOCKED"
    assert "NO_MATCHING_ORDER" in body["mismatch_reasons"]


def test_scenario_3_correct_medication_wrong_dose_is_blocked(client):
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)
    _create_analyze_generate_approve(client, headers, patient["id"], MEDICATION_SUCCINATE_25)

    resp = _verify(client, headers, patient["patient_code"], BARCODE_SUCCINATE_50)

    assert resp.status_code == 200
    body = resp.json()
    assert body["result"] == "BLOCKED"
    assert "DOSE_MISMATCH" in body["mismatch_reasons"]
    assert body["checks"]["dose"]["passed"] is False


def test_scenario_4_same_drug_wrong_formulation_is_blocked(client):
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)
    _create_analyze_generate_approve(client, headers, patient["id"], MEDICATION_SUCCINATE_25)

    resp = _verify(client, headers, patient["patient_code"], BARCODE_TARTRATE_25)

    assert resp.status_code == 200
    body = resp.json()
    assert body["result"] == "BLOCKED"
    assert "FORMULATION_MISMATCH" in body["mismatch_reasons"]
    assert body["checks"]["dose"]["passed"] is True  # same dose/route — only formulation differs
    assert body["checks"]["formulation"]["passed"] is False


def test_scenario_5_stopped_order_scanned_instead_of_active_is_blocked(client):
    """The strongest demo scenario: a barcode that is a perfectly real,
    readable product — it just isn't this patient's *current* order."""
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)
    old_order = _create_analyze_generate_approve(client, headers, patient["id"], MEDICATION_SUCCINATE_25)
    client.patch(f"/instructions/{old_order['id']}/clinical-status", json={"status": "STOPPED"}, headers=headers)
    _create_analyze_generate_approve(client, headers, patient["id"], MEDICATION_SUCCINATE_50)

    resp = _verify(client, headers, patient["patient_code"], BARCODE_SUCCINATE_25)

    assert resp.status_code == 200
    body = resp.json()
    assert body["result"] == "BLOCKED"
    assert "STOPPED_ORDER_SCANNED" in body["mismatch_reasons"]
    assert body["care_instruction_id"] == old_order["id"]
    assert "STOPPED" in body["checks"]["order_status"]["detail"]
    assert "50" in body["checks"]["order_status"]["detail"]


def test_scenario_6_unrecognized_barcode_is_review_required(client):
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)
    _create_analyze_generate_approve(client, headers, patient["id"], MEDICATION_SUCCINATE_25)

    resp = _verify(client, headers, patient["patient_code"], "NOT-A-REAL-BARCODE")

    assert resp.status_code == 200
    body = resp.json()
    assert body["result"] == "REVIEW_REQUIRED"
    assert "PRODUCT_NOT_FOUND" in body["mismatch_reasons"]
    assert body["product"] is None


def test_scenario_formulation_unspecified_is_review_required_not_blocked(client):
    """An order that never documented a formulation is a data gap, not a
    detected mismatch — must never be auto-approved, but must also never be
    conflated with an actual contradiction."""
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)
    _create_analyze_generate_approve(client, headers, patient["id"], MEDICATION_PLAIN)

    resp = _verify(client, headers, patient["patient_code"], BARCODE_SUCCINATE_25)

    assert resp.status_code == 200
    body = resp.json()
    assert body["result"] == "REVIEW_REQUIRED"
    assert "FORMULATION_UNSPECIFIED" in body["mismatch_reasons"]


def test_unknown_patient_wristband_returns_404(client):
    headers = _register_and_login(client)
    resp = _verify(client, headers, "P9999999", BARCODE_SUCCINATE_25)
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Administration confirmation
# ---------------------------------------------------------------------------


def test_administer_after_verified_result_succeeds(client):
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)
    _create_analyze_generate_approve(client, headers, patient["id"], MEDICATION_SUCCINATE_25)
    verification = _verify(client, headers, patient["patient_code"], BARCODE_SUCCINATE_25).json()

    resp = client.post(
        "/medication-verification/administer", json={"verification_id": verification["id"]}, headers=headers
    )

    assert resp.status_code == 200
    assert resp.json()["administered_at"] is not None


def test_administer_after_blocked_result_is_rejected(client):
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)
    _create_analyze_generate_approve(client, headers, patient["id"], MEDICATION_SUCCINATE_25)
    verification = _verify(client, headers, patient["patient_code"], BARCODE_SUCCINATE_50).json()
    assert verification["result"] == "BLOCKED"

    resp = client.post(
        "/medication-verification/administer", json={"verification_id": verification["id"]}, headers=headers
    )

    assert resp.status_code == 422


def test_administer_twice_is_rejected(client):
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)
    _create_analyze_generate_approve(client, headers, patient["id"], MEDICATION_SUCCINATE_25)
    verification = _verify(client, headers, patient["patient_code"], BARCODE_SUCCINATE_25).json()

    first = client.post(
        "/medication-verification/administer", json={"verification_id": verification["id"]}, headers=headers
    )
    second = client.post(
        "/medication-verification/administer", json={"verification_id": verification["id"]}, headers=headers
    )

    assert first.status_code == 200
    assert second.status_code == 409


# ---------------------------------------------------------------------------
# Audit trail
# ---------------------------------------------------------------------------


def test_verification_and_administration_are_audited(client):
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)
    _create_analyze_generate_approve(client, headers, patient["id"], MEDICATION_SUCCINATE_25)
    verification = _verify(client, headers, patient["patient_code"], BARCODE_SUCCINATE_25).json()
    client.post("/medication-verification/administer", json={"verification_id": verification["id"]}, headers=headers)

    audit_resp = client.get(f"/patients/{patient['id']}/audit", headers=headers)
    event_types = [e["event_type"] for e in audit_resp.json()["results"]]

    assert "PATIENT_SCANNED" in event_types
    assert "MEDICATION_SCANNED" in event_types
    assert "MEDICATION_VERIFIED" in event_types
    assert "ADMINISTRATION_CONFIRMED" in event_types


# ---------------------------------------------------------------------------
# Authorization
# ---------------------------------------------------------------------------


def test_verify_requires_authentication(client):
    resp = client.post("/medication-verification/verify", json={"patient_code": "P1001", "barcode": BARCODE_SUCCINATE_25})
    assert resp.status_code == 401


def test_patient_care_plan_token_cannot_call_verify(client):
    """A raw care-access token is not a JWT and was never meant to be used as
    one — confirms the boundary MODULE_2_DESIGN_REPORT.md section 14 relies on."""
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)
    care_link = client.post(f"/patients/{patient['id']}/care-access-tokens", headers=headers).json()

    resp = client.post(
        "/medication-verification/verify",
        json={"patient_code": patient["patient_code"], "barcode": BARCODE_SUCCINATE_25},
        headers={"Authorization": f"Bearer {care_link['token']}"},
    )
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Patient-by-code lookup (wristband scan resolution)
# ---------------------------------------------------------------------------


def test_get_patient_by_code(client):
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)

    resp = client.get(f"/patients/by-code/{patient['patient_code']}", headers=headers)

    assert resp.status_code == 200
    assert resp.json()["id"] == patient["id"]


def test_get_patient_by_unknown_code_404s(client):
    headers = _register_and_login(client)
    resp = client.get("/patients/by-code/P9999999", headers=headers)
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Medication product lookup
# ---------------------------------------------------------------------------


def test_get_medication_product_by_barcode(client):
    headers = _register_and_login(client)
    resp = client.get(f"/medication-products/{BARCODE_LISINOPRIL_10}", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["medication_name"] == "Lisinopril"
    assert body["strength_value"] == 10.0


def test_get_unknown_medication_product_404s(client):
    headers = _register_and_login(client)
    resp = client.get("/medication-products/NOT-A-REAL-BARCODE", headers=headers)
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Multiple active orders for the same drug (MODULE_2_IMPLEMENTATION_PLAN.md §7)
# ---------------------------------------------------------------------------


def test_multiple_active_orders_matching_scanned_dose_is_review_required(client):
    """Two ACTIVE orders for the same drug at the same dose (e.g. a duplicate
    entry) must never be silently resolved by picking one — this is exactly
    the ambiguity the engine must never guess through."""
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)
    _create_analyze_generate_approve(client, headers, patient["id"], MEDICATION_SUCCINATE_25)
    _create_analyze_generate_approve(client, headers, patient["id"], MEDICATION_SUCCINATE_25)

    resp = _verify(client, headers, patient["patient_code"], BARCODE_SUCCINATE_25)

    assert resp.status_code == 200
    body = resp.json()
    assert body["result"] == "REVIEW_REQUIRED"
    assert "MULTIPLE_ACTIVE_ORDERS" in body["mismatch_reasons"]
    assert body["care_instruction_id"] is None


def test_two_different_dose_active_orders_still_resolves_the_matching_one(client):
    """Two ACTIVE orders for the same drug at DIFFERENT doses is not
    ambiguous once a specific product is scanned — exactly one of them
    matches the scanned dose, so verification proceeds normally against
    that one rather than the first-created order."""
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)
    _create_analyze_generate_approve(client, headers, patient["id"], MEDICATION_SUCCINATE_50)
    _create_analyze_generate_approve(client, headers, patient["id"], MEDICATION_SUCCINATE_25)

    resp = _verify(client, headers, patient["patient_code"], BARCODE_SUCCINATE_25)

    assert resp.status_code == 200
    body = resp.json()
    assert body["result"] == "VERIFIED"


# ---------------------------------------------------------------------------
# Image fallback (MODULE_2_IMPLEMENTATION_PLAN.md §8)
# ---------------------------------------------------------------------------


def test_identify_from_image_returns_unconfirmed_candidate(client):
    headers = _register_and_login(client)

    resp = client.post(
        "/medication-verification/identify-from-image",
        files={"file": ("label.jpg", b"__FIXTURE_IMAGE__:SUCCINATE_25", "image/jpeg")},
        headers=headers,
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["medication_name"] == "Metoprolol Succinate ER"
    assert body["strength_value"] == 25.0
    assert body["confidence"] == "high"


def test_identify_from_image_low_confidence_when_blurry(client):
    headers = _register_and_login(client)

    resp = client.post(
        "/medication-verification/identify-from-image",
        files={"file": ("label.jpg", b"__FIXTURE_IMAGE__:BLURRY", "image/jpeg")},
        headers=headers,
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["confidence"] == "low"
    assert body["strength_value"] is None


def test_identify_from_image_provider_failure_returns_safe_null_result_not_an_error(client):
    """A vision-call failure must never surface as a crash or a false
    identification — it degrades to the same "nothing legible" shape a
    genuinely unreadable label would produce, still requiring nurse review."""
    headers = _register_and_login(client)

    resp = client.post(
        "/medication-verification/identify-from-image",
        files={"file": ("label.jpg", b"__FIXTURE_IMAGE__:PROVIDER_FAILURE", "image/jpeg")},
        headers=headers,
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["medication_name"] is None
    assert body["confidence"] == "low"


def test_identify_from_image_records_scan_failed_and_identified_audit_events(client):
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)

    client.post(
        "/medication-verification/identify-from-image",
        files={"file": ("label.jpg", b"__FIXTURE_IMAGE__:SUCCINATE_25", "image/jpeg")},
        data={"patient_id": patient["id"]},
        headers=headers,
    )

    audit_resp = client.get(f"/patients/{patient['id']}/audit", headers=headers)
    event_types = [e["event_type"] for e in audit_resp.json()["results"]]
    assert "MEDICATION_SCAN_FAILED" in event_types
    assert "MEDICATION_IMAGE_IDENTIFIED" in event_types


def test_verify_confirmed_reaches_verified_for_a_correct_match(client):
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)
    _create_analyze_generate_approve(client, headers, patient["id"], MEDICATION_SUCCINATE_25)

    resp = client.post(
        "/medication-verification/verify-confirmed",
        json={
            "patient_code": patient["patient_code"],
            "candidate": {
                "medication_name": "Metoprolol Succinate ER",
                "strength_value": 25.0,
                "strength_unit": "mg",
                "formulation": "extended-release tablet",
                "route": "oral",
            },
        },
        headers=headers,
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["result"] == "VERIFIED"
    assert body["identification_method"] == "IMAGE"


def test_verify_confirmed_still_blocks_a_real_mismatch(client):
    """Confirming an image-identified candidate does not bypass any check —
    a wrong-dose confirmation is blocked exactly like a wrong-dose scan."""
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)
    _create_analyze_generate_approve(client, headers, patient["id"], MEDICATION_SUCCINATE_25)

    resp = client.post(
        "/medication-verification/verify-confirmed",
        json={
            "patient_code": patient["patient_code"],
            "candidate": {
                "medication_name": "Metoprolol Succinate ER",
                "strength_value": 50.0,
                "strength_unit": "mg",
                "formulation": "extended-release tablet",
                "route": "oral",
            },
        },
        headers=headers,
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["result"] == "BLOCKED"
    assert "DOSE_MISMATCH" in body["mismatch_reasons"]


def test_verify_confirmed_records_manually_confirmed_audit_event(client):
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)
    _create_analyze_generate_approve(client, headers, patient["id"], MEDICATION_SUCCINATE_25)

    client.post(
        "/medication-verification/verify-confirmed",
        json={
            "patient_code": patient["patient_code"],
            "candidate": {
                "medication_name": "Metoprolol Succinate ER",
                "strength_value": 25.0,
                "strength_unit": "mg",
                "formulation": "extended-release tablet",
                "route": "oral",
            },
        },
        headers=headers,
    )

    audit_resp = client.get(f"/patients/{patient['id']}/audit", headers=headers)
    event_types = [e["event_type"] for e in audit_resp.json()["results"]]
    assert "MEDICATION_MANUALLY_CONFIRMED" in event_types
    assert "MEDICATION_VERIFIED" in event_types


def test_verify_confirmed_unknown_patient_404s(client):
    headers = _register_and_login(client)
    resp = client.post(
        "/medication-verification/verify-confirmed",
        json={
            "patient_code": "P9999999",
            "candidate": {
                "medication_name": "Metoprolol Succinate ER",
                "strength_value": 25.0,
                "strength_unit": "mg",
                "formulation": "extended-release tablet",
                "route": "oral",
            },
        },
        headers=headers,
    )
    assert resp.status_code == 404


def test_identify_from_image_requires_authentication(client):
    resp = client.post(
        "/medication-verification/identify-from-image",
        files={"file": ("label.jpg", b"__FIXTURE_IMAGE__:SUCCINATE_25", "image/jpeg")},
    )
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Revalidation, duplicate-administration, and concurrency
# (MODULE_2_EDGE_CASE_REVIEW.md sections 5, 6, 7)
# ---------------------------------------------------------------------------


def test_administer_rejects_when_order_stopped_after_verification(client, db_session):
    """The critical scenario this review exists for: a doctor stops the order
    AFTER the nurse's scan already came back VERIFIED, but BEFORE they press
    Confirm. administer() must catch this, not just trust the stale result."""
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)
    order = _create_analyze_generate_approve(client, headers, patient["id"], MEDICATION_SUCCINATE_25)

    verification = _verify(client, headers, patient["patient_code"], BARCODE_SUCCINATE_25).json()
    assert verification["result"] == "VERIFIED"

    # The doctor stops the order in the moment between scan and confirm.
    client.patch(f"/instructions/{order['id']}/clinical-status", json={"status": "STOPPED"}, headers=headers)

    resp = client.post(
        "/medication-verification/administer", json={"verification_id": verification["id"]}, headers=headers
    )

    assert resp.status_code == 422
    assert "administered_at" not in resp.json() or resp.json().get("administered_at") is None


def test_administer_rejects_when_order_dose_changed_after_verification(client, db_session):
    """Simulates the order's facts being corrected between scan and confirm —
    administer() must re-check against current data, not the scan-time
    snapshot."""
    from app.instructions.models import CareInstruction

    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)
    order = _create_analyze_generate_approve(client, headers, patient["id"], MEDICATION_SUCCINATE_25)

    verification = _verify(client, headers, patient["patient_code"], BARCODE_SUCCINATE_25).json()
    assert verification["result"] == "VERIFIED"

    # Directly mutate the order's facts, simulating a correction landing
    # between the nurse's scan and their Confirm click.
    instruction = db_session.get(CareInstruction, uuid_module.UUID(order["id"]))
    extraction = instruction.current_version.extraction
    extraction.normalized_facts = {**extraction.normalized_facts, "dose_value": 50.0}
    db_session.commit()

    resp = client.post(
        "/medication-verification/administer", json={"verification_id": verification["id"]}, headers=headers
    )

    assert resp.status_code == 422


def test_administer_succeeds_when_nothing_changed(client):
    """Sanity check: revalidation must not reject the ordinary, nothing-
    changed case — only actual changes should ever block confirmation."""
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)
    _create_analyze_generate_approve(client, headers, patient["id"], MEDICATION_SUCCINATE_25)
    verification = _verify(client, headers, patient["patient_code"], BARCODE_SUCCINATE_25).json()

    resp = client.post(
        "/medication-verification/administer", json={"verification_id": verification["id"]}, headers=headers
    )

    assert resp.status_code == 200
    assert resp.json()["administered_at"] is not None


def test_administer_detects_duplicate_administration(client):
    """The same order administered via a second, separate verification
    attempt shortly after the first must be blocked as a likely duplicate,
    not silently recorded a second time."""
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)
    _create_analyze_generate_approve(client, headers, patient["id"], MEDICATION_SUCCINATE_25)

    first_verification = _verify(client, headers, patient["patient_code"], BARCODE_SUCCINATE_25).json()
    first_administer = client.post(
        "/medication-verification/administer", json={"verification_id": first_verification["id"]}, headers=headers
    )
    assert first_administer.status_code == 200

    # A second nurse (or the same one) re-scans and re-verifies the same
    # medication shortly after.
    second_verification = _verify(client, headers, patient["patient_code"], BARCODE_SUCCINATE_25).json()
    assert second_verification["id"] != first_verification["id"]

    second_administer = client.post(
        "/medication-verification/administer", json={"verification_id": second_verification["id"]}, headers=headers
    )

    assert second_administer.status_code == 409


def test_administer_allows_next_dose_outside_duplicate_window(client, db_session):
    """A genuinely later scheduled dose (well outside the duplicate-detection
    window) must not be blocked as if it were a repeat of the earlier one."""
    from datetime import datetime, timedelta, timezone

    from app.medication_verification.models import AdministrationEvent

    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)
    _create_analyze_generate_approve(client, headers, patient["id"], MEDICATION_SUCCINATE_25)

    first_verification = _verify(client, headers, patient["patient_code"], BARCODE_SUCCINATE_25).json()
    first_administer = client.post(
        "/medication-verification/administer", json={"verification_id": first_verification["id"]}, headers=headers
    )
    assert first_administer.status_code == 200

    # Push the first administration's timestamp well outside the duplicate
    # window, simulating that real time has passed since the earlier dose.
    event = db_session.get(AdministrationEvent, uuid_module.UUID(first_verification["id"]))
    event.administered_at = datetime.now(timezone.utc) - timedelta(hours=12)
    db_session.commit()

    second_verification = _verify(client, headers, patient["patient_code"], BARCODE_SUCCINATE_25).json()
    second_administer = client.post(
        "/medication-verification/administer", json={"verification_id": second_verification["id"]}, headers=headers
    )

    assert second_administer.status_code == 200


# ---------------------------------------------------------------------------
# Allergy safety check (US_HOSPITAL_MARKET_STANDARDS_GAP_ANALYSIS.md item 2)
# ---------------------------------------------------------------------------


def test_verify_blocks_when_patient_has_documented_allergy(client):
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)
    _create_analyze_generate_approve(client, headers, patient["id"], MEDICATION_SUCCINATE_25)
    _add_allergy(client, headers, patient["id"], "Metoprolol")

    resp = _verify(client, headers, patient["patient_code"], BARCODE_SUCCINATE_25)

    assert resp.status_code == 200
    body = resp.json()
    assert body["result"] == "BLOCKED"
    assert "ALLERGY_ALERT" in body["mismatch_reasons"]
    assert body["checks"]["allergy"]["passed"] is False
    assert "Metoprolol" in body["checks"]["allergy"]["detail"]


def test_verify_is_unaffected_by_an_unrelated_allergy(client):
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)
    _create_analyze_generate_approve(client, headers, patient["id"], MEDICATION_SUCCINATE_25)
    _add_allergy(client, headers, patient["id"], "Penicillin")

    resp = _verify(client, headers, patient["patient_code"], BARCODE_SUCCINATE_25)

    assert resp.status_code == 200
    body = resp.json()
    assert body["result"] == "VERIFIED"
    assert body["checks"]["allergy"]["passed"] is True


def test_allergy_escalates_ambiguous_multiple_orders_to_blocked(client):
    """Without an allergy, two active same-drug/same-dose orders are only
    REVIEW_REQUIRED (genuinely ambiguous, needs a clinician). An allergy match
    must never be softened by that ambiguity — it stays BLOCKED."""
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)
    _create_analyze_generate_approve(client, headers, patient["id"], MEDICATION_SUCCINATE_25)
    _create_analyze_generate_approve(client, headers, patient["id"], MEDICATION_SUCCINATE_25)
    _add_allergy(client, headers, patient["id"], "Metoprolol")

    resp = _verify(client, headers, patient["patient_code"], BARCODE_SUCCINATE_25)

    assert resp.status_code == 200
    body = resp.json()
    assert body["result"] == "BLOCKED"
    assert "ALLERGY_ALERT" in body["mismatch_reasons"]


def test_administer_rejects_when_allergy_documented_after_verification(client):
    """Mirrors the order-changed-after-verification safety net: a new
    allergy documented between scan and confirm must still stop the dose."""
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)
    _create_analyze_generate_approve(client, headers, patient["id"], MEDICATION_SUCCINATE_25)

    verification = _verify(client, headers, patient["patient_code"], BARCODE_SUCCINATE_25).json()
    assert verification["result"] == "VERIFIED"

    _add_allergy(client, headers, patient["id"], "Metoprolol")

    resp = client.post(
        "/medication-verification/administer", json={"verification_id": verification["id"]}, headers=headers
    )

    assert resp.status_code == 422
    assert "allergy" in resp.json()["detail"].lower()


# ---------------------------------------------------------------------------
# High-alert medication independent co-sign (ISMP's recommended mitigation —
# see app/reference/medication_products.py's high_alert flag and
# US_HOSPITAL_MARKET_STANDARDS_GAP_ANALYSIS.md item 3).
# ---------------------------------------------------------------------------

BARCODE_WARFARIN_5 = "MED-WARFARIN-5"


def test_verify_response_surfaces_high_alert_flag_from_catalog(client):
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)

    warfarin_resp = _verify(client, headers, patient["patient_code"], BARCODE_WARFARIN_5)
    assert warfarin_resp.json()["product"]["high_alert"] is True

    metoprolol_resp = _verify(client, headers, patient["patient_code"], BARCODE_SUCCINATE_25)
    assert metoprolol_resp.json()["product"]["high_alert"] is False


MEDICATION_WARFARIN = "Take Warfarin 5 mg orally once daily."


def _make_high_alert_verified_event(client, headers, patient, db_session=None):
    """A real end-to-end high-alert scan: Warfarin is flagged high_alert in
    the catalog AND is stocked in only one formulation, so a plain order for
    it reaches VERIFIED through the ordinary engine with no test-only
    manipulation. (Before the formulation-ambiguity fix this was impossible —
    Warfarin was permanently REVIEW_REQUIRED — and this helper had to borrow
    Metoprolol's result and flip the flag by hand.)"""
    _create_analyze_generate_approve(client, headers, patient["id"], MEDICATION_WARFARIN)
    verification = _verify(client, headers, patient["patient_code"], BARCODE_WARFARIN_5).json()
    assert verification["result"] == "VERIFIED", verification
    return verification["id"]


def test_administer_high_alert_medication_without_cosign_is_rejected(client, db_session):
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)
    verification_id = _make_high_alert_verified_event(client, headers, patient, db_session)

    resp = client.post(
        "/medication-verification/administer", json={"verification_id": verification_id}, headers=headers
    )

    assert resp.status_code == 422
    assert "co-sign" in resp.json()["detail"].lower()


def test_administer_high_alert_medication_wrong_cosign_password_is_rejected(client, db_session):
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)
    verification_id = _make_high_alert_verified_event(client, headers, patient, db_session)

    resp = client.post(
        "/medication-verification/administer",
        json={
            "verification_id": verification_id,
            "co_signer_email": "nurse@example.com",
            "co_signer_password": "wrong-password",
        },
        headers=headers,
    )

    assert resp.status_code == 422


def test_administer_high_alert_medication_cosign_by_same_person_is_rejected(client, db_session):
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)
    verification_id = _make_high_alert_verified_event(client, headers, patient, db_session)

    resp = client.post(
        "/medication-verification/administer",
        json={
            "verification_id": verification_id,
            "co_signer_email": "nurse@example.com",
            "co_signer_password": "supersecret123",
        },
        headers=headers,
    )

    assert resp.status_code == 422
    assert "different clinician" in resp.json()["detail"].lower()


def test_administer_high_alert_medication_with_valid_second_clinician_succeeds(client, db_session):
    import uuid as uuid_module

    from app.medication_verification.models import AdministrationEvent

    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)
    verification_id = _make_high_alert_verified_event(client, headers, patient, db_session)

    second_clinician_headers = _register_and_login(
        client, email="second.nurse@example.com", password="anothersecret123"
    )
    second_clinician_id = client.get("/auth/me", headers=second_clinician_headers).json()["id"]

    resp = client.post(
        "/medication-verification/administer",
        json={
            "verification_id": verification_id,
            "co_signer_email": "second.nurse@example.com",
            "co_signer_password": "anothersecret123",
        },
        headers=headers,
    )

    assert resp.status_code == 200
    assert resp.json()["administered_at"] is not None

    event = db_session.get(AdministrationEvent, uuid_module.UUID(verification_id))
    assert str(event.co_signed_by) == second_clinician_id


def test_administer_non_high_alert_medication_does_not_require_cosign(client):
    """Sanity check: the co-sign gate must never apply outside high_alert —
    every other administer() test in this file already proves this
    implicitly (none of them pass co-signer fields), but this makes the
    contrast with the high-alert tests above explicit."""
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)
    _create_analyze_generate_approve(client, headers, patient["id"], MEDICATION_SUCCINATE_25)
    verification = _verify(client, headers, patient["patient_code"], BARCODE_SUCCINATE_25).json()

    resp = client.post(
        "/medication-verification/administer", json={"verification_id": verification["id"]}, headers=headers
    )

    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Drug-drug interaction check (see app/reference/drug_interactions.py and
# US_HOSPITAL_MARKET_STANDARDS_GAP_ANALYSIS.md item 5).
# ---------------------------------------------------------------------------


def test_severe_interaction_with_another_active_medication_is_blocked(client):
    """Metoprolol + Diltiazem is a curated SEVERE interaction — even though
    the scanned product otherwise matches the order perfectly, this must
    still block, the same as an allergy match."""
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)
    _create_analyze_generate_approve(client, headers, patient["id"], MEDICATION_SUCCINATE_25)
    _create_analyze_generate_approve(client, headers, patient["id"], "Take Diltiazem 120 mg orally once daily.")

    resp = _verify(client, headers, patient["patient_code"], BARCODE_SUCCINATE_25)

    assert resp.status_code == 200
    body = resp.json()
    assert body["result"] == "BLOCKED"
    assert "SEVERE_DRUG_INTERACTION" in body["mismatch_reasons"]
    assert body["checks"]["interactions"]["passed"] is False
    assert "Diltiazem" in body["checks"]["interactions"]["detail"]


def test_moderate_interaction_with_another_active_medication_is_a_warning(client):
    """Metoprolol + Clonidine is curated MODERATE — must not be silently
    ignored, but also must not be an absolute block like SEVERE/allergy."""
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)
    _create_analyze_generate_approve(client, headers, patient["id"], MEDICATION_SUCCINATE_25)
    _create_analyze_generate_approve(client, headers, patient["id"], "Take Clonidine 0.1 mg orally twice daily.")

    resp = _verify(client, headers, patient["patient_code"], BARCODE_SUCCINATE_25)

    assert resp.status_code == 200
    body = resp.json()
    assert body["result"] == "WARNING"
    assert "MODERATE_DRUG_INTERACTION" in body["mismatch_reasons"]
    assert body["checks"]["interactions"]["passed"] is False


def test_no_interaction_with_unrelated_active_medication_passes(client):
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)
    _create_analyze_generate_approve(client, headers, patient["id"], MEDICATION_SUCCINATE_25)
    _create_analyze_generate_approve(client, headers, patient["id"], "Take Metformin 500 mg orally twice daily.")

    resp = _verify(client, headers, patient["patient_code"], BARCODE_SUCCINATE_25)

    assert resp.status_code == 200
    body = resp.json()
    assert body["result"] == "VERIFIED"
    assert body["checks"]["interactions"]["passed"] is True
    assert body["mismatch_reasons"] == []


def test_administer_blocks_when_severe_interacting_medication_started_after_verification(client, db_session):
    """Mirrors the order-changed/allergy-after-verification safety nets: a
    new interacting medication started between scan and confirm must still
    stop the dose."""
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)
    _create_analyze_generate_approve(client, headers, patient["id"], MEDICATION_SUCCINATE_25)

    verification = _verify(client, headers, patient["patient_code"], BARCODE_SUCCINATE_25).json()
    assert verification["result"] == "VERIFIED"

    _create_analyze_generate_approve(client, headers, patient["id"], "Take Diltiazem 120 mg orally once daily.")

    resp = client.post(
        "/medication-verification/administer", json={"verification_id": verification["id"]}, headers=headers
    )

    assert resp.status_code == 422
    assert "interaction" in resp.json()["detail"].lower()


# ---------------------------------------------------------------------------
# Formulation ambiguity is scoped to drugs that actually HAVE more than one
# formulation — see _check_formulation's docstring. Before this, three of the
# five catalog drugs could never reach VERIFIED at all.
# ---------------------------------------------------------------------------


def test_single_formulation_drug_can_be_verified_without_stating_a_formulation(client):
    """Lisinopril is stocked in exactly one form, so an order that doesn't
    name a release type isn't ambiguous — there is nothing to confuse it
    with. Previously this was permanently REVIEW_REQUIRED, which meant the
    drug could never be administered through Module 2 at all."""
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)
    _create_analyze_generate_approve(client, headers, patient["id"], MEDICATION_LISINOPRIL)

    resp = _verify(client, headers, patient["patient_code"], BARCODE_LISINOPRIL_10)

    assert resp.status_code == 200
    body = resp.json()
    assert body["result"] == "VERIFIED"
    assert body["checks"]["formulation"]["passed"] is True
    assert "only one form" in body["checks"]["formulation"]["detail"]
    assert body["mismatch_reasons"] == []


def test_single_formulation_drug_can_then_be_administered(client):
    """The consequence that actually mattered: REVIEW_REQUIRED never renders a
    confirm button, so before this fix a correct Lisinopril dose could not be
    given through the app."""
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)
    _create_analyze_generate_approve(client, headers, patient["id"], MEDICATION_LISINOPRIL)
    verification = _verify(client, headers, patient["patient_code"], BARCODE_LISINOPRIL_10).json()

    resp = client.post(
        "/medication-verification/administer", json={"verification_id": verification["id"]}, headers=headers
    )

    assert resp.status_code == 200


def test_multi_formulation_drug_still_requires_an_explicit_formulation(client):
    """The safety property this check exists for is unchanged: Metoprolol IS
    stocked in two clinically different forms, so a plain 'Metoprolol' order
    remains genuinely ambiguous and must still go to review."""
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)
    _create_analyze_generate_approve(client, headers, patient["id"], MEDICATION_PLAIN)

    resp = _verify(client, headers, patient["patient_code"], BARCODE_SUCCINATE_25)

    assert resp.status_code == 200
    body = resp.json()
    assert body["result"] == "REVIEW_REQUIRED"
    assert "FORMULATION_UNSPECIFIED" in body["mismatch_reasons"]


def test_wrong_formulation_of_a_multi_formulation_drug_is_still_blocked(client):
    """The actual dangerous mix-up — Succinate ER order, Tartrate in hand —
    must remain a hard block, not merely a review."""
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)
    _create_analyze_generate_approve(client, headers, patient["id"], MEDICATION_SUCCINATE_25)

    resp = _verify(client, headers, patient["patient_code"], BARCODE_TARTRATE_25)

    assert resp.status_code == 200
    body = resp.json()
    assert body["result"] == "BLOCKED"
    assert "FORMULATION_MISMATCH" in body["mismatch_reasons"]


# ---------------------------------------------------------------------------
# PRN (as-needed) administration — a scheduled dose is justified by its
# schedule; an as-needed dose has no justification unless someone records it.
# ---------------------------------------------------------------------------

MEDICATION_PRN = "Take Paracetamol 500 mg orally every 6 hours as needed for pain."
BARCODE_PARACETAMOL_500 = "MED-PARACETAMOL-500"


def test_verify_marks_an_as_needed_order_as_prn(client):
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)
    _create_analyze_generate_approve(client, headers, patient["id"], MEDICATION_PRN)

    body = _verify(client, headers, patient["patient_code"], BARCODE_PARACETAMOL_500).json()

    assert body["order_is_prn"] is True


def test_verify_does_not_mark_a_scheduled_order_as_prn(client):
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)
    _create_analyze_generate_approve(client, headers, patient["id"], MEDICATION_SUCCINATE_25)

    body = _verify(client, headers, patient["patient_code"], BARCODE_SUCCINATE_25).json()

    assert body["order_is_prn"] is False


def test_administering_a_prn_dose_without_a_reason_is_rejected(client):
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)
    _create_analyze_generate_approve(client, headers, patient["id"], MEDICATION_PRN)
    verification = _verify(client, headers, patient["patient_code"], BARCODE_PARACETAMOL_500).json()

    resp = client.post(
        "/medication-verification/administer", json={"verification_id": verification["id"]}, headers=headers
    )

    assert resp.status_code == 422
    assert "as-needed" in resp.json()["detail"].lower()


def test_blank_reason_does_not_satisfy_the_prn_requirement(client):
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)
    _create_analyze_generate_approve(client, headers, patient["id"], MEDICATION_PRN)
    verification = _verify(client, headers, patient["patient_code"], BARCODE_PARACETAMOL_500).json()

    resp = client.post(
        "/medication-verification/administer",
        json={"verification_id": verification["id"], "administration_reason": "   "},
        headers=headers,
    )

    assert resp.status_code == 422


def test_administering_a_prn_dose_with_a_reason_records_it(client, db_session):
    import uuid as uuid_module

    from app.medication_verification.models import AdministrationEvent

    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)
    _create_analyze_generate_approve(client, headers, patient["id"], MEDICATION_PRN)
    verification = _verify(client, headers, patient["patient_code"], BARCODE_PARACETAMOL_500).json()

    resp = client.post(
        "/medication-verification/administer",
        json={"verification_id": verification["id"], "administration_reason": "pain 7/10"},
        headers=headers,
    )

    assert resp.status_code == 200
    event = db_session.get(AdministrationEvent, uuid_module.UUID(verification["id"]))
    assert event.administration_reason == "pain 7/10"


def test_scheduled_dose_still_needs_no_reason(client):
    """The PRN requirement must not leak onto ordinary scheduled doses."""
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)
    _create_analyze_generate_approve(client, headers, patient["id"], MEDICATION_SUCCINATE_25)
    verification = _verify(client, headers, patient["patient_code"], BARCODE_SUCCINATE_25).json()

    resp = client.post(
        "/medication-verification/administer", json={"verification_id": verification["id"]}, headers=headers
    )

    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# A discharged patient must not be administrable. Discharge deliberately
# leaves orders ACTIVE (so the record of what was prescribed survives), which
# meant every order of a discharged patient still verified normally.
# ---------------------------------------------------------------------------


def test_discharged_patient_scan_is_blocked(client):
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)
    _create_analyze_generate_approve(client, headers, patient["id"], MEDICATION_SUCCINATE_25)
    client.patch(f"/patients/{patient['id']}", json={"admission_status": "DISCHARGED"}, headers=headers)

    resp = _verify(client, headers, patient["patient_code"], BARCODE_SUCCINATE_25)

    assert resp.status_code == 200
    body = resp.json()
    assert body["result"] == "BLOCKED"
    assert "PATIENT_NOT_ADMITTED" in body["mismatch_reasons"]
    assert body["checks"]["admission"]["passed"] is False
    assert "DISCHARGED" in body["checks"]["admission"]["detail"]


def test_discharged_patient_cannot_be_administered_to(client):
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)
    _create_analyze_generate_approve(client, headers, patient["id"], MEDICATION_SUCCINATE_25)
    client.patch(f"/patients/{patient['id']}", json={"admission_status": "DISCHARGED"}, headers=headers)
    verification = _verify(client, headers, patient["patient_code"], BARCODE_SUCCINATE_25).json()

    resp = client.post(
        "/medication-verification/administer", json={"verification_id": verification["id"]}, headers=headers
    )

    assert resp.status_code == 422


def test_admitted_patient_is_unaffected_by_the_admission_check(client):
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)
    _create_analyze_generate_approve(client, headers, patient["id"], MEDICATION_SUCCINATE_25)

    body = _verify(client, headers, patient["patient_code"], BARCODE_SUCCINATE_25).json()

    assert body["result"] == "VERIFIED"


# ---------------------------------------------------------------------------
# The administration record, and documenting a dose that was NOT given.
# Before this, AdministrationEvent rows were written and never read, and a
# refused dose was indistinguishable from a nurse who walked away.
# ---------------------------------------------------------------------------


def _history(client, headers, patient_id):
    return client.get(f"/patients/{patient_id}/administrations", headers=headers)


def test_administration_history_shows_a_given_dose(client):
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)
    _create_analyze_generate_approve(client, headers, patient["id"], MEDICATION_SUCCINATE_25)
    verification = _verify(client, headers, patient["patient_code"], BARCODE_SUCCINATE_25).json()
    client.post("/medication-verification/administer", json={"verification_id": verification["id"]}, headers=headers)

    body = _history(client, headers, patient["id"]).json()

    assert body["total"] == 1
    row = body["results"][0]
    assert row["verification_result"] == "VERIFIED"
    assert row["administered_at"] is not None
    assert row["not_given_reason"] is None
    assert row["identified_medication_name"] == "Metoprolol Succinate ER"


def test_administration_history_includes_blocked_attempts(client):
    """A wrong drug caught at the bedside is exactly what the next shift needs
    to see — it must not be hidden from the record."""
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)
    _create_analyze_generate_approve(client, headers, patient["id"], MEDICATION_LISINOPRIL)
    _verify(client, headers, patient["patient_code"], BARCODE_SUCCINATE_25)

    body = _history(client, headers, patient["id"]).json()

    assert body["total"] == 1
    assert body["results"][0]["verification_result"] == "BLOCKED"


def test_recording_a_refused_dose(client):
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)
    _create_analyze_generate_approve(client, headers, patient["id"], MEDICATION_SUCCINATE_25)
    verification = _verify(client, headers, patient["patient_code"], BARCODE_SUCCINATE_25).json()

    resp = client.post(
        "/medication-verification/not-given",
        json={"verification_id": verification["id"], "reason": "REFUSED", "note": "patient declined"},
        headers=headers,
    )

    assert resp.status_code == 200
    row = _history(client, headers, patient["id"]).json()["results"][0]
    assert row["not_given_reason"] == "REFUSED"
    assert row["not_given_note"] == "patient declined"
    assert row["not_given_at"] is not None
    assert row["administered_at"] is None


def test_a_dose_cannot_be_both_given_and_not_given(client):
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)
    _create_analyze_generate_approve(client, headers, patient["id"], MEDICATION_SUCCINATE_25)
    verification = _verify(client, headers, patient["patient_code"], BARCODE_SUCCINATE_25).json()
    client.post("/medication-verification/administer", json={"verification_id": verification["id"]}, headers=headers)

    resp = client.post(
        "/medication-verification/not-given",
        json={"verification_id": verification["id"], "reason": "REFUSED"},
        headers=headers,
    )

    assert resp.status_code == 409


def test_a_not_given_dose_cannot_then_be_administered(client):
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)
    _create_analyze_generate_approve(client, headers, patient["id"], MEDICATION_SUCCINATE_25)
    verification = _verify(client, headers, patient["patient_code"], BARCODE_SUCCINATE_25).json()
    client.post(
        "/medication-verification/not-given",
        json={"verification_id": verification["id"], "reason": "HELD"},
        headers=headers,
    )

    resp = client.post(
        "/medication-verification/administer", json={"verification_id": verification["id"]}, headers=headers
    )

    assert resp.status_code in (409, 422)


def test_a_blocked_scan_can_still_be_documented_as_held(client):
    """"The scan was blocked so I held the dose and told the doctor" belongs on
    the record — refusing to let a nurse document it pushes the decision off
    the system entirely."""
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)
    _create_analyze_generate_approve(client, headers, patient["id"], MEDICATION_LISINOPRIL)
    blocked = _verify(client, headers, patient["patient_code"], BARCODE_SUCCINATE_25).json()
    assert blocked["result"] == "BLOCKED"

    resp = client.post(
        "/medication-verification/not-given",
        json={"verification_id": blocked["id"], "reason": "HELD", "note": "pharmacy contacted"},
        headers=headers,
    )

    assert resp.status_code == 200


def test_administration_history_requires_authentication(client):
    resp = client.get("/patients/00000000-0000-0000-0000-000000000000/administrations")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Nil by mouth before a procedure. The order stays ACTIVE and every other
# check passes, so without this the engine reported VERIFIED for a dose that
# must be held — the same shape of gap as the discharged patient.
# ---------------------------------------------------------------------------


def _set_nil_by_mouth(client, headers, patient_id, hours_ago=1, procedure="a hip replacement"):
    from datetime import datetime, timedelta, timezone

    encounter = client.post(
        f"/patients/{patient_id}/encounters",
        json={"reason_for_visit": "pre-operative admission", "admission_date": "2026-09-23"},
        headers=headers,
    ).json()
    npo_from = (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).isoformat()
    resp = client.patch(
        f"/encounters/{encounter['id']}",
        json={"planned_procedure": procedure, "nil_by_mouth_from": npo_from},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    return encounter


def test_oral_dose_is_blocked_for_a_nil_by_mouth_patient(client):
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)
    _create_analyze_generate_approve(client, headers, patient["id"], MEDICATION_SUCCINATE_25)
    _set_nil_by_mouth(client, headers, patient["id"])

    body = _verify(client, headers, patient["patient_code"], BARCODE_SUCCINATE_25).json()

    assert body["result"] == "BLOCKED"
    assert "PATIENT_NIL_BY_MOUTH" in body["mismatch_reasons"]
    assert body["checks"]["nil_by_mouth"]["passed"] is False
    assert "hip replacement" in body["checks"]["nil_by_mouth"]["detail"]


def test_nil_by_mouth_in_the_future_does_not_block_yet(client):
    """"NPO from midnight" is ordered in advance and must not take effect
    early — an alert that fires before it applies is an alert staff learn to
    ignore."""
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)
    _create_analyze_generate_approve(client, headers, patient["id"], MEDICATION_SUCCINATE_25)
    _set_nil_by_mouth(client, headers, patient["id"], hours_ago=-6)

    body = _verify(client, headers, patient["patient_code"], BARCODE_SUCCINATE_25).json()

    assert body["result"] == "VERIFIED"
    assert body["checks"]["nil_by_mouth"]["passed"] is True


def test_patient_not_nil_by_mouth_is_unaffected(client):
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)
    _create_analyze_generate_approve(client, headers, patient["id"], MEDICATION_SUCCINATE_25)

    body = _verify(client, headers, patient["patient_code"], BARCODE_SUCCINATE_25).json()

    assert body["result"] == "VERIFIED"
    assert body["checks"]["nil_by_mouth"]["passed"] is True


def test_a_held_pre_op_dose_can_be_documented_as_held(client):
    """The designed path out of an NPO block: the nurse documents the hold, so
    the decision is on the record rather than the dose silently not happening."""
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)
    _create_analyze_generate_approve(client, headers, patient["id"], MEDICATION_SUCCINATE_25)
    _set_nil_by_mouth(client, headers, patient["id"])
    blocked = _verify(client, headers, patient["patient_code"], BARCODE_SUCCINATE_25).json()

    resp = client.post(
        "/medication-verification/not-given",
        json={"verification_id": blocked["id"], "reason": "HELD", "note": "nil by mouth for theatre"},
        headers=headers,
    )

    assert resp.status_code == 200
    row = client.get(f"/patients/{patient['id']}/administrations", headers=headers).json()["results"][0]
    assert row["not_given_reason"] == "HELD"


def test_injected_medication_is_not_blocked_by_nil_by_mouth(client):
    """Nil by mouth restricts what goes through the gut, not what goes into
    the patient by injection. Blocking a subcutaneous dose here would be
    clinically wrong and would teach staff to click past the warning."""
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)
    _create_analyze_generate_approve(
        client, headers, patient["id"], "Give Enoxaparin 40 mg subcutaneously once daily."
    )
    _set_nil_by_mouth(client, headers, patient["id"])

    body = _verify(client, headers, patient["patient_code"], "MED-ENOXAPARIN-40").json()

    assert body["checks"]["nil_by_mouth"]["passed"] is True
    assert "not restricted" in body["checks"]["nil_by_mouth"]["detail"]
    assert "PATIENT_NIL_BY_MOUTH" not in body["mismatch_reasons"]
