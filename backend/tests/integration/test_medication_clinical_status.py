"""Integration tests for the encounter-aware medication lifecycle:
CareInstruction.clinical_status (ACTIVE/COMPLETED/STOPPED), scoped to
MEDICATION-type instructions only, and its effect on the patient-facing
current/past medications split. See app/instructions/models.py's
ClinicalStatus docstring for the safety rules this proves."""

MEDICATION_TEXT = "Take Lisinopril 10 mg orally once daily in the morning."
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


def _create_analyze_generate_approve(client, headers, patient_id, text) -> dict:
    created = client.post(f"/patients/{patient_id}/instructions", json={"text": text}, headers=headers).json()
    client.post(f"/instructions/{created['id']}/analyze", headers=headers)
    generated = client.post(f"/instructions/{created['id']}/generate", headers=headers).json()
    assert generated["status"] == "READY_FOR_APPROVAL", generated
    approved = client.post(f"/instructions/{created['id']}/approve", headers=headers).json()
    assert approved["status"] == "APPROVED"
    return approved


def _create_care_link(client, headers, patient_id) -> str:
    resp = client.post(f"/patients/{patient_id}/care-access-tokens", headers=headers)
    assert resp.status_code == 201
    return resp.json()["token"]


# ---------------------------------------------------------------------------
# approve() sets clinical_status only for MEDICATION
# ---------------------------------------------------------------------------


def test_approving_a_medication_instruction_sets_clinical_status_active(client):
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)

    approved = _create_analyze_generate_approve(client, headers, patient["id"], MEDICATION_TEXT)

    assert approved["clinical_status"] == "ACTIVE"
    assert approved["clinical_start_date"] is not None
    assert approved["clinical_end_date"] is None


def test_approving_a_mobility_instruction_never_sets_clinical_status(client):
    """The core safety rule of this feature: a non-medication instruction
    must never carry medication-lifecycle semantics, ever."""
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)

    approved = _create_analyze_generate_approve(client, headers, patient["id"], MOBILITY_TEXT)

    assert approved["clinical_status"] is None
    assert approved["clinical_start_date"] is None
    assert approved["clinical_end_date"] is None


# ---------------------------------------------------------------------------
# PATCH /instructions/{id}/clinical-status
# ---------------------------------------------------------------------------


def test_clinician_can_mark_a_medication_stopped(client):
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)
    approved = _create_analyze_generate_approve(client, headers, patient["id"], MEDICATION_TEXT)

    resp = client.patch(
        f"/instructions/{approved['id']}/clinical-status", json={"status": "STOPPED"}, headers=headers
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["clinical_status"] == "STOPPED"
    assert body["clinical_end_date"] is not None


def test_clinician_can_mark_a_medication_completed(client):
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)
    approved = _create_analyze_generate_approve(client, headers, patient["id"], MEDICATION_TEXT)

    resp = client.patch(
        f"/instructions/{approved['id']}/clinical-status", json={"status": "COMPLETED"}, headers=headers
    )

    assert resp.status_code == 200
    assert resp.json()["clinical_status"] == "COMPLETED"


def test_clinical_status_change_is_rejected_for_non_medication_instruction(client):
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)
    approved = _create_analyze_generate_approve(client, headers, patient["id"], MOBILITY_TEXT)

    resp = client.patch(
        f"/instructions/{approved['id']}/clinical-status", json={"status": "STOPPED"}, headers=headers
    )

    assert resp.status_code == 422


def test_clinical_status_change_is_rejected_for_unapproved_medication(client):
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)
    created = client.post(
        f"/patients/{patient['id']}/instructions", json={"text": MEDICATION_TEXT}, headers=headers
    ).json()
    # Never analyzed/approved -- clinical_status is still None.

    resp = client.patch(
        f"/instructions/{created['id']}/clinical-status", json={"status": "STOPPED"}, headers=headers
    )

    assert resp.status_code == 422


def test_reactivating_a_stopped_medication_clears_end_date(client):
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)
    approved = _create_analyze_generate_approve(client, headers, patient["id"], MEDICATION_TEXT)
    client.patch(f"/instructions/{approved['id']}/clinical-status", json={"status": "STOPPED"}, headers=headers)

    resp = client.patch(
        f"/instructions/{approved['id']}/clinical-status", json={"status": "ACTIVE"}, headers=headers
    )

    assert resp.status_code == 200
    assert resp.json()["clinical_status"] == "ACTIVE"
    assert resp.json()["clinical_end_date"] is None


# ---------------------------------------------------------------------------
# Current vs. past medications on the patient care page
# ---------------------------------------------------------------------------


