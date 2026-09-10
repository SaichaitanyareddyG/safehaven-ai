import uuid

import pytest
from sqlalchemy.exc import IntegrityError

from app.instructions import service as instructions_service
from app.instructions.models import (
    CompletenessStatus,
    InstructionStatus,
    InstructionType,
    InstructionVersion,
    PatientOutput,
    StructuredExtraction,
    ValidationStatus,
    VersionSource,
)
from app.instructions.state import transition


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


def _create_and_analyze(client, headers, patient_id, text) -> dict:
    created = client.post(f"/patients/{patient_id}/instructions", json={"text": text}, headers=headers).json()
    return client.post(f"/instructions/{created['id']}/analyze", headers=headers).json()


def _generate(client, headers, instruction_id) -> dict:
    resp = client.post(f"/instructions/{instruction_id}/generate", headers=headers)
    return resp


MEDICATION_TEXT = "Take Metoprolol 25 mg orally twice daily with food."
MOBILITY_TEXT = "Walk for 10 minutes after meals with nurse assistance."


def _with_fixture(text: str, fixture: str) -> str:
    return f"{text} __FIXTURE__:{fixture}"


# ---------------------------------------------------------------------------
# Core generate behavior
# ---------------------------------------------------------------------------


def test_complete_medication_instruction_generates_patient_text(client):
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)
    analyzed = _create_and_analyze(client, headers, patient["id"], MEDICATION_TEXT)
    assert analyzed["status"] == "PROCESSING"

    resp = _generate(client, headers, analyzed["id"])

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "READY_FOR_APPROVAL"
    outputs = body["current_version"]["patient_outputs"]
    assert len(outputs) == 1
    output = outputs[0]
    assert output["attempt_number"] == 1
    assert output["validation_status"] == "PASSED"
    assert "Metoprolol" in output["patient_text_en"]
    assert "25" in output["patient_text_en"]


def test_exact_dose_preserved_passes(client):
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)
    analyzed = _create_and_analyze(client, headers, patient["id"], MEDICATION_TEXT)

    body = _generate(client, headers, analyzed["id"]).json()

    output = body["current_version"]["patient_outputs"][0]
    assert output["validation_status"] == "PASSED"
    assert output["validation_diff"] == []


def test_generate_from_draft_is_rejected(client):
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)
    created = client.post(
        f"/patients/{patient['id']}/instructions", json={"text": MEDICATION_TEXT}, headers=headers
    ).json()

    resp = _generate(client, headers, created["id"])

    assert resp.status_code == 409


def test_generate_from_needs_review_is_rejected(client):
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)
    analyzed = _create_and_analyze(client, headers, patient["id"], "Walk after meals.")
    assert analyzed["status"] == "NEEDS_REVIEW"

    resp = _generate(client, headers, analyzed["id"])

    assert resp.status_code == 409


def test_generate_requires_current_extraction_to_be_passed(client, db_session):
    """Defense in depth: even if status were somehow PROCESSING without a PASSED
    extraction behind it, generate must still refuse. PROCESSING is otherwise
    unreachable without a PASSED extraction through normal flow, so this test
    deliberately manufactures that corrupted state to prove the extra check
    (not just the status check) is what's actually guarding this."""
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)
    analyzed = _create_and_analyze(client, headers, patient["id"], "Walk after meals.")
    assert analyzed["status"] == "NEEDS_REVIEW"  # extraction is NEEDS_CLARIFICATION, not PASSED

    instruction = instructions_service.get_instruction(db_session, uuid.UUID(analyzed["id"]))
    transition(instruction, InstructionStatus.PROCESSING)
    db_session.commit()

    resp = _generate(client, headers, analyzed["id"])

    assert resp.status_code == 409


