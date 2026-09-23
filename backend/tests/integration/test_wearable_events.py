"""Module 3 Stage 3 — event ingestion, attribution and idempotency.

Covers MODULE_3_IMPLEMENTATION_PLAN.md §28 tests 17–19, 24, 27 and 33.

Stage 3 stores and attributes events; turning them into nurse alerts is
Stage 4. So these tests assert on stored rows and status codes, not alerts.
"""

from datetime import datetime, timedelta, timezone

from app.audit.models import ActorType, AuditEvent, AuditEventType
from app.wearables.models import SensorEvent

FALL_METRICS = {
    "fall_score": 4,
    "peak_g": 4.025,
    "tilt_delta_deg": 90.2,
    "freefall_ms": 160,
    "inactive_ms": 2520,
    "stages_seen": ["freefall", "impact", "orientation", "inactivity"],
}


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


def _assign(client, headers, patient_id, device_id, profile="FALL_RISK"):
    return client.post(
        f"/patients/{patient_id}/wearable-assignment",
        json={"device_id": device_id, "monitoring_profile": profile},
        headers=headers,
    )


def _monitored(client, headers, device_code="SH-WEAR-001", profile="FALL_RISK"):
    """A patient with an assigned, enrolled device. Returns (patient, device, secret)."""
    patient = _create_active_patient(client, headers)
    device, secret = _enrolled_device(client, headers, device_code)
    _assign(client, headers, patient["id"], device["id"], profile)
    return patient, device, secret


def _send(
    client,
    secret,
    event_id="evt-0001",
    event_type="POSSIBLE_FALL",
    metrics=None,
    occurred_at_ms=None,
    assignment_id=None,
    battery=73,
):
    body = {
        "device_event_id": event_id,
        "event_type": event_type,
        "occurred_at_ms": occurred_at_ms
        if occurred_at_ms is not None
        else int(datetime.now(timezone.utc).timestamp() * 1000),
        "battery_percent": battery,
        "firmware_version": "0.1.0",
        "metrics": metrics if metrics is not None else FALL_METRICS,
    }
    if assignment_id:
        body["assignment_id"] = assignment_id
    return client.post(
        "/device-api/events", json=body, headers={"Authorization": f"Bearer {secret}"}
    )


# ── happy path ──────────────────────────────────────────────────────────────


def test_event_is_stored_and_attributed(client, db_session):
    headers = _register_and_login(client)
    patient, device, secret = _monitored(client, headers)

    resp = _send(client, secret)
    assert resp.status_code == 201, resp.text
    assert resp.json()["outcome"] == "CREATED"
    assert resp.json()["delayed"] is False

    row = db_session.query(SensorEvent).one()
    assert row.event_type.value == "POSSIBLE_FALL"
    assert row.metrics["fall_score"] == 4
    assert row.metrics["stages_seen"] == ["freefall", "impact", "orientation", "inactivity"]
    assert row.delayed is False
    assert str(row.device_id) == device["id"]


def test_event_updates_device_health(client, db_session):
    """A device that reports an event has obviously just been seen."""
    headers = _register_and_login(client)
    _patient, device, secret = _monitored(client, headers)

    _send(client, secret, battery=37)

    body = client.get("/wearable-devices", headers=headers).json()["results"][0]
    assert body["battery_percent"] == 37
    assert body["last_seen_at"] is not None


def test_all_four_device_event_types_are_accepted(client):
    headers = _register_and_login(client)
    _patient, _device, secret = _monitored(client, headers, profile="RESTRICTED_MOBILITY")

    for i, event_type in enumerate(
        ["POSSIBLE_FALL", "ABNORMAL_MOVEMENT", "UNEXPECTED_MOBILITY", "DEVICE_LOW_BATTERY"]
    ):
        resp = _send(client, secret, event_id=f"evt-{i}", event_type=event_type)
        assert resp.status_code == 201, f"{event_type}: {resp.text}"


def test_device_cannot_report_device_offline(client):
    """DEVICE_OFFLINE is derived by the backend from a missing heartbeat. A
    device claiming to be offline is a contradiction."""
    headers = _register_and_login(client)
    _patient, _device, secret = _monitored(client, headers)

    resp = _send(client, secret, event_type="DEVICE_OFFLINE")
    assert resp.status_code == 422


