import uuid

import pytest
from sqlalchemy.exc import IntegrityError

from app.instructions import service as instructions_service
from app.instructions.models import (
    InstructionVersion,
    PatientOutputTranslation,
    ValidationStatus,
    VersionSource,
)

MEDICATION_TEXT = "Take Metoprolol 25 mg orally twice daily with food."
MOBILITY_TEXT = "Walk for 10 minutes after meals with nurse assistance."


def _register_and_login(client, email="clinician@example.com", password="supersecret123"):
    client.post("/auth/register", json={"email": email, "password": password, "full_name": "Test Clinician"})
    login_resp = client.post("/auth/login", json={"email": email, "password": password})
    token = login_resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _current_user_id(client, headers) -> str:
    return client.get("/auth/me", headers=headers).json()["id"]


def _create_active_patient(client, headers, **overrides) -> dict:
    payload = {
        "first_name": "John",
        "last_name": "Doe",
        "date_of_birth": "1950-01-01",
        "preferred_language": "ENGLISH",
    }
    payload.update(overrides)
    return client.post("/patients", json=payload, headers=headers).json()


def _with_fixture(text: str, fixture: str) -> str:
    return f"{text} __FIXTURE__:{fixture}"


def _create_analyze_generate_approve(client, headers, patient_id, text) -> dict:
    """Runs the full clinician workflow up to APPROVED — every translation test
    needs this as its starting state."""
    created = client.post(f"/patients/{patient_id}/instructions", json={"text": text}, headers=headers).json()
    client.post(f"/instructions/{created['id']}/analyze", headers=headers)
    generated = client.post(f"/instructions/{created['id']}/generate", headers=headers).json()
    assert generated["status"] == "READY_FOR_APPROVAL", generated
    approved = client.post(f"/instructions/{created['id']}/approve", headers=headers).json()
    assert approved["status"] == "APPROVED"
    return created


def _translate(client, headers, instruction_id, languages):
    return client.post(
        f"/instructions/{instruction_id}/translations", json={"languages": languages}, headers=headers
    )


# ---------------------------------------------------------------------------
# Core translation behavior
# ---------------------------------------------------------------------------


def test_approved_output_translates_to_telugu(client):
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)
    created = _create_analyze_generate_approve(client, headers, patient["id"], MEDICATION_TEXT)

    resp = _translate(client, headers, created["id"], ["TELUGU"])

    assert resp.status_code == 200
    body = resp.json()
    assert body["TELUGU"]["status"] == "PASSED"


def test_approved_output_translates_to_hindi(client):
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)
    created = _create_analyze_generate_approve(client, headers, patient["id"], MEDICATION_TEXT)

    resp = _translate(client, headers, created["id"], ["HINDI"])

    assert resp.status_code == 200
    assert resp.json()["HINDI"]["status"] == "PASSED"


def test_valid_translation_passes_and_is_visible_on_instruction_detail(client):
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)
    created = _create_analyze_generate_approve(client, headers, patient["id"], MEDICATION_TEXT)
    _translate(client, headers, created["id"], ["TELUGU", "HINDI"])

    detail = client.get(f"/instructions/{created['id']}", headers=headers).json()
    output = detail["current_version"]["patient_outputs"][-1]
    translations = {t["language"]: t for t in output["translations"]}
    assert translations["TELUGU"]["validation_status"] == "PASSED"
    assert translations["HINDI"]["validation_status"] == "PASSED"
    assert "Metoprolol" in translations["TELUGU"]["translated_text"]
    assert "25" in translations["TELUGU"]["translated_text"]


def test_translation_cannot_be_requested_before_approval(client):
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)
    created = client.post(f"/patients/{patient['id']}/instructions", json={"text": MEDICATION_TEXT}, headers=headers).json()
    client.post(f"/instructions/{created['id']}/analyze", headers=headers)  # PROCESSING, not APPROVED

    resp = _translate(client, headers, created["id"], ["TELUGU"])

    assert resp.status_code == 409