# ---------------------------------------------------------------------------
# Fact-preservation validation — each fixture deliberately corrupts one fact
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("fixture", "expected_field"),
    [
        ("GENERATION_CHANGED_DOSE", "dose_value"),
        ("GENERATION_CHANGED_FREQUENCY", "frequency"),
        ("GENERATION_CHANGED_MEDICATION_NAME", "medication_name"),
        ("GENERATION_REMOVED_ROUTE", "route"),
    ],
)
def test_medication_fact_corruption_fails_validation(client, fixture, expected_field):
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)
    analyzed = _create_and_analyze(client, headers, patient["id"], _with_fixture(MEDICATION_TEXT, fixture))

    body = _generate(client, headers, analyzed["id"]).json()

    assert body["status"] == "NEEDS_REVIEW"
    assert "FACT_PRESERVATION_FAILED" in body["review_reason"]
    output = body["current_version"]["patient_outputs"][0]
    assert output["validation_status"] == "FAILED"
    assert any(d["field"] == expected_field for d in output["validation_diff"])


def test_mobility_duration_is_preserved(client):
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)
    analyzed = _create_and_analyze(client, headers, patient["id"], MOBILITY_TEXT)

    body = _generate(client, headers, analyzed["id"]).json()

    assert body["status"] == "READY_FOR_APPROVAL"
    output = body["current_version"]["patient_outputs"][0]
    assert "10 minutes" in output["patient_text_en"]


def test_assisted_walking_changed_to_independent_fails(client):
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)
    analyzed = _create_and_analyze(
        client, headers, patient["id"], _with_fixture(MOBILITY_TEXT, "GENERATION_REMOVED_ASSISTANCE")
    )
    assert analyzed["current_version"]["extraction"]["normalized_facts"]["assistance_required"] is True

    body = _generate(client, headers, analyzed["id"]).json()

    assert body["status"] == "NEEDS_REVIEW"
    output = body["current_version"]["patient_outputs"][0]
    assert output["validation_status"] == "FAILED"
    diff = next(d for d in output["validation_diff"] if d["field"] == "assistance_required")
    assert diff["source"] is True
    assert diff["generated"] is False


def test_assistance_added_when_absent_fails(client):
    source_text = "Walk for 10 minutes after meals without assistance."
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)
    analyzed = _create_and_analyze(
        client, headers, patient["id"], _with_fixture(source_text, "GENERATION_ADDED_ASSISTANCE")
    )
    assert analyzed["current_version"]["extraction"]["normalized_facts"]["assistance_required"] is False

    body = _generate(client, headers, analyzed["id"]).json()

    assert body["status"] == "NEEDS_REVIEW"
    output = body["current_version"]["patient_outputs"][0]
    diff = next(d for d in output["validation_diff"] if d["field"] == "assistance_required")
    assert diff["source"] is False
    assert diff["generated"] is True


def test_equivalent_normalization_passes(client):
    """Source uses abbreviations (PO, BID); the generated text's paraphrase
    ("by mouth", "twice daily") must be recognized as equivalent, not CHANGED —
    this is exactly what normalization exists for (see validation/normalization.py)."""
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)
    analyzed = _create_and_analyze(client, headers, patient["id"], "Take Metoprolol 25 mg PO BID with food.")
    facts = analyzed["current_version"]["extraction"]["normalized_facts"]
    assert facts["route"] == "oral"
    assert facts["frequency"] == "twice daily"

    body = _generate(client, headers, analyzed["id"]).json()

    assert body["status"] == "READY_FOR_APPROVAL"
    assert body["current_version"]["patient_outputs"][0]["validation_status"] == "PASSED"


