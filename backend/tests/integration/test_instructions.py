import uuid

import pytest
from sqlalchemy.exc import IntegrityError

from app.instructions.models import CareInstruction, InstructionStatus, InstructionVersion, VersionSource


def _register_and_login(client, email="clinician@example.com", password="supersecret123"):
    client.post("/auth/register", json={"email": email, "password": password, "full_name": "Test Clinician"})
    login_resp = client.post("/auth/login", json={"email": email, "password": password})
    token = login_resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _current_user_id(client, headers) -> str:
    return client.get("/auth/me", headers=headers).json()["id"]


def _create_active_patient(client, headers, **overrides) -> dict:
    payload = {
        "first_name": "John",
        "last_name": "Doe",
        "date_of_birth": "1950-01-01",
        "preferred_language": "ENGLISH",
    }
    payload.update(overrides)
    return client.post("/patients", json=payload, headers=headers).json()


def _create_instruction(client, headers, patient_id, text="Walk after meals.") -> dict:
    return client.post(f"/patients/{patient_id}/instructions", json={"text": text}, headers=headers).json()


# ---------------------------------------------------------------------------
# Creation
# ---------------------------------------------------------------------------


def test_create_instruction_for_active_patient_creates_draft_with_original_version(client):
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)

    resp = client.post(f"/patients/{patient['id']}/instructions", json={"text": "Walk after meals."}, headers=headers)

    assert resp.status_code == 201
    body = resp.json()
    uuid.UUID(body["id"])
    assert body["status"] == "DRAFT"
    assert body["patient_id"] == patient["id"]
    assert body["current_version"]["version_number"] == 1
    assert body["current_version"]["source"] == "ORIGINAL"
    assert body["current_version"]["raw_text"] == "Walk after meals."


def test_cannot_create_instruction_for_discharged_patient(client):
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)
    client.patch(f"/patients/{patient['id']}", json={"admission_status": "DISCHARGED"}, headers=headers)

    resp = client.post(f"/patients/{patient['id']}/instructions", json={"text": "Walk after meals."}, headers=headers)

    assert resp.status_code == 409


def test_unauthenticated_instruction_creation_is_rejected(client):
    resp = client.post(f"/patients/{uuid.uuid4()}/instructions", json={"text": "Walk after meals."})
    assert resp.status_code == 401


def test_creating_instruction_for_unknown_patient_returns_404(client):
    headers = _register_and_login(client)
    resp = client.post(f"/patients/{uuid.uuid4()}/instructions", json={"text": "Walk after meals."}, headers=headers)
    assert resp.status_code == 404


def test_server_controlled_fields_supplied_by_client_are_ignored(client):
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)

    resp = client.post(
        f"/patients/{patient['id']}/instructions",
        json={
            "text": "Walk after meals.",
            "status": "APPROVED",
            "created_by": str(uuid.uuid4()),
            "version_number": 99,
        },
        headers=headers,
    )

    assert resp.status_code == 201
    assert resp.json()["status"] == "DRAFT"


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------


def test_retrieve_instruction(client):
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)
    created = _create_instruction(client, headers, patient["id"])

    resp = client.get(f"/instructions/{created['id']}", headers=headers)

    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == created["id"]
    assert len(body["versions"]) == 1


def test_retrieve_unknown_instruction_returns_404(client):
    headers = _register_and_login(client)
    resp = client.get(f"/instructions/{uuid.uuid4()}", headers=headers)
    assert resp.status_code == 404


def test_list_patient_instructions_returns_total_and_results(client):
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)
    _create_instruction(client, headers, patient["id"], text="Walk after meals.")
    _create_instruction(client, headers, patient["id"], text="Take medication.")

    resp = client.get(f"/patients/{patient['id']}/instructions", headers=headers)

    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 2
    assert len(body["results"]) == 2


def test_list_patient_instructions_requires_existing_patient(client):
    headers = _register_and_login(client)
    resp = client.get(f"/patients/{uuid.uuid4()}/instructions", headers=headers)
    assert resp.status_code == 404


def test_filter_instructions_by_status(client):
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)
    draft = _create_instruction(client, headers, patient["id"], text="Walk after meals.")
    processing = _create_instruction(
        client, headers, patient["id"], text="Take Metoprolol 25 mg orally twice daily with food."
    )
    client.post(f"/instructions/{processing['id']}/analyze", headers=headers)  # complete -> stays PROCESSING

    resp = client.get(f"/patients/{patient['id']}/instructions", params={"status": "DRAFT"}, headers=headers)

    ids = {r["id"] for r in resp.json()["results"]}
    assert draft["id"] in ids
    assert processing["id"] not in ids


# ---------------------------------------------------------------------------
# Clarification — see test_analyze.py for clarify's auto-reanalysis behavior
# (version 2 creation, extraction re-run, stale-result protection, etc.)
# ---------------------------------------------------------------------------


def test_clarify_from_draft_is_rejected(client):
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)
    created = _create_instruction(client, headers, patient["id"])

    resp = client.post(f"/instructions/{created['id']}/clarify", json={"text": "clarified text"}, headers=headers)

    assert resp.status_code == 409


def test_duplicate_version_number_is_prevented_by_unique_constraint(client, db_session):
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)
    created = _create_instruction(client, headers, patient["id"])
    user_id = uuid.UUID(_current_user_id(client, headers))

    duplicate = InstructionVersion(
        care_instruction_id=uuid.UUID(created["id"]),
        version_number=1,  # collides with the ORIGINAL version created above
        raw_text="duplicate",
        source=VersionSource.CLARIFICATION,
        created_by=user_id,
    )
    db_session.add(duplicate)

    with pytest.raises(IntegrityError):
        db_session.flush()

    db_session.rollback()


# ---------------------------------------------------------------------------
# Approval / rejection — see test_analyze.py, which sets these up via real
# /analyze calls (plus the service-layer primitive for the one state,
# READY_FOR_APPROVAL, that nothing in Step 5 can reach through normal flow).
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Transaction atomicity
# ---------------------------------------------------------------------------


def test_transaction_rollback_prevents_half_created_instruction_and_version(client, db_session):
    """Mirrors create_instruction's own two-flush-then-commit shape: if the second
    insert fails, nothing — not even the first, already-flushed row — should survive
    a rollback, proving the whole operation really is atomic."""
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)
    user_id = uuid.UUID(_current_user_id(client, headers))

    instruction = CareInstruction(
        patient_id=uuid.UUID(patient["id"]), created_by=user_id, status=InstructionStatus.DRAFT
    )
    db_session.add(instruction)
    db_session.flush()
    instruction_id = instruction.id

    bad_version = InstructionVersion(
        care_instruction_id=instruction.id,
        version_number=1,
        raw_text="test",
        source=VersionSource.ORIGINAL,
        created_by=uuid.uuid4(),  # no such user -> FK violation
    )
    db_session.add(bad_version)

    with pytest.raises(IntegrityError):
        db_session.flush()

    db_session.rollback()

    assert db_session.query(CareInstruction).filter(CareInstruction.id == instruction_id).first() is None
