"""Integration tests for encounters and their (nullable) link from
PatientCondition — see app/encounters/models.py for why encounter_id is
never used as a basis for medication-indication inference."""

import uuid


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


def test_create_and_list_encounters(client):
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)

    resp = client.post(
        f"/patients/{patient['id']}/encounters",
        json={"reason_for_visit": "Hypertension follow-up", "admission_date": "2026-01-10"},
        headers=headers,
    )

    assert resp.status_code == 201
    body = resp.json()
    uuid.UUID(body["id"])
    assert body["reason_for_visit"] == "Hypertension follow-up"
    assert body["admission_date"] == "2026-01-10"
    assert body["status"] == "OPEN"

    list_resp = client.get(f"/patients/{patient['id']}/encounters", headers=headers)
    assert list_resp.status_code == 200
    assert list_resp.json()["total"] == 1
    assert list_resp.json()["results"][0]["id"] == body["id"]


def test_encounter_can_be_created_closed_with_discharge_date(client):
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)

    resp = client.post(
        f"/patients/{patient['id']}/encounters",
        json={
            "reason_for_visit": "Bacterial infection",
            "admission_date": "2026-05-01",
            "discharge_date": "2026-05-03",
            "status": "CLOSED",
        },
        headers=headers,
    )

    assert resp.status_code == 201
    assert resp.json()["status"] == "CLOSED"
    assert resp.json()["discharge_date"] == "2026-05-03"


def test_multiple_encounters_are_returned_newest_first(client):
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)

    client.post(
        f"/patients/{patient['id']}/encounters",
        json={"reason_for_visit": "January visit", "admission_date": "2026-01-10"},
        headers=headers,
    )
    client.post(
        f"/patients/{patient['id']}/encounters",
        json={"reason_for_visit": "September visit", "admission_date": "2026-09-01"},
        headers=headers,
    )

    resp = client.get(f"/patients/{patient['id']}/encounters", headers=headers)

    results = resp.json()["results"]
    assert len(results) == 2
    assert results[0]["reason_for_visit"] == "September visit"
    assert results[1]["reason_for_visit"] == "January visit"


def test_encounters_require_existing_patient(client):
    headers = _register_and_login(client)

    resp = client.post(
        f"/patients/{uuid.uuid4()}/encounters",
        json={"admission_date": "2026-01-10"},
        headers=headers,
    )

    assert resp.status_code == 404


def test_condition_can_be_linked_to_an_encounter(client):
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)
    encounter = client.post(
        f"/patients/{patient['id']}/encounters",
        json={"reason_for_visit": "Hypertension follow-up", "admission_date": "2026-01-10"},
        headers=headers,
    ).json()

    resp = client.post(
        f"/patients/{patient['id']}/conditions",
        json={"condition_name": "Hypertension", "encounter_id": encounter["id"]},
        headers=headers,
    )

    assert resp.status_code == 201
    assert resp.json()["encounter_id"] == encounter["id"]


def test_condition_without_encounter_is_still_allowed(client):
    """The nullable case — a condition documented as general patient history,
    not tied to a specific visit. Must keep working exactly as before this
    change."""
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)

    resp = client.post(
        f"/patients/{patient['id']}/conditions",
        json={"condition_name": "Hypertension"},
        headers=headers,
    )

    assert resp.status_code == 201
    assert resp.json()["encounter_id"] is None