# ── idempotency (§22 / §28 test 19) ─────────────────────────────────────────


def test_duplicate_event_id_is_idempotent(client, db_session):
    headers = _register_and_login(client)
    _patient, _device, secret = _monitored(client, headers)

    first = _send(client, secret, event_id="evt-same")
    assert first.status_code == 201
    assert first.json()["outcome"] == "CREATED"

    for _ in range(4):
        again = _send(client, secret, event_id="evt-same")
        assert again.status_code == 200
        assert again.json()["outcome"] == "DUPLICATE"
        # Same row, so a later alert can never be duplicated either.
        assert again.json()["event_id"] == first.json()["event_id"]

    assert db_session.query(SensorEvent).count() == 1


def test_same_event_id_on_different_devices_is_not_a_duplicate(client, db_session):
    """The idempotency key is (device_id, device_event_id). Two devices both
    starting their sequence at 0001 must not collide."""
    headers = _register_and_login(client)
    patient_a = _create_active_patient(client, headers, first_name="A")
    patient_b = _create_active_patient(client, headers, first_name="B")
    device_a, secret_a = _enrolled_device(client, headers, "SH-WEAR-001")
    device_b, secret_b = _enrolled_device(client, headers, "SH-WEAR-002")
    _assign(client, headers, patient_a["id"], device_a["id"])
    _assign(client, headers, patient_b["id"], device_b["id"])

    assert _send(client, secret_a, event_id="evt-0001").status_code == 201
    assert _send(client, secret_b, event_id="evt-0001").status_code == 201
    assert db_session.query(SensorEvent).count() == 2


def test_burst_of_distinct_events_all_store(client, db_session):
    """Idempotency is not dedupe. Twenty DISTINCT event ids are twenty real
    events; collapsing them into one alert is Stage 4's job, not this layer's."""
    headers = _register_and_login(client)
    _patient, _device, secret = _monitored(client, headers)

    for i in range(20):
        assert _send(client, secret, event_id=f"evt-{i:04d}").status_code == 201

    assert db_session.query(SensorEvent).count() == 20


# ── attribution and refusal (§28 tests 17–18) ───────────────────────────────


def test_event_from_unassigned_device_is_discarded(client, db_session):
    headers = _register_and_login(client)
    _device, secret = _enrolled_device(client, headers)

    resp = _send(client, secret)
    assert resp.status_code == 202
    assert resp.json()["outcome"] == "DISCARDED"
    assert resp.json()["event_id"] is None
    assert db_session.query(SensorEvent).count() == 0


def test_event_after_discharge_is_discarded(client, db_session):
    headers = _register_and_login(client)
    patient, _device, secret = _monitored(client, headers)
    client.patch(
        f"/patients/{patient['id']}", json={"admission_status": "DISCHARGED"}, headers=headers
    )

    resp = _send(client, secret)
    assert resp.status_code == 202
    assert db_session.query(SensorEvent).count() == 0


def test_event_requires_a_device_credential(client):
    headers = _register_and_login(client)
    _patient, _device, _secret = _monitored(client, headers)

    # No credential at all.
    assert client.post(
        "/device-api/events",
        json={
            "device_event_id": "x",
            "event_type": "POSSIBLE_FALL",
            "occurred_at_ms": 0,
            "metrics": {},
        },
    ).status_code == 401

    # A clinician JWT must not work here either.
    assert client.post(
        "/device-api/events",
        json={
            "device_event_id": "x",
            "event_type": "POSSIBLE_FALL",
            "occurred_at_ms": 0,
            "metrics": {},
        },
        headers=headers,
    ).status_code == 401


# ── queued events across an assignment change ───────────────────────────────


def test_queued_event_is_attributed_to_the_assignment_it_happened_under(client, db_session):
    """The offline-queue case. A fall detected at 10:43, delivered at 10:55
    after the patient was unassigned at 10:50, still belongs to the assignment
    it happened under. Discarding it would throw away a real fall."""
    headers = _register_and_login(client)
    patient, device, secret = _monitored(client, headers)
    assignment_id = client.get(
        f"/patients/{patient['id']}/wearable-assignment", headers=headers
    ).json()["assignment"]["id"]

    client.delete(f"/patients/{patient['id']}/wearable-assignment", headers=headers)

    # Without the claim it would be discarded...
    assert _send(client, secret, event_id="evt-nohint").status_code == 202
    # ...but naming the assignment attributes it correctly.
    resp = _send(client, secret, event_id="evt-queued", assignment_id=assignment_id)
    assert resp.status_code == 201

    row = db_session.query(SensorEvent).one()
    assert str(row.assignment_id) == assignment_id


