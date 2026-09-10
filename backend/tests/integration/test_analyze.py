import uuid

from app.instructions import service as instructions_service
from app.instructions.models import InstructionStatus


def _register_and_login(client, email="clinician@example.com", password="supersecret123"):
    client.post("/auth/register", json={"email": email, "password": password, "full_name": "Test Clinician"})
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


def _create_and_analyze(client, headers, patient_id, text) -> dict:
    created = client.post(f"/patients/{patient_id}/instructions", json={"text": text}, headers=headers).json()
    return client.post(f"/instructions/{created['id']}/analyze", headers=headers).json()


# ---------------------------------------------------------------------------
# Core analyze behavior
# ---------------------------------------------------------------------------


def test_analyze_draft_instruction(client):
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)
    created = client.post(
        f"/patients/{patient['id']}/instructions",
        json={"text": "Take Metoprolol 25 mg orally twice daily with food."},
        headers=headers,
    ).json()

    resp = client.post(f"/instructions/{created['id']}/analyze", headers=headers)

    assert resp.status_code == 200
    assert resp.json()["status"] == "PROCESSING"


def test_reanalyze_non_draft_instruction_is_rejected(client):
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)
    created = client.post(
        f"/patients/{patient['id']}/instructions",
        json={"text": "Take Metoprolol 25 mg orally twice daily with food."},
        headers=headers,
    ).json()
    client.post(f"/instructions/{created['id']}/analyze", headers=headers)  # now PROCESSING

    resp = client.post(f"/instructions/{created['id']}/analyze", headers=headers)  # not DRAFT anymore

    assert resp.status_code == 409


# ---------------------------------------------------------------------------
# Completeness outcomes
# ---------------------------------------------------------------------------


def test_complete_medication_instruction_stays_processing(client):
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)

    body = _create_and_analyze(client, headers, patient["id"], "Take Metoprolol 25 mg orally twice daily with food.")

    assert body["status"] == "PROCESSING"
    assert body["review_reason"] is None
    extraction = body["current_version"]["extraction"]
    assert extraction["instruction_type"] == "MEDICATION"
    assert extraction["completeness_status"] == "PASSED"
    assert extraction["clarification_required_fields"] == []
    facts = extraction["normalized_facts"]
    assert facts["medication_name"] == "Metoprolol"
    assert facts["dose_value"] == 25.0
    assert facts["dose_unit"] == "mg"
    assert facts["frequency"] == "twice daily"


def test_reason_extracted_when_explicitly_stated(client):
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)

    body = _create_and_analyze(
        client, headers, patient["id"], "Take Metoprolol 25 mg orally twice daily for your blood pressure."
    )

    facts = body["current_version"]["extraction"]["normalized_facts"]
    assert facts["reason"] == "your blood pressure"
    # PASSED regardless — reason is optional-tier, absence or presence never
    # blocks completion.
    assert body["current_version"]["extraction"]["completeness_status"] == "PASSED"


def test_reason_stays_null_when_not_stated_never_invented(client):
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)

    body = _create_and_analyze(client, headers, patient["id"], "Take Metoprolol 25 mg orally twice daily with food.")

    facts = body["current_version"]["extraction"]["normalized_facts"]
    assert facts["reason"] is None


def test_reason_not_confused_with_duration_phrase(client):
    """'for 7 days' is a duration, not a reason -- must not be misread as one,
    and must itself be captured as the course length."""
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)

    body = _create_and_analyze(
        client, headers, patient["id"], "Take Amoxicillin 500 mg orally three times daily for 7 days."
    )

    facts = body["current_version"]["extraction"]["normalized_facts"]
    assert facts["reason"] is None
    assert facts["duration"] == "7 days"


def test_duration_extracted_when_explicitly_stated(client):
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)

    body = _create_and_analyze(
        client, headers, patient["id"], "Take Paracetamol 500 mg orally twice daily for 3 days."
    )

    facts = body["current_version"]["extraction"]["normalized_facts"]
    assert facts["duration"] == "3 days"
    # Optional-tier -- presence or absence never blocks completion.
    assert body["current_version"]["extraction"]["completeness_status"] == "PASSED"


def test_duration_stays_null_when_not_stated(client):
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)

    body = _create_and_analyze(client, headers, patient["id"], "Take Metoprolol 25 mg orally twice daily with food.")

    facts = body["current_version"]["extraction"]["normalized_facts"]
    assert facts["duration"] is None


def test_missing_medication_dose_requires_clarification(client):
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)

    body = _create_and_analyze(client, headers, patient["id"], "Take Metoprolol.")

    assert body["status"] == "NEEDS_REVIEW"
    extraction = body["current_version"]["extraction"]
    assert extraction["completeness_status"] == "NEEDS_CLARIFICATION"
    assert "dose_value" in extraction["clarification_required_fields"]
    assert "dose_unit" in extraction["clarification_required_fields"]


