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


# ---------------------------------------------------------------------------
# Teach-back (US_HOSPITAL_MARKET_STANDARDS_GAP_ANALYSIS.md item 9) — the
# patient explains the instruction back in their own words instead of only
# clicking a "yes, I understand" button.
# ---------------------------------------------------------------------------


def test_teach_back_with_correct_explanation_passes(client):
    """MEDICATION_TEXT is extracted (mock provider) as medication=Lisinopril,
    frequency='once daily', reason='your high blood pressure' — an
    explanation that touches all three should confirm all three and pass."""
    _patient, token, _headers, instruction_id = _setup_patient_with_care_link(client)

    resp = client.post(
        "/care-plan/teach-back",
        json={
            "token": token,
            "instruction_id": instruction_id,
            "response_text": "I take my Lisinopril once daily for my blood pressure.",
        },
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["passed"] is True
    assert body["missing_facts"] == []
    assert "medication_name" in body["confirmed_facts"]
    assert "timing" in body["confirmed_facts"]
    assert "reason" in body["confirmed_facts"]


def test_teach_back_missing_medication_name_flags_attention(client):
    patient, token, headers, instruction_id = _setup_patient_with_care_link(client)

    resp = client.post(
        "/care-plan/teach-back",
        json={
            "token": token,
            "instruction_id": instruction_id,
            "response_text": "I take a pill every morning for my blood pressure.",
        },
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["passed"] is False
    assert "medication_name" in body["missing_facts"]

    timeline = client.get(f"/patients/{patient['id']}/audit", headers=headers).json()
    event_types = [e["event_type"] for e in timeline["results"]]
    assert "PATIENT_TEACH_BACK_NEEDS_ATTENTION" in event_types


def test_teach_back_passing_response_does_not_appear_on_timeline(client):
    patient, token, headers, instruction_id = _setup_patient_with_care_link(client)

    client.post(
        "/care-plan/teach-back",
        json={
            "token": token,
            "instruction_id": instruction_id,
            "response_text": "Lisinopril once daily for my blood pressure.",
        },
    )

    timeline = client.get(f"/patients/{patient['id']}/audit", headers=headers).json()
    event_types = [e["event_type"] for e in timeline["results"]]
    assert "PATIENT_TEACH_BACK_NEEDS_ATTENTION" not in event_types


def test_teach_back_invalid_token_is_rejected(client):
    resp = client.post(
        "/care-plan/teach-back",
        json={
            "token": "not-a-real-token",
            "instruction_id": "00000000-0000-0000-0000-000000000000",
            "response_text": "anything",
        },
    )

    assert resp.status_code == 401


def test_teach_back_instruction_belonging_to_a_different_patient_is_rejected(client):
    headers = _register_and_login(client)
    patient_a = _create_active_patient(client, headers, first_name="PatientA")
    _create_analyze_generate_approve(client, headers, patient_a["id"], MEDICATION_TEXT)
    token_a = _create_care_link(client, headers, patient_a["id"])

    patient_b = _create_active_patient(client, headers, first_name="PatientB")
    _create_analyze_generate_approve(client, headers, patient_b["id"], MEDICATION_TEXT)
    token_b = _create_care_link(client, headers, patient_b["id"])
    care_plan_b = client.get("/care-plan", params={"token": token_b}).json()
    instruction_id_b = care_plan_b["instructions"][0]["id"]

    resp = client.post(
        "/care-plan/teach-back",
        json={"token": token_a, "instruction_id": instruction_id_b, "response_text": "anything"},
    )

    assert resp.status_code == 404