def test_failed_english_output_cannot_be_translated(client, db_session):
    """Even if somehow current_version_id pointed at a version whose only output
    FAILED, translation must refuse — approve()'s own defense-in-depth check
    already prevents reaching APPROVED this way, so this proves translation
    doesn't independently reopen that gap."""
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)
    created = client.post(
        f"/patients/{patient['id']}/instructions",
        json={"text": _with_fixture(MEDICATION_TEXT, "GENERATION_CHANGED_DOSE")},
        headers=headers,
    ).json()
    client.post(f"/instructions/{created['id']}/analyze", headers=headers)
    generated = client.post(f"/instructions/{created['id']}/generate", headers=headers).json()
    assert generated["status"] == "NEEDS_REVIEW"  # FAILED output, never reached APPROVED

    resp = _translate(client, headers, created["id"], ["TELUGU"])

    assert resp.status_code == 409


# ---------------------------------------------------------------------------
# Fact-preservation failures
# ---------------------------------------------------------------------------


def test_dose_change_translation_fails(client):
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)
    created = _create_analyze_generate_approve(
        client, headers, patient["id"], _with_fixture(MEDICATION_TEXT, "TRANSLATION_CHANGED_DOSE")
    )

    resp = _translate(client, headers, created["id"], ["TELUGU"])

    assert resp.status_code == 200
    assert resp.json()["TELUGU"]["status"] == "FAILED"

    detail = client.get(f"/instructions/{created['id']}", headers=headers).json()
    output = detail["current_version"]["patient_outputs"][-1]
    telugu = next(t for t in output["translations"] if t["language"] == "TELUGU")
    assert any(d["field"] == "dose_value" for d in telugu["validation_diff"])


def test_frequency_change_translation_fails(client):
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)
    created = _create_analyze_generate_approve(
        client, headers, patient["id"], _with_fixture(MEDICATION_TEXT, "TRANSLATION_CHANGED_FREQUENCY")
    )

    resp = _translate(client, headers, created["id"], ["TELUGU"])

    assert resp.json()["TELUGU"]["status"] == "FAILED"


def test_duration_change_translation_fails(client):
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)
    created = _create_analyze_generate_approve(
        client, headers, patient["id"], _with_fixture(MOBILITY_TEXT, "TRANSLATION_CHANGED_DURATION")
    )

    resp = _translate(client, headers, created["id"], ["TELUGU"])

    assert resp.json()["TELUGU"]["status"] == "FAILED"


def test_assistance_requirement_change_translation_fails(client):
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)
    created = _create_analyze_generate_approve(
        client, headers, patient["id"], _with_fixture(MOBILITY_TEXT, "TRANSLATION_CHANGED_ASSISTANCE")
    )

    resp = _translate(client, headers, created["id"], ["TELUGU"])

    assert resp.json()["TELUGU"]["status"] == "FAILED"


# ---------------------------------------------------------------------------
# Independence between languages / English
# ---------------------------------------------------------------------------


def test_telugu_failure_does_not_block_english(client):
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)
    created = _create_analyze_generate_approve(
        client, headers, patient["id"], _with_fixture(MEDICATION_TEXT, "TRANSLATION_TELUGU_CHANGED_DOSE")
    )

    _translate(client, headers, created["id"], ["TELUGU"])

    detail = client.get(f"/instructions/{created['id']}", headers=headers).json()
    assert detail["status"] == "APPROVED"
    assert detail["current_version"]["patient_outputs"][-1]["validation_status"] == "PASSED"
    assert detail["current_version"]["patient_outputs"][-1]["patient_text_en"] is not None


def test_hindi_failure_does_not_block_telugu_or_english(client):
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)
    created = _create_analyze_generate_approve(
        client, headers, patient["id"], _with_fixture(MEDICATION_TEXT, "TRANSLATION_HINDI_CHANGED_DOSE")
    )

    resp = _translate(client, headers, created["id"], ["TELUGU", "HINDI"])

    body = resp.json()
    assert body["TELUGU"]["status"] == "PASSED"
    assert body["HINDI"]["status"] == "FAILED"

    detail = client.get(f"/instructions/{created['id']}", headers=headers).json()
    assert detail["status"] == "APPROVED"  # unaffected by the Hindi failure
    assert detail["current_version"]["patient_outputs"][-1]["patient_text_en"] is not None