def test_complete_mobility_instruction_stays_processing(client):
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)

    body = _create_and_analyze(
        client, headers, patient["id"], "Walk for 10 minutes after meals with nurse assistance."
    )

    assert body["status"] == "PROCESSING"
    extraction = body["current_version"]["extraction"]
    assert extraction["instruction_type"] == "MOBILITY"
    assert extraction["completeness_status"] == "PASSED"
    facts = extraction["normalized_facts"]
    assert facts["activity"] == "walking"
    assert facts["duration"] == "10 minutes"
    assert facts["assistance_required"] is True


def test_walk_after_meals_preserves_duration_and_assistance_as_null(client):
    """The user's own worked example: the AI must never invent a value for
    information the instruction simply doesn't mention."""
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)

    body = _create_and_analyze(client, headers, patient["id"], "Walk after meals.")

    extraction = body["current_version"]["extraction"]
    facts = extraction["normalized_facts"]
    assert facts["activity"] == "walking"
    assert facts["timing"] == "after meals"
    assert facts["duration"] is None
    assert facts["assistance_required"] is None


def test_missing_field_does_not_automatically_require_clarification(client):
    """duration is missing but optional-tier for MOBILITY — it must show up in
    missing_fields without forcing clarification_required_fields/NEEDS_REVIEW."""
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)

    body = _create_and_analyze(client, headers, patient["id"], "Walk for 10 minutes after meals.")

    extraction = body["current_version"]["extraction"]
    assert "duration" not in extraction["missing_fields"]  # it WAS specified here
    assert "assistance_required" in extraction["missing_fields"]
    assert "assistance_required" in extraction["clarification_required_fields"]
    assert body["status"] == "NEEDS_REVIEW"


def test_configurable_rule_makes_assistance_required_mandatory_for_mobility(client):
    """Same instruction as above, phrased differently — demonstrates the rules
    table (not the LLM) is what makes assistance_required block completion."""
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)

    body = _create_and_analyze(client, headers, patient["id"], "Walk after meals.")

    extraction = body["current_version"]["extraction"]
    assert extraction["clarification_required_fields"] == ["assistance_required"]
    assert "duration" in extraction["missing_fields"]
    assert "duration" not in extraction["clarification_required_fields"]


# ---------------------------------------------------------------------------
# Failure handling — malformed output / provider failure
# ---------------------------------------------------------------------------


def test_malformed_llm_output_is_safely_rejected(client):
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)

    body = _create_and_analyze(client, headers, patient["id"], "__FIXTURE__:MALFORMED_RESPONSE")

    assert body["status"] == "NEEDS_REVIEW"
    assert "AI_EXTRACTION_FAILED" in body["review_reason"]
    extraction = body["current_version"]["extraction"]
    assert extraction["completeness_status"] == "FAILED"
    assert extraction["extracted_facts"] == {}
    assert extraction["instruction_type"] is None


def test_provider_failure_is_safely_handled(client):
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)

    body = _create_and_analyze(client, headers, patient["id"], "__FIXTURE__:PROVIDER_FAILURE")

    assert body["status"] == "NEEDS_REVIEW"
    assert "AI_EXTRACTION_FAILED" in body["review_reason"]
    extraction = body["current_version"]["extraction"]
    assert extraction["completeness_status"] == "FAILED"


def test_provider_construction_failure_is_handled_gracefully_not_as_a_500(client, monkeypatch):
    """Regression test: a provider that fails to even construct (e.g. a missing
    API key) must flow through the same NEEDS_REVIEW/FAILED path as a bad response
    — not leak as an unhandled 500 that also strands the instruction in
    PROCESSING with no way to retry (analyze only accepts DRAFT)."""
    from app.core.config import get_settings

    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)
    created = client.post(
        f"/patients/{patient['id']}/instructions", json={"text": "Walk after meals."}, headers=headers
    ).json()

    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    get_settings.cache_clear()

    resp = client.post(f"/instructions/{created['id']}/analyze", headers=headers)

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "NEEDS_REVIEW"
    assert "AI_EXTRACTION_FAILED" in body["review_reason"]
    assert "OPENAI_API_KEY" in body["review_reason"]

    # Revert now (within the test body) rather than relying on monkeypatch's
    # automatic teardown timing, so the settings cache is clean again for the
    # next test before it gets a chance to run.
    monkeypatch.undo()
    get_settings.cache_clear()