def test_device_cannot_claim_another_devices_assignment(client, db_session):
    headers = _register_and_login(client)
    patient_a = _create_active_patient(client, headers, first_name="A")
    device_a, _secret_a = _enrolled_device(client, headers, "SH-WEAR-001")
    _assign(client, headers, patient_a["id"], device_a["id"])
    assignment_a = client.get(
        f"/patients/{patient_a['id']}/wearable-assignment", headers=headers
    ).json()["assignment"]["id"]

    # A second, unassigned device tries to attribute its event to A's assignment.
    _device_b, secret_b = _enrolled_device(client, headers, "SH-WEAR-002")
    resp = _send(client, secret_b, assignment_id=assignment_a)

    assert resp.status_code == 202
    assert db_session.query(SensorEvent).count() == 0


def test_unknown_assignment_id_is_discarded_not_crashed(client):
    headers = _register_and_login(client)
    _patient, _device, secret = _monitored(client, headers)

    resp = _send(client, secret, assignment_id="00000000-0000-0000-0000-000000000000")
    assert resp.status_code == 202


# ── timestamps: delayed and skewed (§18, §28 test 27) ───────────────────────


def test_old_event_is_flagged_delayed_but_still_stored(client, db_session):
    headers = _register_and_login(client)
    _patient, _device, secret = _monitored(client, headers)
    fifteen_min_ago = datetime.now(timezone.utc) - timedelta(minutes=15)

    resp = _send(client, secret, occurred_at_ms=int(fifteen_min_ago.timestamp() * 1000))
    assert resp.status_code == 201
    assert resp.json()["delayed"] is True

    row = db_session.query(SensorEvent).one()
    assert row.delayed is True
    # occurred_at keeps the true detection time; received_at is now.
    assert row.received_at > row.occurred_at


def test_recent_event_is_not_flagged_delayed(client):
    headers = _register_and_login(client)
    _patient, _device, secret = _monitored(client, headers)
    ten_s_ago = datetime.now(timezone.utc) - timedelta(seconds=10)

    resp = _send(client, secret, occurred_at_ms=int(ten_s_ago.timestamp() * 1000))
    assert resp.json()["delayed"] is False


def test_future_timestamp_is_clamped_to_receipt_time(client, db_session):
    """A device with a broken clock must not be able to date an event in the
    future: the nurse queue is time-ordered, and a future-dated alert would sit
    above every genuine one and stay there."""
    headers = _register_and_login(client)
    _patient, _device, secret = _monitored(client, headers)
    tomorrow = datetime.now(timezone.utc) + timedelta(days=1)

    resp = _send(client, secret, occurred_at_ms=int(tomorrow.timestamp() * 1000))
    assert resp.status_code == 201

    row = db_session.query(SensorEvent).one()
    assert row.occurred_at <= row.received_at + timedelta(seconds=1)
    assert row.delayed is False


# ── the strict metrics schema (§28 test 33) ─────────────────────────────────


def test_unknown_metrics_keys_are_rejected(client, db_session):
    """extra="forbid" is a safety control: a buggy or compromised device must
    not be able to write arbitrary content — including PHI — into the DB."""
    headers = _register_and_login(client)
    _patient, _device, secret = _monitored(client, headers)

    resp = _send(
        client,
        secret,
        metrics={"fall_score": 4, "patient_name": "John Doe", "notes": "fell in bathroom"},
    )
    assert resp.status_code == 422
    assert db_session.query(SensorEvent).count() == 0


def test_out_of_range_metrics_are_rejected(client):
    headers = _register_and_login(client)
    _patient, _device, secret = _monitored(client, headers)

    assert _send(client, secret, metrics={"fall_score": 99}).status_code == 422
    assert _send(client, secret, metrics={"tilt_delta_deg": 400.0}).status_code == 422
    assert _send(client, secret, metrics={"stages_seen": ["teleported"]}).status_code == 422


