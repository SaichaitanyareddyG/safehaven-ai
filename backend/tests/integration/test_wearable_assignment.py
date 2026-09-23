"""Module 3 Stage 2 — assignment, monitoring profiles and the discharge cascade.

Covers MODULE_3_IMPLEMENTATION_PLAN.md §28 tests 28–30 and 32, plus the two
invariants the stage exists to guarantee: one active assignment per device, and
one per patient — enforced in the database, not just in Python.
"""

import pytest
from sqlalchemy.exc import IntegrityError

from app.audit.models import ActorType, AuditEvent, AuditEventType
from app.wearables.models import DeviceAssignment, MonitoringProfile


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
        "room_number": "204",
    }
    payload.update(overrides)
    return client.post("/patients", json=payload, headers=headers).json()


def _enrolled_device(client, headers, device_code="SH-WEAR-001") -> tuple[dict, str]:
    reg = client.post("/wearable-devices", json={"device_code": device_code}, headers=headers).json()
    body = client.post(
        "/device-api/enroll",
        json={"enrollment_code": reg["enrollment_code"], "hardware_id": f"HW-{device_code}"},
    ).json()
    return reg["device"], body["device_secret"]


def _registered_only_device(client, headers, device_code="SH-WEAR-099") -> dict:
    """Registered but never enrolled — it has no credential, so it can never
    report anything."""
    return client.post(
        "/wearable-devices", json={"device_code": device_code}, headers=headers
    ).json()["device"]


def _assign(client, headers, patient_id, device_id, profile="STANDARD"):
    return client.post(
        f"/patients/{patient_id}/wearable-assignment",
        json={"device_id": device_id, "monitoring_profile": profile},
        headers=headers,
    )


def _heartbeat(client, secret, battery=70):
    return client.post(
        "/device-api/heartbeat",
        json={"battery_percent": battery, "firmware_version": "0.1.0"},
        headers={"Authorization": f"Bearer {secret}"},
    )


def _discharge(client, headers, patient_id):
    return client.patch(
        f"/patients/{patient_id}", json={"admission_status": "DISCHARGED"}, headers=headers
    )


# ── happy path ──────────────────────────────────────────────────────────────


def test_assign_device_to_patient(client):
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)
    device, _ = _enrolled_device(client, headers)

    resp = _assign(client, headers, patient["id"], device["id"], "FALL_RISK")
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["device_code"] == "SH-WEAR-001"
    assert body["patient_id"] == patient["id"]
    assert body["monitoring_profile"] == "FALL_RISK"
    assert body["unassigned_at"] is None


def test_assignment_links_the_open_encounter_as_context(client, db_session):
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)
    encounter = client.post(
        f"/patients/{patient['id']}/encounters",
        json={"admission_date": "2026-09-20", "reason_for_visit": "Hip replacement"},
        headers=headers,
    ).json()
    device, _ = _enrolled_device(client, headers)

    _assign(client, headers, patient["id"], device["id"])

    row = db_session.query(DeviceAssignment).one()
    assert str(row.encounter_id) == encounter["id"]


def test_assignment_succeeds_without_an_open_encounter(client):
    """Encounter is context, not a gate. Patient.admission_status is the
    authority, and these are separate unlinked state machines."""
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)
    device, _ = _enrolled_device(client, headers)

    assert _assign(client, headers, patient["id"], device["id"]).status_code == 201


def test_get_assignment_is_null_when_patient_has_no_wearable(client):
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)

    resp = client.get(f"/patients/{patient['id']}/wearable-assignment", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["assignment"] is None


def test_get_assignment_includes_live_device_health(client):
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)
    device, secret = _enrolled_device(client, headers)
    _assign(client, headers, patient["id"], device["id"])
    _heartbeat(client, secret, battery=42)

    body = client.get(f"/patients/{patient['id']}/wearable-assignment", headers=headers).json()
    assert body["assignment"]["battery_percent"] == 42
    assert body["assignment"]["last_seen_at"] is not None


# ── the device learns the profile, and nothing about the patient ────────────


def test_heartbeat_returns_the_assignment_after_assigning(client):
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)
    device, secret = _enrolled_device(client, headers)

    assert _heartbeat(client, secret).json()["assignment"] is None

    _assign(client, headers, patient["id"], device["id"], "RESTRICTED_MOBILITY")

    assignment = _heartbeat(client, secret).json()["assignment"]
    assert assignment is not None
    assert assignment["monitoring_profile"] == "RESTRICTED_MOBILITY"
    assert assignment["assigned_at_ms"] > 0


def test_device_is_never_told_who_it_is_monitoring(client):
    """The single most important privacy property of the device API."""
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers, first_name="Gladys", last_name="Pemberton")
    device, secret = _enrolled_device(client, headers)
    _assign(client, headers, patient["id"], device["id"])

    body = _heartbeat(client, secret).json()
    assert set(body["assignment"].keys()) == {
        "assignment_id",
        "monitoring_profile",
        "assigned_at_ms",
    }

    blob = str(body)
    for leak in ("Gladys", "Pemberton", patient["id"], patient["patient_code"], "204", "1950"):
        assert leak not in blob


