"""Patient chat v3: the two hard, deterministic pre-LLM gates (emergency,
treatment-change), the grounded/web-search-assisted reply path via the mock
provider's fixture markers, and that a stopped/completed medication never
leaks into the chat's care-plan context — see
app/patient_chat/service.py for the gates themselves and
PATIENT_CHAT_SYSTEM_PROMPT for why web search is trusted-source-only."""

MEDICATION_TEXT = "Take Metoprolol 25 mg orally twice daily with food."


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
    approved = client.post(f"/instructions/{created['id']}/approve", headers=headers).json()
    assert approved["status"] == "APPROVED"
    return created


def _create_care_link(client, headers, patient_id) -> str:
    resp = client.post(f"/patients/{patient_id}/care-access-tokens", headers=headers)
    assert resp.status_code == 201
    return resp.json()["token"]


def test_emergency_message_never_reaches_the_llm(client):
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)
    _create_analyze_generate_approve(client, headers, patient["id"], MEDICATION_TEXT)
    token = _create_care_link(client, headers, patient["id"])

    resp = client.post("/care-plan/chat", json={"token": token, "text": "I have severe chest pain"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["patient_message"]["emergency_flagged"] is True
    assert "emergency" in body["assistant_message"]["text"].lower()
    assert body["assistant_message"]["web_search_used"] is False


def test_treatment_change_request_is_redirected_not_answered(client):
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)
    _create_analyze_generate_approve(client, headers, patient["id"], MEDICATION_TEXT)
    token = _create_care_link(client, headers, patient["id"])

    resp = client.post("/care-plan/chat", json={"token": token, "text": "Can I just double my dose today?"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["patient_message"]["redirect_flagged"] is True
    assert "care team" in body["assistant_message"]["text"].lower()


def test_ordinary_question_gets_a_grounded_reply(client):
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)
    _create_analyze_generate_approve(client, headers, patient["id"], MEDICATION_TEXT)
    token = _create_care_link(client, headers, patient["id"])

    resp = client.post("/care-plan/chat", json={"token": token, "text": "What is this medicine for?"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["patient_message"]["emergency_flagged"] is False
    assert body["patient_message"]["redirect_flagged"] is False
    assert "metoprolol" in body["assistant_message"]["text"].lower()
    assert body["assistant_message"]["web_search_used"] is False


def test_web_search_marker_sets_web_search_used_and_records_audit_event(client):
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)
    _create_analyze_generate_approve(client, headers, patient["id"], MEDICATION_TEXT)
    token = _create_care_link(client, headers, patient["id"])

    resp = client.post("/care-plan/chat", json={"token": token, "text": "__WEB_SEARCH_QUESTION__ tell me more"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["assistant_message"]["web_search_used"] is True

    audit_resp = client.get(f"/patients/{patient['id']}/audit", headers=headers)
    event_types = [e["event_type"] for e in audit_resp.json()["results"]]
    assert "PATIENT_CHAT_WEB_SEARCH_USED" in event_types


def test_ungrounded_question_gets_the_fixed_decline(client):
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)
    _create_analyze_generate_approve(client, headers, patient["id"], MEDICATION_TEXT)
    token = _create_care_link(client, headers, patient["id"])

    resp = client.post("/care-plan/chat", json={"token": token, "text": "__UNGROUNDED_QUESTION__ what about this?"})

    assert resp.status_code == 200
    assert "ask your doctor or pharmacist" in resp.json()["assistant_message"]["text"].lower()


def test_chat_history_persists_across_requests(client):
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)
    _create_analyze_generate_approve(client, headers, patient["id"], MEDICATION_TEXT)
    token = _create_care_link(client, headers, patient["id"])

    client.post("/care-plan/chat", json={"token": token, "text": "What is this medicine for?"})
    history_resp = client.get("/care-plan/chat", params={"token": token})

    assert history_resp.status_code == 200
    messages = history_resp.json()["messages"]
    assert len(messages) == 2  # patient turn + assistant turn
    assert messages[0]["role"] == "PATIENT"
    assert messages[1]["role"] == "ASSISTANT"


def test_clinician_can_read_the_same_transcript(client):
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)
    _create_analyze_generate_approve(client, headers, patient["id"], MEDICATION_TEXT)
    token = _create_care_link(client, headers, patient["id"])

    client.post("/care-plan/chat", json={"token": token, "text": "What is this medicine for?"})
    clinician_resp = client.get(f"/patients/{patient['id']}/chat", headers=headers)

    assert clinician_resp.status_code == 200
    assert len(clinician_resp.json()["messages"]) == 2


def test_invalid_token_is_rejected(client):
    resp = client.post("/care-plan/chat", json={"token": "not-a-real-token", "text": "hello"})
    assert resp.status_code == 401


def test_stopped_medication_excluded_from_chat_context(client):
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)
    approved = _create_analyze_generate_approve(client, headers, patient["id"], MEDICATION_TEXT)
    client.patch(f"/instructions/{approved['id']}/clinical-status", json={"status": "STOPPED"}, headers=headers)
    token = _create_care_link(client, headers, patient["id"])

    resp = client.post("/care-plan/chat", json={"token": token, "text": "What medicines am I currently taking?"})

    assert resp.status_code == 200
    # The mock provider echoes back the care-plan summary it was given —
    # a stopped medication must not appear in it.
    assert "metoprolol" not in resp.json()["assistant_message"]["text"].lower()
