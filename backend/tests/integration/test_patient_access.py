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

    assert set(body.keys()) == {"patient_first_name", "preferred_language", "instructions", "past_medications"}
    instruction_view = body["instructions"][0]
    assert set(instruction_view.keys()) == {"id", "instruction_type", "text_by_language", "approved_at", "why"}
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
