import uuid
from datetime import datetime, timedelta, timezone

from app.patient_access.models import PatientCareAccessToken

MEDICATION_TEXT = "Take Metoprolol 25 mg orally twice daily with food."
MOBILITY_TEXT = "Walk for 10 minutes after meals with nurse assistance."


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


def _with_fixture(text: str, fixture: str) -> str:
    return f"{text} __FIXTURE__:{fixture}"


def _create_analyze_generate_approve(client, headers, patient_id, text) -> dict:
    created = client.post(f"/patients/{patient_id}/instructions", json={"text": text}, headers=headers).json()
    client.post(f"/instructions/{created['id']}/analyze", headers=headers)
    generated = client.post(f"/instructions/{created['id']}/generate", headers=headers).json()
    assert generated["status"] == "READY_FOR_APPROVAL", generated
    approved = client.post(f"/instructions/{created['id']}/approve", headers=headers).json()
    assert approved["status"] == "APPROVED"
    return created


def _create_care_link(client, headers, patient_id) -> str:
    resp = client.post(f"/patients/{patient_id}/care-access-tokens", headers=headers)
    assert resp.status_code == 201
    return resp.json()["token"]


# ---------------------------------------------------------------------------
# Token issuance / security
# ---------------------------------------------------------------------------


def test_secure_care_token_is_generated(client):
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)

    resp = client.post(f"/patients/{patient['id']}/care-access-tokens", headers=headers)

    assert resp.status_code == 201
    body = resp.json()
    assert len(body["token"]) >= 32  # base64url of 256 bits is long — a real random token, not a short code
    assert body["expires_at"] is not None


def test_raw_token_is_not_stored(client, db_session):
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)

    raw_token = _create_care_link(client, headers, patient["id"])

    record = db_session.query(PatientCareAccessToken).filter(PatientCareAccessToken.patient_id == uuid.UUID(patient["id"])).one()
    assert record.token_hash != raw_token
    assert raw_token not in record.token_hash
    assert len(record.token_hash) == 64  # sha256 hex digest


def test_token_creation_requires_clinician_auth(client):
    patient_id = uuid.uuid4()
    resp = client.post(f"/patients/{patient_id}/care-access-tokens")
    assert resp.status_code == 401


def test_invalid_token_is_rejected(client):
    resp = client.get("/care-plan", params={"token": "not-a-real-token"})
    assert resp.status_code == 401


def test_audio_endpoint_rejects_invalid_token_before_any_synthesis(client):
    """The token gate must run before ever calling out to the TTS service —
    this must 401 without requiring network access."""
    resp = client.post(
        "/care-plan/audio",
        json={"token": "not-a-real-token", "text": "hello", "language": "ENGLISH"},
    )
    assert resp.status_code == 401


def test_audio_endpoint_rejects_revoked_token(client, db_session):
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)
    raw_token = _create_care_link(client, headers, patient["id"])

    record = db_session.query(PatientCareAccessToken).filter(
        PatientCareAccessToken.patient_id == uuid.UUID(patient["id"])
    ).one()
    record.revoked_at = datetime.now(timezone.utc)
    db_session.commit()

    resp = client.post(
        "/care-plan/audio",
        json={"token": raw_token, "text": "hello", "language": "ENGLISH"},
    )
    assert resp.status_code == 401


def test_audio_endpoint_rejects_text_over_length_limit(client):
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)
    raw_token = _create_care_link(client, headers, patient["id"])

    resp = client.post(
        "/care-plan/audio",
        json={"token": raw_token, "text": "x" * 2001, "language": "ENGLISH"},
    )
    assert resp.status_code == 422


def test_expired_token_is_rejected(client, db_session):
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)
    raw_token = _create_care_link(client, headers, patient["id"])

    record = db_session.query(PatientCareAccessToken).filter(PatientCareAccessToken.patient_id == uuid.UUID(patient["id"])).one()
    record.expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
    db_session.commit()

    resp = client.get("/care-plan", params={"token": raw_token})
    assert resp.status_code == 401


def test_revoked_token_is_rejected(client, db_session):
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)
    raw_token = _create_care_link(client, headers, patient["id"])

    record = db_session.query(PatientCareAccessToken).filter(PatientCareAccessToken.patient_id == uuid.UUID(patient["id"])).one()
    record.revoked_at = datetime.now(timezone.utc)
    db_session.commit()

    resp = client.get("/care-plan", params={"token": raw_token})
    assert resp.status_code == 401


def test_care_plan_endpoint_requires_no_clinician_auth():
    """Not gated by the JWT auth dependency at all — token possession alone
    grants access, matching how a patient would actually reach it."""
    import inspect

    from app.patient_access.router import get_care_plan

    params = inspect.signature(get_care_plan).parameters
    assert "current_user" not in params


# ---------------------------------------------------------------------------
# Content minimality / visibility rules
# ---------------------------------------------------------------------------


