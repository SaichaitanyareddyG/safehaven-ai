"""Integration tests for clinician voice dictation (see
MODULE_1_VOICE_DICTATION_DESIGN.md).

The central property under test is structural: /instructions/transcribe
returns a draft and creates NOTHING, so a transcript cannot become a clinical
order without the clinician submitting it through the ordinary creation
endpoint. That is what makes "the clinician reviewed it" unavoidable rather
than merely encouraged — no downstream validator can catch a transcription
error, because the transcript becomes the source of truth they all check
against."""


def _register_and_login(client, email="clinician@example.com", password="supersecret123"):
    client.post("/auth/register", json={"email": email, "password": password, "full_name": "Test Clinician"})
    login_resp = client.post("/auth/login", json={"email": email, "password": password})
    return {"Authorization": f"Bearer {login_resp.json()['access_token']}"}


def _create_active_patient(client, headers, **overrides) -> dict:
    payload = {
        "first_name": "John",
        "last_name": "Doe",
        "date_of_birth": "1950-01-01",
        "preferred_language": "ENGLISH",
    }
    payload.update(overrides)
    return client.post("/patients", json=payload, headers=headers).json()


def _transcribe(client, headers, audio: bytes, filename="dictation.webm", content_type="audio/webm"):
    return client.post(
        "/instructions/transcribe",
        files={"file": (filename, audio, content_type)},
        headers=headers,
    )


def test_transcribe_returns_a_draft_transcript(client):
    headers = _register_and_login(client)

    resp = _transcribe(client, headers, b"__FIXTURE_AUDIO__:CLEAN")

    assert resp.status_code == 200
    body = resp.json()
    assert "Metoprolol" in body["text"]
    assert body["warnings"] == []


def test_transcribe_creates_no_instruction(client):
    """The structural guarantee: transcription must leave the database
    untouched, so a transcript can never reach a patient's chart without the
    clinician submitting it themselves."""
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)

    _transcribe(client, headers, b"__FIXTURE_AUDIO__:CLEAN")

    instructions = client.get(f"/patients/{patient['id']}/instructions", headers=headers).json()
    assert instructions["total"] == 0


def test_transcribe_surfaces_dictation_safety_warnings(client):
    headers = _register_and_login(client)

    resp = _transcribe(client, headers, b"__FIXTURE_AUDIO__:TRAILING_ZERO")

    assert resp.status_code == 200
    body = resp.json()
    assert "25.0" in body["text"]
    assert [w["code"] for w in body["warnings"]] == ["TRAILING_ZERO"]
    assert body["warnings"][0]["excerpt"]


def test_transcribe_of_silence_returns_empty_text_not_a_guess(client):
    headers = _register_and_login(client)

    resp = _transcribe(client, headers, b"__FIXTURE_AUDIO__:SILENT")

    assert resp.status_code == 200
    assert resp.json()["text"] == ""


def test_transcribe_provider_failure_does_not_fabricate_a_transcript(client):
    headers = _register_and_login(client)

    resp = _transcribe(client, headers, b"__FIXTURE_AUDIO__:PROVIDER_FAILURE")

    assert resp.status_code == 502
    assert "type it" in resp.json()["detail"]


def test_transcribe_rejects_empty_audio(client):
    headers = _register_and_login(client)

    resp = _transcribe(client, headers, b"")

    assert resp.status_code == 400


def test_transcribe_rejects_oversized_audio(client):
    headers = _register_and_login(client)

    resp = _transcribe(client, headers, b"x" * (10 * 1024 * 1024 + 1))

    assert resp.status_code == 413


def test_transcribe_requires_authentication(client):
    resp = client.post("/instructions/transcribe", files={"file": ("d.webm", b"audio", "audio/webm")})

    assert resp.status_code == 401


def test_dictated_instruction_records_capture_method_and_audit_event(client, db_session):
    from app.instructions.models import CaptureMethod, CareInstruction

    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)

    created = client.post(
        f"/patients/{patient['id']}/instructions",
        json={"text": "Take Metoprolol Succinate ER 25 mg orally twice daily.", "dictated": True},
        headers=headers,
    ).json()

    instruction = db_session.get(CareInstruction, __import__("uuid").UUID(created["id"]))
    assert instruction.current_version.capture_method == CaptureMethod.DICTATED

    timeline = client.get(f"/patients/{patient['id']}/audit", headers=headers).json()
    assert "INSTRUCTION_DICTATED" in [e["event_type"] for e in timeline["results"]]


def test_typed_instruction_records_typed_and_no_dictation_event(client, db_session):
    from app.instructions.models import CaptureMethod, CareInstruction

    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)

    created = client.post(
        f"/patients/{patient['id']}/instructions",
        json={"text": "Take Metoprolol Succinate ER 25 mg orally twice daily."},
        headers=headers,
    ).json()

    instruction = db_session.get(CareInstruction, __import__("uuid").UUID(created["id"]))
    assert instruction.current_version.capture_method == CaptureMethod.TYPED

    timeline = client.get(f"/patients/{patient['id']}/audit", headers=headers).json()
    assert "INSTRUCTION_DICTATED" not in [e["event_type"] for e in timeline["results"]]