def test_explicit_warning_removed_fails(client, db_session):
    """The mock's own extraction never produces non-empty warnings organically
    (no free-text warning parser) — this simulates what a real LLM extraction
    might have found, same pattern used elsewhere for scenarios the mock can't
    reach through its own organic engine."""
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)
    user_id = uuid.UUID(_current_user_id(client, headers))
    created = client.post(
        f"/patients/{patient['id']}/instructions",
        json={"text": _with_fixture(MEDICATION_TEXT, "GENERATION_REMOVED_WARNING")},
        headers=headers,
    ).json()

    instruction = instructions_service.get_instruction(db_session, uuid.UUID(created["id"]))
    version_id = instruction.current_version_id
    transition(instruction, InstructionStatus.PROCESSING)
    extraction = StructuredExtraction(
        instruction_version_id=version_id,
        instruction_type=InstructionType.MEDICATION,
        extracted_facts={},
        normalized_facts={
            "medication_name": "Metoprolol",
            "dose_value": 25.0,
            "dose_unit": "mg",
            "route": "oral",
            "frequency": "twice daily",
            "timing": None,
            "with_food": True,
            "warnings": ["Avoid grapefruit juice"],
        },
        missing_fields=[],
        ambiguous_fields=[],
        clarification_required_fields=[],
        validation_messages=[],
        completeness_status=CompletenessStatus.PASSED,
        provider="mock",
        model="mock-extraction-v1",
        prompt_version="health-literacy-extraction-v1",
    )
    db_session.add(extraction)
    db_session.commit()

    resp = client.post(f"/instructions/{created['id']}/generate", headers=headers)

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "NEEDS_REVIEW"
    output = body["current_version"]["patient_outputs"][0]
    assert output["validation_status"] == "FAILED"
    assert any(
        d["field"] == "warnings" and d["source"] == "Avoid grapefruit juice" for d in output["validation_diff"]
    )


# ---------------------------------------------------------------------------
# Failure handling
# ---------------------------------------------------------------------------


def test_generated_output_reextraction_malformed_is_a_safe_failure(client):
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)
    analyzed = _create_and_analyze(
        client, headers, patient["id"], _with_fixture(MEDICATION_TEXT, "GENERATION_REEXTRACTION_MALFORMED")
    )

    body = _generate(client, headers, analyzed["id"]).json()

    assert body["status"] == "NEEDS_REVIEW"
    output = body["current_version"]["patient_outputs"][0]
    assert output["validation_status"] == "FAILED"
    assert output["patient_text_en"] is not None  # generation itself succeeded
    assert any(d["type"] == "AMBIGUOUS" for d in output["validation_diff"])


def test_generation_provider_failure_moves_to_needs_review(client):
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)
    analyzed = _create_and_analyze(
        client, headers, patient["id"], _with_fixture(MEDICATION_TEXT, "GENERATION_PROVIDER_FAILURE")
    )

    body = _generate(client, headers, analyzed["id"]).json()

    assert body["status"] == "NEEDS_REVIEW"
    assert "AI_GENERATION_FAILED" in body["review_reason"]
    output = body["current_version"]["patient_outputs"][0]
    assert output["validation_status"] == "FAILED"
    assert output["patient_text_en"] is None  # no fabricated fallback text
    # The original clinical instruction stays visible regardless.
    assert body["current_version"]["raw_text"].startswith(MEDICATION_TEXT)


def test_provider_construction_failure_during_generation_is_handled_gracefully(client, monkeypatch):
    from app.core.config import get_settings

    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)
    analyzed = _create_and_analyze(client, headers, patient["id"], MEDICATION_TEXT)

    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    get_settings.cache_clear()

    resp = _generate(client, headers, analyzed["id"])

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "NEEDS_REVIEW"
    assert "AI_GENERATION_FAILED" in body["review_reason"]

    monkeypatch.undo()
    get_settings.cache_clear()


# ---------------------------------------------------------------------------
# Approval, now gated on a real PASSED PatientOutput
# ---------------------------------------------------------------------------


def test_valid_output_can_be_approved_and_approved_by_comes_from_auth_context(client, db_session):
    headers = _register_and_login(client)
    user_id = _current_user_id(client, headers)
    patient = _create_active_patient(client, headers)
    analyzed = _create_and_analyze(client, headers, patient["id"], MEDICATION_TEXT)
    generated = _generate(client, headers, analyzed["id"]).json()
    assert generated["status"] == "READY_FOR_APPROVAL"

    resp = client.post(f"/instructions/{analyzed['id']}/approve", headers=headers)

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "APPROVED"
    assert body["approved_at"] is not None

    instruction = instructions_service.get_instruction(db_session, uuid.UUID(analyzed["id"]))
    assert str(instruction.approved_by) == user_id