def test_unknown_top_level_fields_are_rejected(client):
    headers = _register_and_login(client)
    _patient, _device, secret = _monitored(client, headers)

    resp = client.post(
        "/device-api/events",
        json={
            "device_event_id": "evt-x",
            "event_type": "POSSIBLE_FALL",
            "occurred_at_ms": int(datetime.now(timezone.utc).timestamp() * 1000),
            "metrics": {},
            "patient_code": "P1001",
        },
        headers={"Authorization": f"Bearer {secret}"},
    )
    assert resp.status_code == 422


# ── audit ───────────────────────────────────────────────────────────────────


def test_event_is_audited_as_system_against_the_patient(client, db_session):
    headers = _register_and_login(client)
    patient, _device, secret = _monitored(client, headers)
    _send(client, secret)

    event = (
        db_session.query(AuditEvent)
        .filter(AuditEvent.event_type == AuditEventType.SAFETY_EVENT_RECEIVED.value)
        .one()
    )
    assert event.actor_type is ActorType.SYSTEM
    assert event.actor_id is None
    assert str(event.patient_id) == patient["id"]
    assert event.event_metadata["sensor_event_type"] == "POSSIBLE_FALL"
    assert event.event_metadata["delayed"] is False


def test_duplicate_submission_writes_only_one_audit_event(client, db_session):
    headers = _register_and_login(client)
    _patient, _device, secret = _monitored(client, headers)

    for _ in range(3):
        _send(client, secret, event_id="evt-same")

    count = (
        db_session.query(AuditEvent)
        .filter(AuditEvent.event_type == AuditEventType.SAFETY_EVENT_RECEIVED.value)
        .count()
    )
    assert count == 1


def test_discarded_event_writes_no_audit_event(client, db_session):
    headers = _register_and_login(client)
    _device, secret = _enrolled_device(client, headers)
    _send(client, secret)

    assert (
        db_session.query(AuditEvent)
        .filter(AuditEvent.event_type == AuditEventType.SAFETY_EVENT_RECEIVED.value)
        .count()
        == 0
    )


# ── staff history view ──────────────────────────────────────────────────────


def test_patient_safety_event_history(client):
    headers = _register_and_login(client)
    patient, _device, secret = _monitored(client, headers)
    _send(client, secret, event_id="evt-1", event_type="POSSIBLE_FALL")
    _send(client, secret, event_id="evt-2", event_type="ABNORMAL_MOVEMENT")

    body = client.get(f"/patients/{patient['id']}/safety-events", headers=headers).json()
    assert body["total"] == 2
    assert {r["event_type"] for r in body["results"]} == {
        "POSSIBLE_FALL",
        "ABNORMAL_MOVEMENT",
    }


def test_history_follows_the_patient_not_the_device(client):
    """After reassignment, each patient's history keeps only their own events —
    resolved by joining through assignments rather than copying patient_id onto
    the event."""
    headers = _register_and_login(client)
    patient_a = _create_active_patient(client, headers, first_name="A")
    patient_b = _create_active_patient(client, headers, first_name="B")
    device, secret = _enrolled_device(client, headers)

    _assign(client, headers, patient_a["id"], device["id"])
    _send(client, secret, event_id="evt-a")
    client.delete(f"/patients/{patient_a['id']}/wearable-assignment", headers=headers)

    _assign(client, headers, patient_b["id"], device["id"])
    _send(client, secret, event_id="evt-b")

    a_events = client.get(f"/patients/{patient_a['id']}/safety-events", headers=headers).json()
    b_events = client.get(f"/patients/{patient_b['id']}/safety-events", headers=headers).json()
    assert a_events["total"] == 1
    assert b_events["total"] == 1
    assert a_events["results"][0]["id"] != b_events["results"][0]["id"]


def test_history_requires_a_clinician_jwt(client):
    headers = _register_and_login(client)
    patient, _device, secret = _monitored(client, headers)

    resp = client.get(
        f"/patients/{patient['id']}/safety-events",
        headers={"Authorization": f"Bearer {secret}"},
    )
    assert resp.status_code == 401