# ── refusals, each for a safety reason ──────────────────────────────────────


def test_cannot_assign_an_unenrolled_device(client):
    """It has no credential, so it can never report. Assigning it would create
    a false impression that the patient is monitored."""
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)
    device = _registered_only_device(client, headers)

    resp = _assign(client, headers, patient["id"], device["id"])
    assert resp.status_code == 409
    assert "not enrolled" in resp.json()["detail"]


def test_cannot_assign_a_revoked_device(client):
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)
    device, _ = _enrolled_device(client, headers)
    client.post(f"/wearable-devices/{device['id']}/revoke", headers=headers)

    resp = _assign(client, headers, patient["id"], device["id"])
    assert resp.status_code == 409
    assert "DISABLED" in resp.json()["detail"]


def test_cannot_assign_to_a_discharged_patient(client):
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)
    device, _ = _enrolled_device(client, headers)
    _discharge(client, headers, patient["id"])

    resp = _assign(client, headers, patient["id"], device["id"])
    assert resp.status_code == 409
    assert "discharged" in resp.json()["detail"]


def test_patient_cannot_have_two_wearables(client):
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)
    device_a, _ = _enrolled_device(client, headers, "SH-WEAR-001")
    device_b, _ = _enrolled_device(client, headers, "SH-WEAR-002")

    assert _assign(client, headers, patient["id"], device_a["id"]).status_code == 201
    resp = _assign(client, headers, patient["id"], device_b["id"])
    assert resp.status_code == 409
    assert "already has" in resp.json()["detail"]


def test_device_cannot_be_assigned_to_two_patients(client):
    headers = _register_and_login(client)
    patient_a = _create_active_patient(client, headers, first_name="A")
    patient_b = _create_active_patient(client, headers, first_name="B")
    device, _ = _enrolled_device(client, headers)

    assert _assign(client, headers, patient_a["id"], device["id"]).status_code == 201
    resp = _assign(client, headers, patient_b["id"], device["id"])
    assert resp.status_code == 409
    assert "already assigned" in resp.json()["detail"]


def test_monitoring_profile_is_required(client):
    """No default. Defaulting to STANDARD could silently give the wrong
    behaviour; defaulting to RESTRICTED_MOBILITY would switch on an
    inferential detector nobody asked for."""
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)
    device, _ = _enrolled_device(client, headers)

    resp = client.post(
        f"/patients/{patient['id']}/wearable-assignment",
        json={"device_id": device["id"]},
        headers=headers,
    )
    assert resp.status_code == 422


def test_assign_requires_a_clinician_jwt(client):
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)
    device, secret = _enrolled_device(client, headers)

    # A device credential must not be able to assign itself to a patient.
    resp = client.post(
        f"/patients/{patient['id']}/wearable-assignment",
        json={"device_id": device["id"], "monitoring_profile": "STANDARD"},
        headers={"Authorization": f"Bearer {secret}"},
    )
    assert resp.status_code == 401


# ── database-level invariants ───────────────────────────────────────────────


def test_partial_unique_index_blocks_a_second_active_assignment_per_device(client, db_session):
    """The Python check can lose a race; the index cannot."""
    headers = _register_and_login(client)
    patient_a = _create_active_patient(client, headers, first_name="A")
    patient_b = _create_active_patient(client, headers, first_name="B")
    device, _ = _enrolled_device(client, headers)
    _assign(client, headers, patient_a["id"], device["id"])

    import uuid as _uuid

    db_session.add(
        DeviceAssignment(
            device_id=_uuid.UUID(device["id"]),
            patient_id=_uuid.UUID(patient_b["id"]),
            monitoring_profile=MonitoringProfile.STANDARD,
            assigned_by=_uuid.UUID(client.get("/auth/me", headers=headers).json()["id"]),
        )
    )
    with pytest.raises(IntegrityError):
        db_session.flush()


# ── unassign and reuse ──────────────────────────────────────────────────────


def test_unassign_returns_device_to_the_pool(client):
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)
    device, secret = _enrolled_device(client, headers)
    _assign(client, headers, patient["id"], device["id"])

    resp = client.delete(f"/patients/{patient['id']}/wearable-assignment", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["unassigned_at"] is not None

    # The device finds out on its next heartbeat and drops to its safe state.
    assert _heartbeat(client, secret).json()["assignment"] is None
    assert client.get(
        f"/patients/{patient['id']}/wearable-assignment", headers=headers
    ).json()["assignment"] is None


def test_unassign_with_no_assignment_is_404(client):
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)
    resp = client.delete(f"/patients/{patient['id']}/wearable-assignment", headers=headers)
    assert resp.status_code == 404