def test_failed_output_cannot_be_approved(client):
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)
    analyzed = _create_and_analyze(
        client, headers, patient["id"], _with_fixture(MEDICATION_TEXT, "GENERATION_CHANGED_DOSE")
    )
    generated = _generate(client, headers, analyzed["id"]).json()
    assert generated["status"] == "NEEDS_REVIEW"

    resp = client.post(f"/instructions/{analyzed['id']}/approve", headers=headers)

    assert resp.status_code == 409


def test_approve_defense_in_depth_rejects_even_if_status_is_corrupted_to_ready(client, db_session):
    """The status graph already prevents this in normal flow (READY_FOR_APPROVAL
    is a terminal-ish state generate() sets only alongside a PASSED output) — this
    proves the *separate* PatientOutput check in approve() is real, not just
    relying on the status check, by manufacturing the corrupted state directly."""
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)
    analyzed = _create_and_analyze(
        client, headers, patient["id"], _with_fixture(MEDICATION_TEXT, "GENERATION_CHANGED_DOSE")
    )
    generated = _generate(client, headers, analyzed["id"]).json()
    assert generated["status"] == "NEEDS_REVIEW"  # has a FAILED output only

    instruction = instructions_service.get_instruction(db_session, uuid.UUID(analyzed["id"]))
    # Deliberately bypass transition()'s own graph check here — that's the whole
    # point: this simulates a corruption transition() would never itself allow.
    instruction.status = InstructionStatus.READY_FOR_APPROVAL
    db_session.commit()

    resp = client.post(f"/instructions/{analyzed['id']}/approve", headers=headers)

    assert resp.status_code == 409


def test_approved_instruction_cannot_be_clarified(client):
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)
    analyzed = _create_and_analyze(client, headers, patient["id"], MEDICATION_TEXT)
    _generate(client, headers, analyzed["id"])
    client.post(f"/instructions/{analyzed['id']}/approve", headers=headers)

    resp = client.post(f"/instructions/{analyzed['id']}/clarify", json={"text": "new text"}, headers=headers)

    assert resp.status_code == 409


# ---------------------------------------------------------------------------
# Attempt immutability / uniqueness
# ---------------------------------------------------------------------------


def test_patient_output_attempt_history_is_immutable(client, db_session):
    """No endpoint can trigger a second attempt on the same version through
    normal flow today (status leaves PROCESSING after any generate call) — this
    directly exercises generate_patient_output() twice via the service layer,
    resetting status between calls the way a future retry mechanism would,
    proving attempt_number increments and the first attempt's row is untouched."""
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)
    analyzed = _create_and_analyze(
        client, headers, patient["id"], _with_fixture(MEDICATION_TEXT, "GENERATION_CHANGED_DOSE")
    )
    instruction_id = uuid.UUID(analyzed["id"])
    actor_id = uuid.UUID(_current_user_id(client, headers))

    first = instructions_service.generate_patient_output(db_session, instruction_id, actor_id)
    assert first.status == InstructionStatus.NEEDS_REVIEW

    first_output = (
        db_session.query(PatientOutput)
        .filter(PatientOutput.instruction_version_id == first.current_version_id)
        .one()
    )
    assert first_output.attempt_number == 1
    first_output_id = first_output.id
    first_text = first_output.patient_text_en

    # Reset back to PROCESSING the way analyze() would leave it, to simulate a
    # retry (no such endpoint exists yet — see report).
    transition(first, InstructionStatus.PROCESSING)
    db_session.commit()

    second = instructions_service.generate_patient_output(db_session, instruction_id, actor_id)

    outputs = (
        db_session.query(PatientOutput)
        .filter(PatientOutput.instruction_version_id == second.current_version_id)
        .order_by(PatientOutput.attempt_number)
        .all()
    )
    assert [o.attempt_number for o in outputs] == [1, 2]
    unchanged_first = next(o for o in outputs if o.id == first_output_id)
    assert unchanged_first.patient_text_en == first_text  # first attempt untouched