def test_patient_endpoint_only_returns_approved_content(client):
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)
    approved = _create_analyze_generate_approve(client, headers, patient["id"], MEDICATION_TEXT)
    # A second instruction that never gets approved.
    client.post(f"/patients/{patient['id']}/instructions", json={"text": "Take Lisinopril 10 mg orally once daily."}, headers=headers)

    raw_token = _create_care_link(client, headers, patient["id"])
    resp = client.get("/care-plan", params={"token": raw_token})

    assert resp.status_code == 200
    body = resp.json()
    assert len(body["instructions"]) == 1
    assert "Metoprolol" in body["instructions"][0]["text_by_language"]["ENGLISH"]
    assert body["patient_first_name"] == "John"


def test_failed_generated_output_is_never_exposed(client):
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)
    # This instruction never reaches APPROVED (generation fails validation).
    created = client.post(
        f"/patients/{patient['id']}/instructions",
        json={"text": _with_fixture(MEDICATION_TEXT, "GENERATION_CHANGED_DOSE")},
        headers=headers,
    ).json()
    client.post(f"/instructions/{created['id']}/analyze", headers=headers)
    client.post(f"/instructions/{created['id']}/generate", headers=headers)

    raw_token = _create_care_link(client, headers, patient["id"])
    resp = client.get("/care-plan", params={"token": raw_token})

    assert resp.status_code == 200
    assert resp.json()["instructions"] == []


def test_failed_translation_is_never_exposed(client):
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers, preferred_language="ENGLISH")
    created = _create_analyze_generate_approve(
        client, headers, patient["id"], _with_fixture(MEDICATION_TEXT, "TRANSLATION_CHANGED_DOSE")
    )
    client.post(f"/instructions/{created['id']}/translations", json={"languages": ["TELUGU"]}, headers=headers)

    raw_token = _create_care_link(client, headers, patient["id"])
    resp = client.get("/care-plan", params={"token": raw_token})

    body = resp.json()
    text_by_language = body["instructions"][0]["text_by_language"]
    assert "ENGLISH" in text_by_language
    assert "TELUGU" not in text_by_language  # failed translation withheld entirely


def test_response_is_minimal_no_internal_fields(client):
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)
    _create_analyze_generate_approve(client, headers, patient["id"], MEDICATION_TEXT)
    raw_token = _create_care_link(client, headers, patient["id"])

    resp = client.get("/care-plan", params={"token": raw_token})
    body = resp.json()

    assert set(body.keys()) == {
        "patient_first_name",
        "preferred_language",
        "instructions",
        "past_medications",
        "conditions",
        "allergies",
    }
    instruction_view = body["instructions"][0]
    assert set(instruction_view.keys()) == {"id", "instruction_type", "text_by_language", "approved_at", "why", "past_reason"}
    # `id` is deliberately present (an opaque reference, needed by the
    # comprehension-feedback endpoint) — everything else stays absent: no
    # patient_id, no provider/model metadata, no validation internals.
    assert "provider" not in instruction_view
    assert "validation_diff" not in instruction_view


# ---------------------------------------------------------------------------
# Preferred-language defaulting (frontend concern, but the data must support it)
# ---------------------------------------------------------------------------


def test_preferred_telugu_available_when_translation_passed(client):
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers, preferred_language="TELUGU")
    created = _create_analyze_generate_approve(client, headers, patient["id"], MEDICATION_TEXT)
    client.post(f"/instructions/{created['id']}/translations", json={"languages": ["TELUGU"]}, headers=headers)

    raw_token = _create_care_link(client, headers, patient["id"])
    resp = client.get("/care-plan", params={"token": raw_token})

    body = resp.json()
    assert body["preferred_language"] == "TELUGU"
    assert "TELUGU" in body["instructions"][0]["text_by_language"]


def test_preferred_telugu_falls_back_to_english_when_unavailable(client):
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers, preferred_language="TELUGU")
    created = _create_analyze_generate_approve(client, headers, patient["id"], MEDICATION_TEXT)
    # Telugu never requested/translated at all.

    raw_token = _create_care_link(client, headers, patient["id"])
    resp = client.get("/care-plan", params={"token": raw_token})

    body = resp.json()
    assert body["preferred_language"] == "TELUGU"
    text_by_language = body["instructions"][0]["text_by_language"]
    assert "TELUGU" not in text_by_language
    assert "ENGLISH" in text_by_language  # the frontend falls back to this


# ---------------------------------------------------------------------------
# Documented conditions + curated visual explainer (see
# app/reference/condition_explainers.py — a safe, non-AI-generated
# alternative to generating disease/anatomy images live).
# ---------------------------------------------------------------------------


def test_documented_condition_with_curated_explainer_is_surfaced(client):
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)
    _create_analyze_generate_approve(client, headers, patient["id"], MEDICATION_TEXT)
    client.post(f"/patients/{patient['id']}/conditions", json={"condition_name": "Hypertension"}, headers=headers)
    raw_token = _create_care_link(client, headers, patient["id"])

    resp = client.get("/care-plan", params={"token": raw_token})

    body = resp.json()
    assert len(body["conditions"]) == 1
    condition = body["conditions"][0]
    assert condition["condition_name"] == "Hypertension"
    assert condition["explainer"] is not None
    assert "blood pressure" in condition["explainer"]["what_it_is"].lower()
    assert condition["explainer"]["how_it_develops"]
    assert condition["explainer"]["where_it_affects"]


