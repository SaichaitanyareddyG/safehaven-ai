import uuid
from datetime import date, timedelta


def _register_and_login(client, email="clinician@example.com", password="supersecret123"):
    client.post("/auth/register", json={"email": email, "password": password, "full_name": "Test Clinician"})
    login_resp = client.post("/auth/login", json={"email": email, "password": password})
    token = login_resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _patient_payload(**overrides):
    payload = {
        "first_name": "John",
        "last_name": "Doe",
        "date_of_birth": "1950-01-01",
        "room_number": "204A",
        "preferred_language": "ENGLISH",
    }
    payload.update(overrides)
    return payload


def test_authenticated_clinician_creates_patient(client):
    headers = _register_and_login(client)

    response = client.post("/patients", json=_patient_payload(), headers=headers)

    assert response.status_code == 201
    body = response.json()
    assert body["patient_code"].startswith("P")
    assert body["first_name"] == "John"
    assert body["admission_status"] == "ACTIVE"
    assert "created_by" not in body
    uuid.UUID(body["id"])  # doesn't raise


def test_unauthenticated_request_is_rejected(client):
    response = client.post("/patients", json=_patient_payload())
    assert response.status_code == 401


def test_duplicate_patient_code_is_rejected_at_generation_level(client):
    # patient_code is server-generated, never client-supplied — creating two patients
    # always yields two distinct codes. This proves that guarantee holds.
    headers = _register_and_login(client)

    first = client.post("/patients", json=_patient_payload(), headers=headers).json()
    second = client.post("/patients", json=_patient_payload(last_name="Smith"), headers=headers).json()

    assert first["patient_code"] != second["patient_code"]


def test_future_date_of_birth_is_rejected(client):
    headers = _register_and_login(client)
    future_dob = (date.today() + timedelta(days=1)).isoformat()

    response = client.post("/patients", json=_patient_payload(date_of_birth=future_dob), headers=headers)

    assert response.status_code == 422


def test_retrieve_patient(client):
    headers = _register_and_login(client)
    created = client.post("/patients", json=_patient_payload(), headers=headers).json()

    response = client.get(f"/patients/{created['id']}", headers=headers)

    assert response.status_code == 200
    assert response.json()["id"] == created["id"]


def test_retrieve_unknown_patient_returns_404(client):
    headers = _register_and_login(client)

    response = client.get(f"/patients/{uuid.uuid4()}", headers=headers)

    assert response.status_code == 404


def test_update_patient(client):
    headers = _register_and_login(client)
    created = client.post("/patients", json=_patient_payload(), headers=headers).json()

    response = client.patch(
        f"/patients/{created['id']}", json={"room_number": "310B", "preferred_language": "TELUGU"}, headers=headers
    )

    assert response.status_code == 200
    body = response.json()
    assert body["room_number"] == "310B"
    assert body["preferred_language"] == "TELUGU"
    assert body["first_name"] == "John"  # untouched fields unchanged


def test_discharge_patient_through_patch(client):
    headers = _register_and_login(client)
    created = client.post("/patients", json=_patient_payload(), headers=headers).json()

    response = client.patch(f"/patients/{created['id']}", json={"admission_status": "DISCHARGED"}, headers=headers)

    assert response.status_code == 200
    assert response.json()["admission_status"] == "DISCHARGED"


def test_filter_active_patients(client):
    headers = _register_and_login(client)
    active = client.post("/patients", json=_patient_payload(last_name="Active"), headers=headers).json()
    to_discharge = client.post("/patients", json=_patient_payload(last_name="Discharged"), headers=headers).json()
    client.patch(f"/patients/{to_discharge['id']}", json={"admission_status": "DISCHARGED"}, headers=headers)

    response = client.get("/patients", params={"status": "ACTIVE"}, headers=headers)

    assert response.status_code == 200
    body = response.json()
    ids = {p["id"] for p in body["results"]}
    assert active["id"] in ids
    assert to_discharge["id"] not in ids


def test_search_by_patient_name_and_code(client):
    headers = _register_and_login(client)
    target = client.post(
        "/patients", json=_patient_payload(first_name="Priya", last_name="Sharma"), headers=headers
    ).json()
    client.post("/patients", json=_patient_payload(first_name="Alex", last_name="Nguyen"), headers=headers)

    by_name = client.get("/patients", params={"search": "priya"}, headers=headers).json()
    assert any(p["id"] == target["id"] for p in by_name["results"])

    by_code = client.get("/patients", params={"search": target["patient_code"]}, headers=headers).json()
    assert [p["id"] for p in by_code["results"]] == [target["id"]]


def test_pagination_returns_total_and_bounded_results(client):
    headers = _register_and_login(client)
    for i in range(5):
        client.post("/patients", json=_patient_payload(last_name=f"Patient{i}"), headers=headers)

    response = client.get("/patients", params={"limit": 2, "offset": 0}, headers=headers)

    body = response.json()
    assert body["total"] >= 5
    assert len(body["results"]) == 2


def test_committed_data_is_invisible_to_a_separate_connection(client, outside_session):
    """Self-contained proof that db.commit() inside the app only closes a SAVEPOINT:
    create + commit a patient through the API, then check for it on a totally
    separate connection that isn't part of db_session's outer transaction. Does not
    rely on pytest test-definition order — everything happens inside one test."""
    from app.patients.models import Patient

    headers = _register_and_login(client)
    client.post("/patients", json=_patient_payload(last_name="SavepointIsolationMarker"), headers=headers)

    # Sanity check: visible within this test's own (uncommitted) transaction.
    resp = client.get("/patients", params={"search": "SavepointIsolationMarker"}, headers=headers)
    assert len(resp.json()["results"]) == 1

    # Not visible from a separate connection — the outer transaction was never
    # actually committed to the database, only the inner SAVEPOINT.
    leaked = outside_session.query(Patient).filter(Patient.last_name == "SavepointIsolationMarker").count()
    assert leaked == 0
