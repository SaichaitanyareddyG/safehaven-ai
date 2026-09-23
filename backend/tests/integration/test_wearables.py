"""Module 3 Stage 1 — device registry, enrolment and the credential boundary.

Covers MODULE_3_IMPLEMENTATION_PLAN.md §28 tests 13–16, plus the boundary
assertions the plan calls out as the point of the stage: a device credential
must not work on a clinician route, a clinician JWT must not work on the device
API, and every authentication failure must be indistinguishable from the
others.
"""

from app.audit.models import ActorType, AuditEvent, AuditEventType
from app.wearables.models import DeviceStatus, WearableDevice


def _register_and_login(client, email="clinician@example.com", password="supersecret123"):
    client.post("/auth/register", json={"email": email, "password": password, "full_name": "Test Clinician"})
    login_resp = client.post("/auth/login", json={"email": email, "password": password})
    return {"Authorization": f"Bearer {login_resp.json()['access_token']}"}


def _register_device(client, headers, device_code="SH-WEAR-001") -> dict:
    resp = client.post("/wearable-devices", json={"device_code": device_code}, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _enroll(client, enrollment_code, hardware_id="EFUSE-AABBCCDD") -> tuple[int, dict]:
    resp = client.post(
        "/device-api/enroll",
        json={"enrollment_code": enrollment_code, "hardware_id": hardware_id},
    )
    return resp.status_code, resp.json()


def _device_headers(secret: str) -> dict:
    return {"Authorization": f"Bearer {secret}"}


def _enrolled_device(client, headers, device_code="SH-WEAR-001") -> tuple[dict, str]:
    """Register + enrol in one step. Returns (device json, raw secret)."""
    registered = _register_device(client, headers, device_code)
    status_code, body = _enroll(client, registered["enrollment_code"])
    assert status_code == 200, body
    return registered["device"], body["device_secret"]


# ── registration ────────────────────────────────────────────────────────────


def test_register_device_returns_one_time_enrollment_code(client):
    headers = _register_and_login(client)
    body = _register_device(client, headers)

    assert body["device"]["device_code"] == "SH-WEAR-001"
    assert body["device"]["status"] == "ACTIVE"
    assert body["device"]["enrolled"] is False
    assert body["enrollment_code"]
    assert body["enrollment_expires_at"]


def test_register_device_rejects_duplicate_code(client):
    headers = _register_and_login(client)
    _register_device(client, headers, "SH-WEAR-001")

    resp = client.post("/wearable-devices", json={"device_code": "SH-WEAR-001"}, headers=headers)
    assert resp.status_code == 409


def test_device_code_is_normalised_to_uppercase(client):
    headers = _register_and_login(client)
    resp = client.post("/wearable-devices", json={"device_code": " sh-wear-009 "}, headers=headers)
    assert resp.status_code == 201
    assert resp.json()["device"]["device_code"] == "SH-WEAR-009"


def test_registration_requires_a_clinician_jwt(client):
    resp = client.post("/wearable-devices", json={"device_code": "SH-WEAR-002"})
    assert resp.status_code == 401


def test_raw_enrollment_code_is_never_persisted(client, db_session):
    headers = _register_and_login(client)
    body = _register_device(client, headers)
    raw = body["enrollment_code"]

    device = db_session.query(WearableDevice).one()
    assert device.enrollment_code_hash is not None
    assert device.enrollment_code_hash != raw
    assert raw not in str(device.__dict__.values())


# ── enrolment (§28 test 13) ─────────────────────────────────────────────────


def test_enroll_exchanges_code_for_secret_once(client, db_session):
    headers = _register_and_login(client)
    registered = _register_device(client, headers)

    status_code, body = _enroll(client, registered["enrollment_code"])
    assert status_code == 200
    assert body["device_code"] == "SH-WEAR-001"
    secret = body["device_secret"]
    assert len(secret) > 20

    device = db_session.query(WearableDevice).one()
    # Only the hash is kept, and the code is consumed.
    assert device.credential_hash is not None
    assert device.credential_hash != secret
    assert device.enrollment_code_hash is None
    assert device.enrollment_expires_at is None
    assert device.hardware_id == "EFUSE-AABBCCDD"


def test_enrollment_code_cannot_be_replayed(client):
    headers = _register_and_login(client)
    registered = _register_device(client, headers)
    code = registered["enrollment_code"]

    assert _enroll(client, code)[0] == 200
    # Second attempt with the same code must not enrol a second device.
    status_code, _ = _enroll(client, code, hardware_id="EFUSE-11112222")
    assert status_code == 401


def test_unknown_enrollment_code_is_rejected(client):
    status_code, _ = _enroll(client, "ZZZZZZZZZZ")
    assert status_code == 401


def test_expired_enrollment_code_is_rejected(client, db_session):
    from datetime import datetime, timedelta, timezone

    headers = _register_and_login(client)
    registered = _register_device(client, headers)

    device = db_session.query(WearableDevice).one()
    device.enrollment_expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    db_session.flush()

    status_code, _ = _enroll(client, registered["enrollment_code"])
    assert status_code == 401


def test_all_enrollment_failures_are_indistinguishable(client, db_session):
    """Unknown, expired and already-consumed must look identical, so the
    response cannot be used to probe which codes exist."""
    from datetime import datetime, timedelta, timezone

    headers = _register_and_login(client)

    unknown = client.post(
        "/device-api/enroll", json={"enrollment_code": "ZZZZZZZZZZ", "hardware_id": "HW-1"}
    )

    consumed_reg = _register_device(client, headers, "SH-WEAR-010")
    _enroll(client, consumed_reg["enrollment_code"], "HW-2")
    consumed = client.post(
        "/device-api/enroll",
        json={"enrollment_code": consumed_reg["enrollment_code"], "hardware_id": "HW-3"},
    )

    expired_reg = _register_device(client, headers, "SH-WEAR-011")
    expired_device = (
        db_session.query(WearableDevice).filter(WearableDevice.device_code == "SH-WEAR-011").one()
    )
    expired_device.enrollment_expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    db_session.flush()
    expired = client.post(
        "/device-api/enroll",
        json={"enrollment_code": expired_reg["enrollment_code"], "hardware_id": "HW-4"},
    )

    assert unknown.status_code == consumed.status_code == expired.status_code == 401
    assert unknown.json() == consumed.json() == expired.json()


def test_reissued_enrollment_code_works_and_invalidates_the_old_one(client):
    headers = _register_and_login(client)
    registered = _register_device(client, headers)
    old_code = registered["enrollment_code"]
    device_id = registered["device"]["id"]

    resp = client.post(f"/wearable-devices/{device_id}/enrollment-code", headers=headers)
    assert resp.status_code == 200
    new_code = resp.json()["enrollment_code"]
    assert new_code != old_code

    assert _enroll(client, old_code)[0] == 401
    assert _enroll(client, new_code)[0] == 200


# ── credential boundary (§28 tests 15–16) ───────────────────────────────────


def test_heartbeat_with_valid_credential_updates_health(client, db_session):
    headers = _register_and_login(client)
    _, secret = _enrolled_device(client, headers)

    resp = client.post(
        "/device-api/heartbeat",
        json={"battery_percent": 73, "firmware_version": "0.1.0", "rssi": -58, "sensor_ok": True},
        headers=_device_headers(secret),
    )
    assert resp.status_code == 200
    assert resp.json()["assignment"] is None  # no assignments until Stage 2
    assert resp.json()["server_time_ms"] > 0

    device = db_session.query(WearableDevice).one()
    assert device.battery_percent == 73
    assert device.firmware_version == "0.1.0"
    assert device.last_seen_at is not None


def test_heartbeat_is_not_stored_as_an_audit_event(client, db_session):
    """A heartbeat every 30s per device would bury the events that matter."""
    headers = _register_and_login(client)
    _, secret = _enrolled_device(client, headers)
    before = db_session.query(AuditEvent).count()

    for _ in range(3):
        client.post(
            "/device-api/heartbeat",
            json={"battery_percent": 70, "firmware_version": "0.1.0"},
            headers=_device_headers(secret),
        )

    assert db_session.query(AuditEvent).count() == before


def test_device_api_rejects_missing_wrong_and_revoked_credentials_identically(client, db_session):
    headers = _register_and_login(client)
    device, secret = _enrolled_device(client, headers)
    body = {"battery_percent": 50, "firmware_version": "0.1.0"}

    missing = client.post("/device-api/heartbeat", json=body)
    wrong = client.post("/device-api/heartbeat", json=body, headers=_device_headers("not-a-secret"))

    revoke = client.post(f"/wearable-devices/{device['id']}/revoke", headers=headers)
    assert revoke.status_code == 200
    revoked = client.post("/device-api/heartbeat", json=body, headers=_device_headers(secret))

    assert missing.status_code == wrong.status_code == revoked.status_code == 401
    assert missing.json() == wrong.json() == revoked.json()


def test_clinician_jwt_is_rejected_on_the_device_api(client):
    """The three actor types must not be interchangeable."""
    headers = _register_and_login(client)
    resp = client.post(
        "/device-api/heartbeat",
        json={"battery_percent": 50, "firmware_version": "0.1.0"},
        headers=headers,  # a real clinician JWT
    )
    assert resp.status_code == 401


def test_device_credential_is_rejected_on_a_clinician_route(client):
    headers = _register_and_login(client)
    _, secret = _enrolled_device(client, headers)

    resp = client.get("/wearable-devices", headers=_device_headers(secret))
    assert resp.status_code == 401


# ── revocation independence (§9's core requirement) ─────────────────────────


def test_revoking_one_device_does_not_affect_another(client):
    headers = _register_and_login(client)
    device_a, secret_a = _enrolled_device(client, headers, "SH-WEAR-001")
    _, secret_b = _enrolled_device(client, headers, "SH-WEAR-002")
    body = {"battery_percent": 60, "firmware_version": "0.1.0"}

    client.post(f"/wearable-devices/{device_a['id']}/revoke", headers=headers)

    assert client.post("/device-api/heartbeat", json=body, headers=_device_headers(secret_a)).status_code == 401
    assert client.post("/device-api/heartbeat", json=body, headers=_device_headers(secret_b)).status_code == 200


def test_revoke_destroys_the_credential_not_just_the_status(client, db_session):
    """Clearing the hash means a leaked secret is worthless even if some future
    code path forgets to check status."""
    headers = _register_and_login(client)
    device, _ = _enrolled_device(client, headers)

    client.post(f"/wearable-devices/{device['id']}/revoke", headers=headers)

    row = db_session.query(WearableDevice).one()
    assert row.status is DeviceStatus.DISABLED
    assert row.credential_hash is None


def test_revoke_unknown_device_is_404(client):
    headers = _register_and_login(client)
    resp = client.post(
        "/wearable-devices/00000000-0000-0000-0000-000000000000/revoke", headers=headers
    )
    assert resp.status_code == 404


# ── listing and audit ───────────────────────────────────────────────────────


def test_list_devices_reports_derived_enrolled_state(client):
    headers = _register_and_login(client)
    _register_device(client, headers, "SH-WEAR-001")
    _enrolled_device(client, headers, "SH-WEAR-002")

    body = client.get("/wearable-devices", headers=headers).json()
    assert body["total"] == 2
    by_code = {d["device_code"]: d for d in body["results"]}
    assert by_code["SH-WEAR-001"]["enrolled"] is False
    assert by_code["SH-WEAR-002"]["enrolled"] is True


def test_device_lifecycle_is_audited_with_correct_actor_types(client, db_session):
    headers = _register_and_login(client)
    device, _ = _enrolled_device(client, headers)
    client.post(f"/wearable-devices/{device['id']}/revoke", headers=headers)

    events = {e.event_type: e for e in db_session.query(AuditEvent).all()}

    assert AuditEventType.WEARABLE_DEVICE_REGISTERED.value in events
    assert AuditEventType.WEARABLE_DEVICE_ENROLLED.value in events
    assert AuditEventType.WEARABLE_DEVICE_REVOKED.value in events

    # Staff actions are attributed to the clinician; the device enrolling itself
    # is SYSTEM, matching how other actor-less events are recorded.
    assert events[AuditEventType.WEARABLE_DEVICE_REGISTERED.value].actor_type is ActorType.CLINICIAN
    assert events[AuditEventType.WEARABLE_DEVICE_ENROLLED.value].actor_type is ActorType.SYSTEM
    assert events[AuditEventType.WEARABLE_DEVICE_REVOKED.value].actor_type is ActorType.CLINICIAN

    # Device lifecycle is not patient-scoped.
    assert events[AuditEventType.WEARABLE_DEVICE_ENROLLED.value].patient_id is None


def test_audit_metadata_never_contains_the_secret_or_its_hash(client, db_session):
    headers = _register_and_login(client)
    registered = _register_device(client, headers)
    code = registered["enrollment_code"]
    _, body = _enroll(client, code)
    secret = body["device_secret"]

    device = db_session.query(WearableDevice).one()
    for event in db_session.query(AuditEvent).all():
        blob = str(event.event_metadata)
        assert secret not in blob
        assert code not in blob
        assert (device.credential_hash or "x") not in blob


# ── edge-case review regressions ────────────────────────────────────────────


def test_revoked_device_can_be_returned_to_service(client, db_session):
    """Revocation is reversible; RETIRED is the terminal state.

    Regression: reissue_enrollment_code happily minted a code for a DISABLED
    device, but enroll_device then refused it because it required status ACTIVE
    — so a device revoked by mistake, or recovered after being lost, was
    bricked forever with no path back.
    """
    headers = _register_and_login(client)
    device, old_secret = _enrolled_device(client, headers)
    client.post(f"/wearable-devices/{device['id']}/revoke", headers=headers)

    reissue = client.post(f"/wearable-devices/{device['id']}/enrollment-code", headers=headers)
    assert reissue.status_code == 200

    status_code, body = _enroll(client, reissue.json()["enrollment_code"], "HW-REENROLLED")
    assert status_code == 200
    new_secret = body["device_secret"]
    assert new_secret != old_secret

    row = db_session.query(WearableDevice).one()
    assert row.status is DeviceStatus.ACTIVE

    heartbeat = client.post(
        "/device-api/heartbeat",
        json={"battery_percent": 55, "firmware_version": "0.1.0"},
        headers=_device_headers(new_secret),
    )
    assert heartbeat.status_code == 200
    # The old credential stays dead — re-enrolment issues a new secret.
    assert client.post(
        "/device-api/heartbeat",
        json={"battery_percent": 55, "firmware_version": "0.1.0"},
        headers=_device_headers(old_secret),
    ).status_code == 401


def test_revoking_an_assigned_device_stops_the_monitoring_it_implied(client, db_session):
    """The worst defect the edge-case review found.

    Regression: revoking left the assignment ACTIVE while destroying the
    credential. The patient panel still showed a device, the device got 401 on
    every report, and the offline sweep skipped it because that query filters
    on status == ACTIVE. The patient appeared monitored and silently was not —
    the exact failure this module exists to prevent.
    """
    from app.wearables.models import DeviceAssignment

    headers = _register_and_login(client)
    patient = client.post(
        "/patients",
        json={
            "first_name": "John", "last_name": "Doe", "date_of_birth": "1950-01-01",
            "preferred_language": "ENGLISH", "room_number": "204",
        },
        headers=headers,
    ).json()
    device, _secret = _enrolled_device(client, headers)
    client.post(
        f"/patients/{patient['id']}/wearable-assignment",
        json={"device_id": device["id"], "monitoring_profile": "FALL_RISK"},
        headers=headers,
    )

    client.post(f"/wearable-devices/{device['id']}/revoke", headers=headers)

    assert db_session.query(DeviceAssignment).one().unassigned_at is not None
    panel = client.get(f"/patients/{patient['id']}/wearable-assignment", headers=headers).json()
    assert panel["assignment"] is None


def test_revocation_records_whether_it_ended_monitoring(client, db_session):
    headers = _register_and_login(client)
    device, _ = _enrolled_device(client, headers)
    client.post(f"/wearable-devices/{device['id']}/revoke", headers=headers)

    event = (
        db_session.query(AuditEvent)
        .filter(AuditEvent.event_type == AuditEventType.WEARABLE_DEVICE_REVOKED.value)
        .one()
    )
    assert event.event_metadata["ended_active_assignment"] is False