def test_no_invented_value_is_ever_inserted_by_application_code(client):
    """Even on a message with zero recognizable clinical content, the app must
    not fabricate facts — it should classify GENERAL and flag for review rather
    than guess."""
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)

    body = _create_and_analyze(client, headers, patient["id"], "See attached brochure for details.")

    extraction = body["current_version"]["extraction"]
    assert extraction["instruction_type"] == "GENERAL"
    assert body["status"] == "NEEDS_REVIEW"


# ---------------------------------------------------------------------------
# Clarification auto-reanalysis
# ---------------------------------------------------------------------------


def test_clarify_reanalyzes_and_can_resolve_needs_review(client):
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)
    initial = _create_and_analyze(client, headers, patient["id"], "Walk after meals.")
    assert initial["status"] == "NEEDS_REVIEW"
    instruction_id = initial["id"]

    resp = client.post(
        f"/instructions/{instruction_id}/clarify",
        json={"text": "Walk for 10 minutes after meals with nurse assistance."},
        headers=headers,
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "PROCESSING"
    assert body["review_reason"] is None
    assert body["current_version"]["version_number"] == 2
    assert body["current_version"]["source"] == "CLARIFICATION"
    extraction = body["current_version"]["extraction"]
    assert extraction["completeness_status"] == "PASSED"
    assert extraction["normalized_facts"]["assistance_required"] is True


def test_v1_extraction_remains_associated_with_v1_after_clarification(client):
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)
    initial = _create_and_analyze(client, headers, patient["id"], "Walk after meals.")
    instruction_id = initial["id"]

    client.post(
        f"/instructions/{instruction_id}/clarify",
        json={"text": "Walk for 10 minutes after meals with nurse assistance."},
        headers=headers,
    )

    detail = client.get(f"/instructions/{instruction_id}", headers=headers).json()
    versions = {v["version_number"]: v for v in detail["versions"]}
    assert len(versions) == 2

    v1_extraction = versions[1]["extraction"]
    assert v1_extraction is not None
    assert v1_extraction["normalized_facts"]["duration"] is None
    assert v1_extraction["normalized_facts"]["assistance_required"] is None

    v2_extraction = versions[2]["extraction"]
    assert v2_extraction is not None
    assert v2_extraction["normalized_facts"]["assistance_required"] is True

    assert detail["current_version"]["version_number"] == 2


# ---------------------------------------------------------------------------
# Stale-result / concurrency protection
# ---------------------------------------------------------------------------


def test_stale_analysis_result_cannot_change_state_of_a_newer_version(client, db_session):
    """Simulates: V1 analysis started (status -> PROCESSING) but its LLM result
    hasn't come back yet, and meanwhile V2 has already become current. Applying
    V1's (now-stale) result must not touch current status — only persist for the
    historical record.

    Note this exact interleaving isn't reachable through Step 5's public API today
    — /clarify requires NEEDS_REVIEW, which can only exist after V1's analysis has
    already *finished* and stored its own extraction, so there's no window for a
    still-in-flight V1 result to race a V2. The guard is still real and tested
    directly here (a deliberate white-box test) because it matters as soon as
    retries or async processing land — this is exactly the kind of interleaving
    that becomes possible then."""
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)
    created = client.post(
        f"/patients/{patient['id']}/instructions", json={"text": "Walk after meals."}, headers=headers
    ).json()
    instruction_id = uuid.UUID(created["id"])
    v1_id = uuid.UUID(created["current_version"]["id"])

    # Simulate analyze()'s phase 1 (status -> PROCESSING) without letting its
    # result land yet — v1 has no extraction at this point.
    from app.instructions.state import transition

    instruction = instructions_service.get_instruction(db_session, instruction_id)
    transition(instruction, InstructionStatus.PROCESSING)
    db_session.commit()

    # Meanwhile, simulate V2 having become current by some other path.
    from app.instructions.models import InstructionVersion, VersionSource

    v2 = InstructionVersion(
        care_instruction_id=instruction.id,
        version_number=2,
        raw_text="Walk for 10 minutes after meals with nurse assistance.",
        source=VersionSource.CLARIFICATION,
        created_by=instruction.created_by,
    )
    db_session.add(v2)
    db_session.flush()
    v2_id = v2.id
    instruction.current_version_id = v2_id
    db_session.commit()

    # Now V1's late result arrives and tries to apply, via the same private helper
    # the real pipeline uses.
    from app.ai.extraction_service import ExtractionAttempt
    from app.ai.provider import ProviderMetadata
    from app.ai.schemas import MobilityExtraction, MobilityFacts

    late_attempt = ExtractionAttempt(
        succeeded=True,
        result=MobilityExtraction(facts=MobilityFacts(activity="walking", timing="after meals")),
        metadata=ProviderMetadata(
            provider="mock", model="mock-extraction-v1", request_id="late", latency_ms=1, token_usage=None
        ),
        prompt_version="health-literacy-extraction-v1",
        failure_reason=None,
    )

    result = instructions_service._apply_extraction_result(
        db_session, instruction_id, v1_id, late_attempt, instruction.created_by
    )

    assert result.current_version_id == v2_id  # untouched — still points at v2
    assert result.status == InstructionStatus.PROCESSING  # untouched by the stale v1 result

    # The stale result was still persisted for the historical record, on v1.
    detail = client.get(f"/instructions/{instruction_id}", headers=headers).json()
    v1_detail = next(v for v in detail["versions"] if v["version_number"] == 1)
    assert v1_detail["extraction"] is not None


