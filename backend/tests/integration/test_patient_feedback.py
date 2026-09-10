"""Integration tests for the comprehension-feedback endpoint ("Did this
explanation help?") — see app/patient_feedback/models.py for why
HAS_QUESTION/ASK_CARE_TEAM surface to the clinician via the audit trail and
UNDERSTOOD doesn't."""

MEDICATION_TEXT = "Take Lisinopril 10 mg orally once daily in the morning for your high blood pressure."


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


def _create_analyze_generate_approve(client, headers, patient_id, text) -> dict:
    created = client.post(f"/patients/{patient_id}/instructions", json={"text": text}, headers=headers).json()
    client.post(f"/instructions/{created['id']}/analyze", headers=headers)
    generated = client.post(f"/instructions/{created['id']}/generate", headers=headers).json()
    assert generated["status"] == "READY_FOR_APPROVAL", generated
    client.post(f"/instructions/{created['id']}/approve", headers=headers)
    return created


def _create_care_link(client, headers, patient_id) -> str:
    resp = client.post(f"/patients/{patient_id}/care-access-tokens", headers=headers)
    assert resp.status_code == 201
    return resp.json()["token"]


def _setup_patient_with_care_link(client):
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)
    _create_analyze_generate_approve(client, headers, patient["id"], MEDICATION_TEXT)
    token = _create_care_link(client, headers, patient["id"])
    care_plan = client.get("/care-plan", params={"token": token}).json()
    instruction_id = care_plan["instructions"][0]["id"]
    return patient, token, headers, instruction_id


def test_understood_feedback_is_recorded(client):
    _patient, token, _headers, instruction_id = _setup_patient_with_care_link(client)

    resp = client.post(
        "/care-plan/feedback", json={"token": token, "instruction_id": instruction_id, "response": "UNDERSTOOD"}
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["response"] == "UNDERSTOOD"
    assert body["care_instruction_id"] == instruction_id


def test_has_question_feedback_surfaces_on_clinician_timeline(client):
    patient, token, headers, instruction_id = _setup_patient_with_care_link(client)

    resp = client.post(
        "/care-plan/feedback", json={"token": token, "instruction_id": instruction_id, "response": "HAS_QUESTION"}
    )
    assert resp.status_code == 200

    timeline = client.get(f"/patients/{patient['id']}/audit", headers=headers).json()
    event_types = [e["event_type"] for e in timeline["results"]]
    assert "PATIENT_COMPREHENSION_NEEDS_ATTENTION" in event_types


def test_ask_care_team_feedback_surfaces_on_clinician_timeline(client):
    patient, token, headers, instruction_id = _setup_patient_with_care_link(client)

    resp = client.post(
        "/care-plan/feedback", json={"token": token, "instruction_id": instruction_id, "response": "ASK_CARE_TEAM"}
    )
    assert resp.status_code == 200

    timeline = client.get(f"/patients/{patient['id']}/audit", headers=headers).json()
    event_types = [e["event_type"] for e in timeline["results"]]
    assert "PATIENT_COMPREHENSION_NEEDS_ATTENTION" in event_types


def test_understood_feedback_does_not_appear_on_timeline(client):
    patient, token, headers, instruction_id = _setup_patient_with_care_link(client)

    client.post("/care-plan/feedback", json={"token": token, "instruction_id": instruction_id, "response": "UNDERSTOOD"})

    timeline = client.get(f"/patients/{patient['id']}/audit", headers=headers).json()
    event_types = [e["event_type"] for e in timeline["results"]]
    assert "PATIENT_COMPREHENSION_NEEDS_ATTENTION" not in event_types


def test_invalid_token_is_rejected(client):
    resp = client.post(
        "/care-plan/feedback",
        json={"token": "not-a-real-token", "instruction_id": "00000000-0000-0000-0000-000000000000", "response": "UNDERSTOOD"},
    )

    assert resp.status_code == 401


def test_instruction_belonging_to_a_different_patient_is_rejected(client):
    headers = _register_and_login(client)
    patient_a = _create_active_patient(client, headers, first_name="PatientA")
    _create_analyze_generate_approve(client, headers, patient_a["id"], MEDICATION_TEXT)
    token_a = _create_care_link(client, headers, patient_a["id"])

    patient_b = _create_active_patient(client, headers, first_name="PatientB")
    _create_analyze_generate_approve(client, headers, patient_b["id"], MEDICATION_TEXT)
    token_b = _create_care_link(client, headers, patient_b["id"])
    care_plan_b = client.get("/care-plan", params={"token": token_b}).json()
    instruction_id_b = care_plan_b["instructions"][0]["id"]

    # Token for patient A, but referencing patient B's instruction.
    resp = client.post(
        "/care-plan/feedback", json={"token": token_a, "instruction_id": instruction_id_b, "response": "UNDERSTOOD"}
    )

    assert resp.status_code == 404