def test_documented_condition_without_curated_explainer_still_appears_by_name(client):
    """Never hidden just because no explainer exists — and never a guessed
    explainer either (see lookup_condition_explainer's exact-match-only
    rule)."""
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)
    _create_analyze_generate_approve(client, headers, patient["id"], MEDICATION_TEXT)
    client.post(
        f"/patients/{patient['id']}/conditions",
        json={"condition_name": "A rare condition not in the curated table"},
        headers=headers,
    )
    raw_token = _create_care_link(client, headers, patient["id"])

    resp = client.get("/care-plan", params={"token": raw_token})

    body = resp.json()
    assert len(body["conditions"]) == 1
    assert body["conditions"][0]["condition_name"] == "A rare condition not in the curated table"
    assert body["conditions"][0]["explainer"] is None


def test_no_documented_conditions_returns_empty_list(client):
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)
    _create_analyze_generate_approve(client, headers, patient["id"], MEDICATION_TEXT)
    raw_token = _create_care_link(client, headers, patient["id"])

    resp = client.get("/care-plan", params={"token": raw_token})

    assert resp.json()["conditions"] == []


# ---------------------------------------------------------------------------
# Patient-facing allergy display — the patient is the one person positioned to
# notice the list is wrong or incomplete (gap analysis item 10).
# ---------------------------------------------------------------------------


def test_documented_allergies_are_shown_to_the_patient(client):
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)
    _create_analyze_generate_approve(client, headers, patient["id"], MEDICATION_TEXT)
    client.post(
        f"/patients/{patient['id']}/allergies",
        json={"allergen": "Penicillin", "reaction": "rash", "severity": "moderate"},
        headers=headers,
    )
    raw_token = _create_care_link(client, headers, patient["id"])

    body = client.get("/care-plan", params={"token": raw_token}).json()

    assert len(body["allergies"]) == 1
    assert body["allergies"][0] == {"allergen": "Penicillin", "reaction": "rash", "severity": "moderate"}


def test_allergy_without_reaction_or_severity_is_still_shown(client):
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)
    _create_analyze_generate_approve(client, headers, patient["id"], MEDICATION_TEXT)
    client.post(f"/patients/{patient['id']}/allergies", json={"allergen": "Latex"}, headers=headers)
    raw_token = _create_care_link(client, headers, patient["id"])

    body = client.get("/care-plan", params={"token": raw_token}).json()

    assert body["allergies"][0]["allergen"] == "Latex"
    assert body["allergies"][0]["reaction"] is None


def test_patient_with_no_allergies_gets_an_empty_list(client):
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)
    _create_analyze_generate_approve(client, headers, patient["id"], MEDICATION_TEXT)
    raw_token = _create_care_link(client, headers, patient["id"])

    assert client.get("/care-plan", params={"token": raw_token}).json()["allergies"] == []


def test_allergies_are_scoped_to_the_token_s_own_patient(client):
    """A care link must never leak another patient's allergy list."""
    headers = _register_and_login(client)
    patient_a = _create_active_patient(client, headers, first_name="Ayla")
    _create_analyze_generate_approve(client, headers, patient_a["id"], MEDICATION_TEXT)
    client.post(f"/patients/{patient_a['id']}/allergies", json={"allergen": "Penicillin"}, headers=headers)

    patient_b = _create_active_patient(client, headers, first_name="Bruno")
    _create_analyze_generate_approve(client, headers, patient_b["id"], MEDICATION_TEXT)
    token_b = _create_care_link(client, headers, patient_b["id"])

    assert client.get("/care-plan", params={"token": token_b}).json()["allergies"] == []


# ---------------------------------------------------------------------------
# A stopped medication and a finished course both appear under past
# medications, but they ask opposite things of the patient. The API must let
# the page tell them apart.
# ---------------------------------------------------------------------------


def test_stopped_and_completed_medications_are_distinguishable(client):
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)
    stopped = _create_analyze_generate_approve(client, headers, patient["id"], MEDICATION_TEXT)
    completed = _create_analyze_generate_approve(client, headers, patient["id"], MEDICATION_TEXT)
    client.patch(f"/instructions/{stopped['id']}/clinical-status", json={"status": "STOPPED"}, headers=headers)
    client.patch(f"/instructions/{completed['id']}/clinical-status", json={"status": "COMPLETED"}, headers=headers)
    raw_token = _create_care_link(client, headers, patient["id"])

    body = client.get("/care-plan", params={"token": raw_token}).json()

    reasons = sorted(item["past_reason"] for item in body["past_medications"])
    assert reasons == ["COMPLETED", "STOPPED"]


def test_active_medication_has_no_past_reason(client):
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)
    _create_analyze_generate_approve(client, headers, patient["id"], MEDICATION_TEXT)
    raw_token = _create_care_link(client, headers, patient["id"])

    body = client.get("/care-plan", params={"token": raw_token}).json()

    assert body["instructions"][0]["past_reason"] is None