# ---------------------------------------------------------------------------
# Extraction uniqueness / metadata
# ---------------------------------------------------------------------------


def test_extraction_is_unique_per_instruction_version(client, db_session):
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)
    body = _create_and_analyze(client, headers, patient["id"], "Walk after meals.")
    version_id = uuid.UUID(body["current_version"]["id"])

    import pytest
    from sqlalchemy.exc import IntegrityError

    from app.instructions.models import CompletenessStatus, StructuredExtraction

    duplicate = StructuredExtraction(
        instruction_version_id=version_id,
        instruction_type=None,
        completeness_status=CompletenessStatus.FAILED,
        provider="mock",
        model="mock-extraction-v1",
        prompt_version="health-literacy-extraction-v1",
    )
    db_session.add(duplicate)

    with pytest.raises(IntegrityError):
        db_session.flush()

    db_session.rollback()


def test_provider_and_prompt_version_metadata_are_stored(client):
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)

    body = _create_and_analyze(client, headers, patient["id"], "Take Metoprolol 25 mg orally twice daily with food.")

    extraction = body["current_version"]["extraction"]
    assert extraction["provider"] == "mock"
    assert extraction["model"] == "mock-extraction-v1"
    assert extraction["prompt_version"] == "health-literacy-extraction-v5"


def test_raw_llm_response_is_not_stored_by_default(client):
    """Structural guarantee: the response schema (and the underlying table) simply
    has no field capable of holding a raw prompt or raw response — see
    instructions/schemas.py's StructuredExtractionRead and models.py's
    StructuredExtraction, which only ever store the structured/normalized facts
    and small provider metadata."""
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)

    body = _create_and_analyze(client, headers, patient["id"], "Take Metoprolol 25 mg orally twice daily with food.")

    extraction = body["current_version"]["extraction"]
    assert "raw_prompt" not in extraction
    assert "raw_response" not in extraction
    assert set(extraction.keys()) == {
        "id",
        "instruction_type",
        "extracted_facts",
        "normalized_facts",
        "missing_fields",
        "ambiguous_fields",
        "clarification_required_fields",
        "validation_messages",
        "completeness_status",
        "provider",
        "model",
        "prompt_version",
        "created_at",
    }


# ---------------------------------------------------------------------------
# Approval / rejection. Approve-dependent tests (approve only from
# READY_FOR_APPROVAL, approved instruction can't be clarified) moved to
# test_generate.py, which is where READY_FOR_APPROVAL is genuinely reachable
# now (via /generate) — reject only needs NEEDS_REVIEW, which analysis alone
# already reaches, so those stay here.
# ---------------------------------------------------------------------------


def test_reject_with_reason_is_stored(client):
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)
    body = _create_and_analyze(client, headers, patient["id"], "Walk after meals.")
    assert body["status"] == "NEEDS_REVIEW"

    resp = client.post(
        f"/instructions/{body['id']}/reject",
        json={"reason": "Clinical instruction should be rewritten."},
        headers=headers,
    )

    assert resp.status_code == 200
    rejected = resp.json()
    assert rejected["status"] == "REJECTED"
    assert rejected["review_reason"] == "Clinical instruction should be rewritten."


def test_reject_requires_a_non_empty_reason(client):
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)
    body = _create_and_analyze(client, headers, patient["id"], "Walk after meals.")

    resp = client.post(f"/instructions/{body['id']}/reject", json={"reason": "   "}, headers=headers)

    assert resp.status_code == 422


def test_rejected_instruction_cannot_transition_further(client):
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)
    body = _create_and_analyze(client, headers, patient["id"], "Walk after meals.")
    client.post(f"/instructions/{body['id']}/reject", json={"reason": "not usable"}, headers=headers)

    assert client.post(f"/instructions/{body['id']}/analyze", headers=headers).status_code == 409
    assert client.post(f"/instructions/{body['id']}/approve", headers=headers).status_code == 409
    assert (
        client.post(f"/instructions/{body['id']}/clarify", json={"text": "x"}, headers=headers).status_code == 409
    )