def test_patient_output_attempt_number_is_unique_per_version(client, db_session):
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)
    analyzed = _create_and_analyze(client, headers, patient["id"], MEDICATION_TEXT)
    generated = _generate(client, headers, analyzed["id"]).json()
    version_id = uuid.UUID(generated["current_version"]["id"])

    duplicate = PatientOutput(
        instruction_version_id=version_id,
        attempt_number=1,  # collides with the real attempt created above
        patient_text_en="duplicate",
        validation_status=ValidationStatus.PASSED,
        provider="mock",
        model="mock-extraction-v1",
        prompt_version="health-literacy-generation-v1",
    )
    db_session.add(duplicate)

    with pytest.raises(IntegrityError):
        db_session.flush()

    db_session.rollback()


# ---------------------------------------------------------------------------
# Stale-result protection (mirrors the Step 5 analysis version of this test)
# ---------------------------------------------------------------------------


def test_stale_generation_result_cannot_change_a_newer_version(client, db_session):
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)
    analyzed = _create_and_analyze(client, headers, patient["id"], MEDICATION_TEXT)
    instruction_id = uuid.UUID(analyzed["id"])
    v1_id = uuid.UUID(analyzed["current_version"]["id"])
    user_id = uuid.UUID(_current_user_id(client, headers))

    # Simulate: generation started against v1 (still PROCESSING) but its result
    # hasn't landed, and meanwhile a new version has already become current.
    instruction = instructions_service.get_instruction(db_session, instruction_id)
    v2 = InstructionVersion(
        care_instruction_id=instruction.id,
        version_number=2,
        raw_text="Take Metoprolol 25 mg orally twice daily with food, revised.",
        source=VersionSource.CLARIFICATION,
        created_by=user_id,
    )
    db_session.add(v2)
    db_session.flush()
    v2_id = v2.id
    instruction.current_version_id = v2_id
    db_session.commit()

    from app.ai.generation_service import GenerationAttempt
    from app.ai.provider import ProviderMetadata

    late_attempt = GenerationAttempt(
        succeeded=True,
        patient_text="Take Metoprolol 25 mg by mouth twice daily. Take it with food.",
        metadata=ProviderMetadata(provider="mock", model="mock-extraction-v1", request_id="late", latency_ms=1, token_usage=None),
        prompt_version="health-literacy-generation-v1",
        failure_reason=None,
    )

    result = instructions_service._apply_generation_result(
        db_session,
        instruction_id,
        v1_id,
        1,
        InstructionType.MEDICATION,
        {"dose_value": 25.0},
        late_attempt,
        None,
        user_id,
    )

    assert result.current_version_id == v2_id  # untouched — still points at v2
    assert result.status == InstructionStatus.PROCESSING  # untouched by the stale result

    # Still persisted for the historical record, on v1.
    v1_output = db_session.query(PatientOutput).filter(PatientOutput.instruction_version_id == v1_id).one()
    assert v1_output.attempt_number == 1


# ---------------------------------------------------------------------------
# No raw provider data persisted
# ---------------------------------------------------------------------------


def test_no_raw_provider_data_in_patient_output_response(client):
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)
    analyzed = _create_and_analyze(client, headers, patient["id"], MEDICATION_TEXT)

    body = _generate(client, headers, analyzed["id"]).json()

    output = body["current_version"]["patient_outputs"][0]
    assert set(output.keys()) == {
        "id",
        "attempt_number",
        "patient_text_en",
        "validation_status",
        "validation_diff",
        "validation_messages",
        "provider",
        "model",
        "prompt_version",
        "created_at",
        "translations",
    }