# ---------------------------------------------------------------------------
# Immutability / uniqueness
# ---------------------------------------------------------------------------


def test_translation_rows_are_immutable_repeat_request_returns_same_row(client):
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)
    created = _create_analyze_generate_approve(client, headers, patient["id"], MEDICATION_TEXT)

    first = _translate(client, headers, created["id"], ["TELUGU"]).json()
    detail1 = client.get(f"/instructions/{created['id']}", headers=headers).json()
    first_translation = detail1["current_version"]["patient_outputs"][-1]["translations"][0]

    second = _translate(client, headers, created["id"], ["TELUGU"]).json()
    detail2 = client.get(f"/instructions/{created['id']}", headers=headers).json()
    second_translation = detail2["current_version"]["patient_outputs"][-1]["translations"][0]

    assert first["TELUGU"]["status"] == second["TELUGU"]["status"] == "PASSED"
    assert first_translation["id"] == second_translation["id"]  # same row, not a new attempt
    assert first_translation["created_at"] == second_translation["created_at"]


def test_unique_language_per_patient_output_enforced(client, db_session):
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)
    created = _create_analyze_generate_approve(client, headers, patient["id"], MEDICATION_TEXT)
    _translate(client, headers, created["id"], ["TELUGU"])

    detail = client.get(f"/instructions/{created['id']}", headers=headers).json()
    output_id = uuid.UUID(detail["current_version"]["patient_outputs"][-1]["id"])

    duplicate = PatientOutputTranslation(
        patient_output_id=output_id,
        language="TELUGU",
        translated_text="duplicate",
        validation_status=ValidationStatus.PASSED,
        provider="mock",
        model="mock-extraction-v1",
        prompt_version="health-literacy-translation-v1",
    )
    db_session.add(duplicate)

    with pytest.raises(IntegrityError):
        db_session.flush()

    db_session.rollback()


# ---------------------------------------------------------------------------
# Stale protection (mirrors Steps 5/6's version) — not reachable via the
# public API today, since APPROVED is a terminal state with no outgoing
# transitions in this state machine; tested directly as a white-box guard.
# ---------------------------------------------------------------------------


def test_stale_translation_result_cannot_attach_to_a_newer_version(client, db_session):
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)
    created = _create_analyze_generate_approve(client, headers, patient["id"], MEDICATION_TEXT)
    instruction_id = uuid.UUID(created["id"])
    user_id = uuid.UUID(_current_user_id(client, headers))

    detail = client.get(f"/instructions/{created['id']}", headers=headers).json()
    v1_id = uuid.UUID(detail["current_version"]["id"])
    output_id = uuid.UUID(detail["current_version"]["patient_outputs"][-1]["id"])

    # Simulate the instruction somehow moving on to a newer version after
    # approval (not reachable via the real API today — APPROVED has no
    # outgoing transitions — but the guard must hold regardless).
    instruction = instructions_service.get_instruction(db_session, instruction_id)
    v2 = InstructionVersion(
        care_instruction_id=instruction.id,
        version_number=2,
        raw_text="a later version",
        source=VersionSource.CLARIFICATION,
        created_by=user_id,
    )
    db_session.add(v2)
    db_session.flush()
    instruction.current_version_id = v2.id
    db_session.commit()

    from app.ai.translation_service import TranslationAttempt
    from app.ai.provider import ProviderMetadata

    late_attempt = TranslationAttempt(
        succeeded=True,
        translated_text="[TELUGU_TR] a late result",
        metadata=ProviderMetadata(provider="mock", model="mock-extraction-v1", request_id="late", latency_ms=1, token_usage=None),
        prompt_version="health-literacy-translation-v1",
        failure_reason=None,
    )

    result = instructions_service._apply_translation_result(
        db_session, instruction_id, v1_id, output_id, "TELUGU", late_attempt, None, user_id
    )

    # Persisted for the record, but the instruction's current_version_id must
    # remain untouched — still v2, never reverted by the stale v1 result.
    refreshed_instruction = instructions_service.get_instruction(db_session, instruction_id)
    assert refreshed_instruction.current_version_id == v2.id
    assert result.patient_output_id == output_id