def test_device_can_be_reused_for_another_patient(client, db_session):
    """§28 test 32 / demo Scenario 7. The physical device is reusable; the old
    patient must retain no ACTIVE association."""
    headers = _register_and_login(client)
    patient_a = _create_active_patient(client, headers, first_name="A")
    patient_b = _create_active_patient(client, headers, first_name="B")
    device, secret = _enrolled_device(client, headers)

    _assign(client, headers, patient_a["id"], device["id"], "FALL_RISK")
    client.delete(f"/patients/{patient_a['id']}/wearable-assignment", headers=headers)
    assert _assign(client, headers, patient_b["id"], device["id"], "STANDARD").status_code == 201

    # Two rows of history, exactly one active, pointing at the new patient.
    rows = db_session.query(DeviceAssignment).all()
    assert len(rows) == 2
    active = [r for r in rows if r.unassigned_at is None]
    assert len(active) == 1
    assert str(active[0].patient_id) == patient_b["id"]
    assert active[0].monitoring_profile is MonitoringProfile.STANDARD

    # And the device is now running the new patient's profile.
    assert _heartbeat(client, secret).json()["assignment"]["monitoring_profile"] == "STANDARD"


# ── discharge cascade ───────────────────────────────────────────────────────


def test_discharge_automatically_ends_the_assignment(client, db_session):
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)
    device, secret = _enrolled_device(client, headers)
    _assign(client, headers, patient["id"], device["id"])

    assert _discharge(client, headers, patient["id"]).status_code == 200

    row = db_session.query(DeviceAssignment).one()
    assert row.unassigned_at is not None
    # No clinician is attributed to an automatic action.
    assert row.unassigned_by is None

    # The device stops believing it monitors anyone.
    assert _heartbeat(client, secret).json()["assignment"] is None


def test_discharge_cascade_is_audited_as_system(client, db_session):
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)
    device, _ = _enrolled_device(client, headers)
    _assign(client, headers, patient["id"], device["id"])
    _discharge(client, headers, patient["id"])

    event = (
        db_session.query(AuditEvent)
        .filter(AuditEvent.event_type == AuditEventType.WEARABLE_DEVICE_UNASSIGNED.value)
        .one()
    )
    assert event.actor_type is ActorType.SYSTEM
    assert event.actor_id is None
    assert event.event_metadata["reason"] == "patient_discharged"


def test_staff_unassign_is_audited_as_clinician(client, db_session):
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)
    device, _ = _enrolled_device(client, headers)
    _assign(client, headers, patient["id"], device["id"])
    client.delete(f"/patients/{patient['id']}/wearable-assignment", headers=headers)

    event = (
        db_session.query(AuditEvent)
        .filter(AuditEvent.event_type == AuditEventType.WEARABLE_DEVICE_UNASSIGNED.value)
        .one()
    )
    assert event.actor_type is ActorType.CLINICIAN
    assert event.actor_id is not None
    assert event.event_metadata["reason"] == "staff_unassigned"


def test_discharge_without_a_wearable_still_works(client):
    """The cascade must be a no-op, not an error, for the common case."""
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)
    assert _discharge(client, headers, patient["id"]).status_code == 200


def test_non_discharge_patient_update_does_not_touch_the_assignment(client, db_session):
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)
    device, _ = _enrolled_device(client, headers)
    _assign(client, headers, patient["id"], device["id"])

    resp = client.patch(f"/patients/{patient['id']}", json={"room_number": "301"}, headers=headers)
    assert resp.status_code == 200

    assert db_session.query(DeviceAssignment).one().unassigned_at is None


# ── audit ───────────────────────────────────────────────────────────────────


def test_assignment_is_audited_with_profile_and_patient(client, db_session):
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)
    device, _ = _enrolled_device(client, headers)
    _assign(client, headers, patient["id"], device["id"], "RESTRICTED_MOBILITY")

    event = (
        db_session.query(AuditEvent)
        .filter(AuditEvent.event_type == AuditEventType.WEARABLE_DEVICE_ASSIGNED.value)
        .one()
    )
    assert str(event.patient_id) == patient["id"]
    assert event.actor_type is ActorType.CLINICIAN
    assert event.event_metadata["monitoring_profile"] == "RESTRICTED_MOBILITY"
    assert event.event_metadata["device_code"] == "SH-WEAR-001"


def test_assignment_audit_metadata_carries_no_patient_identifiers(client, db_session):
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers, first_name="Gladys", last_name="Pemberton")
    device, _ = _enrolled_device(client, headers)
    _assign(client, headers, patient["id"], device["id"])

    for event in db_session.query(AuditEvent).all():
        blob = str(event.event_metadata)
        assert "Gladys" not in blob
        assert "Pemberton" not in blob
        assert patient["patient_code"] not in blob
