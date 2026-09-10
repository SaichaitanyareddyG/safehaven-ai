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