def test_current_medications_excludes_completed_and_stopped(client):
    """The exact demo scenario: Lisinopril + Naproxen ACTIVE, Amoxicillin
    COMPLETED — current medications list shows only the first two."""
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)

    lisinopril = _create_analyze_generate_approve(
        client, headers, patient["id"], "Take Lisinopril 10 mg orally once daily in the morning."
    )
    amoxicillin = _create_analyze_generate_approve(
        client, headers, patient["id"], "Take Amoxicillin 500 mg orally three times daily."
    )
    naproxen = _create_analyze_generate_approve(
        client, headers, patient["id"], "Take Naproxen 250 mg orally twice daily."
    )
    client.patch(f"/instructions/{amoxicillin['id']}/clinical-status", json={"status": "COMPLETED"}, headers=headers)

    token = _create_care_link(client, headers, patient["id"])
    care_plan = client.get("/care-plan", params={"token": token}).json()

    current_texts = " ".join(v["text_by_language"]["ENGLISH"] for v in care_plan["instructions"])
    past_texts = " ".join(v["text_by_language"]["ENGLISH"] for v in care_plan["past_medications"])
    assert "Lisinopril" in current_texts
    assert "Naproxen" in current_texts
    assert "Amoxicillin" not in current_texts
    assert "Amoxicillin" in past_texts


def test_mobility_instruction_always_shows_in_current_regardless_of_clinical_status(client):
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)
    _create_analyze_generate_approve(client, headers, patient["id"], MOBILITY_TEXT)

    token = _create_care_link(client, headers, patient["id"])
    care_plan = client.get("/care-plan", params={"token": token}).json()

    assert len(care_plan["instructions"]) == 1
    assert care_plan["past_medications"] == []


# ---------------------------------------------------------------------------
# Medication supersession: old STOPPED order must never leak into the new one
# ---------------------------------------------------------------------------


def test_superseded_medication_order_never_leaks_into_the_new_active_one(client):
    """Old: Metoprolol 25mg / Hypertension / STOPPED.
    New: Metoprolol 50mg / Arrhythmia / ACTIVE.
    The patient-facing explanation must reflect only the new order."""
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)

    old_order = _create_analyze_generate_approve(
        client, headers, patient["id"], "Take Metoprolol 25 mg orally twice daily for your hypertension."
    )
    client.patch(f"/instructions/{old_order['id']}/clinical-status", json={"status": "STOPPED"}, headers=headers)

    new_order = _create_analyze_generate_approve(
        client, headers, patient["id"], "Take Metoprolol 50 mg orally twice daily for your irregular heartbeat."
    )

    token = _create_care_link(client, headers, patient["id"])
    care_plan = client.get("/care-plan", params={"token": token}).json()

    assert len(care_plan["instructions"]) == 1
    current = care_plan["instructions"][0]
    assert "50 mg" in current["text_by_language"]["ENGLISH"]
    assert "25 mg" not in current["text_by_language"]["ENGLISH"]
    assert current["why"]["text"] == "your irregular heartbeat"

    past = care_plan["past_medications"]
    assert len(past) == 1
    assert "25 mg" in past[0]["text_by_language"]["ENGLISH"]
    assert past[0]["why"]["text"] == "your hypertension"


# ---------------------------------------------------------------------------
# Safety test: documented diagnoses must never be used to infer indication
# ---------------------------------------------------------------------------


def test_multiple_diagnoses_never_inferred_as_medication_indication(client):
    """Lisinopril's curated Tier 2/GENERAL reference text happens to mention
    both high blood pressure and heart failure — legitimately, as real,
    static pharmacology knowledge, unrelated to any specific patient. The
    safety property this proves isn't "the text never mentions a diagnosis
    the patient happens to have" (that would be an unreliable, coincidental
    check) — it's that the answer is the SAME static, curated text
    regardless of which diagnoses are on file, i.e. never DOCUMENTED
    (patient-specific), and never re-selected/tailored based on the
    patient's 2 documented diagnoses."""
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)
    client.post(f"/patients/{patient['id']}/conditions", json={"condition_name": "Hypertension"}, headers=headers)
    client.post(f"/patients/{patient['id']}/conditions", json={"condition_name": "Heart failure"}, headers=headers)

    # No stated reason -- indication is null on this order.
    _create_analyze_generate_approve(client, headers, patient["id"], "Take Lisinopril 10 mg orally once daily.")

    token = _create_care_link(client, headers, patient["id"])
    care_plan = client.get("/care-plan", params={"token": token}).json()

    why = care_plan["instructions"][0]["why"]
    assert why is not None
    assert why["tier"] == "GENERAL"
    assert why["text"] == "Commonly used to treat high blood pressure and heart failure."
    assert why["disclaimer"] is not None
