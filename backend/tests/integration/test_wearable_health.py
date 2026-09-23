"""Module 3 Stage 6 — device health: offline detection, battery, recovery.

Covers MODULE_3_IMPLEMENTATION_PLAN.md §28 tests 23–26.

The interesting property here is that offline detection runs with NO scheduler:
it is derived on read, and the nurse dashboard's poll is the sweep. These tests
therefore trigger it the same way the dashboard does — by listing alerts.
"""

from datetime import datetime, timedelta, timezone

from app.audit.models import ActorType, AuditEvent, AuditEventType
from app.wearables.models import AlertStatus, SafetyAlert, WearableDevice


def _register_and_login(client, email="clinician@example.com", password="supersecret123"):
    client.post("/auth/register", json={"email": email, "password": password, "full_name": "Test Clinician"})
    login_resp = client.post("/auth/login", json={"email": email, "password": password})
    return {"Authorization": f"Bearer {login_resp.json()['access_token']}"}


def _create_active_patient(client, headers, **overrides) -> dict:
    payload = {
        "first_name": "John",
        "last_name": "Smith",
        "date_of_birth": "1948-03-02",
        "preferred_language": "ENGLISH",
        "room_number": "204",
    }
    payload.update(overrides)
    return client.post("/patients", json=payload, headers=headers).json()


def _monitored(client, headers, device_code="SH-WEAR-001", profile="FALL_RISK", **patient_kw):
    patient = _create_active_patient(client, headers, **patient_kw)
    reg = client.post("/wearable-devices", json={"device_code": device_code}, headers=headers).json()
    secret = client.post(
        "/device-api/enroll",
        json={"enrollment_code": reg["enrollment_code"], "hardware_id": f"HW-{device_code}"},
    ).json()["device_secret"]
    client.post(
        f"/patients/{patient['id']}/wearable-assignment",
        json={"device_id": reg["device"]["id"], "monitoring_profile": profile},
        headers=headers,
    )
    return patient, reg["device"], secret


def _heartbeat(client, secret, battery=80):
    return client.post(
        "/device-api/heartbeat",
        json={"battery_percent": battery, "firmware_version": "0.1.0"},
        headers={"Authorization": f"Bearer {secret}"},
    )


def _alerts(client, headers, **params):
    """Listing alerts is also what triggers the offline sweep — same call the
    nurse dashboard makes every few seconds."""
    return client.get("/safety-alerts", headers=headers, params=params).json()


def _go_silent(db_session, device_code, minutes=10):
    """Backdate last_seen_at to simulate a device that stopped reporting."""
    device = (
        db_session.query(WearableDevice).filter(WearableDevice.device_code == device_code).one()
    )
    device.last_seen_at = datetime.now(timezone.utc) - timedelta(minutes=minutes)
    db_session.flush()
    return device


# ── heartbeat keeps a device online ─────────────────────────────────────────


def test_heartbeat_marks_device_online(client):
    headers = _register_and_login(client)
    _patient, _device, secret = _monitored(client, headers)
    _heartbeat(client, secret, battery=80)

    device = client.get("/wearable-devices", headers=headers).json()["results"][0]
    assert device["online"] is True
    assert device["battery_percent"] == 80


def test_freshly_assigned_device_is_not_offline_before_its_first_heartbeat(client):
    """assigned_at is the fallback reference. A device assigned ten seconds ago
    has not had time to check in, and alerting on that would fire on correct
    behaviour."""
    headers = _register_and_login(client)
    _monitored(client, headers)

    assert _alerts(client, headers)["total"] == 0
    device = client.get("/wearable-devices", headers=headers).json()["results"][0]
    assert device["online"] is True


def test_unassigned_device_is_never_reported_offline(client, db_session):
    """A device in a drawer is idle, not offline. Flagging it would fill the
    fleet view and the alert queue with false problems."""
    headers = _register_and_login(client)
    reg = client.post("/wearable-devices", json={"device_code": "SH-IDLE"}, headers=headers).json()
    client.post(
        "/device-api/enroll",
        json={"enrollment_code": reg["enrollment_code"], "hardware_id": "HW-IDLE"},
    )
    _go_silent(db_session, "SH-IDLE", minutes=600)

    assert _alerts(client, headers)["total"] == 0
    device = client.get("/wearable-devices", headers=headers).json()["results"][0]
    assert device["online"] is False  # not assigned, so not "online" either


# ── offline detection, derived on read (§28 test 26) ───────────────────────


def test_silent_assigned_device_raises_a_high_priority_offline_alert(client, db_session):
    headers = _register_and_login(client)
    patient, _device, secret = _monitored(client, headers)
    _heartbeat(client, secret)
    _go_silent(db_session, "SH-WEAR-001", minutes=10)

    body = _alerts(client, headers)
    assert body["total"] == 1
    alert = body["results"][0]
    assert alert["alert_type"] == "DEVICE_OFFLINE"
    # A patient-safety monitor that has silently stopped reporting is itself a
    # safety condition; the dangerous failure is a quiet device, not a noisy one.
    assert alert["priority"] == "HIGH"
    assert alert["message"] == "Safety monitor offline — device check required."
    assert alert["patient_code"] == patient["patient_code"]


def test_offline_alert_has_no_sensor_event(client, db_session):
    """It is derived from the ABSENCE of data, so there is no event to point at."""
    headers = _register_and_login(client)
    _monitored(client, headers)
    _go_silent(db_session, "SH-WEAR-001", minutes=10)
    _alerts(client, headers)

    assert db_session.query(SafetyAlert).one().sensor_event_id is None


def test_offline_is_detected_only_once_however_many_polls(client, db_session):
    """The dashboard polls every few seconds. Without operational dedupe this
    would be an alert per poll — the exact fatigue the module exists to avoid."""
    headers = _register_and_login(client)
    _monitored(client, headers)
    _go_silent(db_session, "SH-WEAR-001", minutes=10)

    for _ in range(6):
        _alerts(client, headers)

    assert db_session.query(SafetyAlert).count() == 1


def test_offline_detection_is_audited_as_system(client, db_session):
    headers = _register_and_login(client)
    _monitored(client, headers)
    _go_silent(db_session, "SH-WEAR-001", minutes=10)
    _alerts(client, headers)

    event = (
        db_session.query(AuditEvent)
        .filter(AuditEvent.event_type == AuditEventType.WEARABLE_DEVICE_OFFLINE_DETECTED.value)
        .one()
    )
    assert event.actor_type is ActorType.SYSTEM
    assert event.actor_id is None
    assert event.event_metadata["device_code"] == "SH-WEAR-001"


def test_fleet_view_also_triggers_the_sweep(client, db_session):
    """Both read paths sweep, so the fleet view and the alert queue can never
    disagree about which devices are silent."""
    headers = _register_and_login(client)
    _monitored(client, headers)
    _go_silent(db_session, "SH-WEAR-001", minutes=10)

    device = client.get("/wearable-devices", headers=headers).json()["results"][0]
    assert device["online"] is False
    assert db_session.query(SafetyAlert).count() == 1


def test_offline_alert_does_not_fire_for_a_revoked_device(client, db_session):
    headers = _register_and_login(client)
    _patient, device, _secret = _monitored(client, headers)
    _go_silent(db_session, "SH-WEAR-001", minutes=10)
    client.post(f"/wearable-devices/{device['id']}/revoke", headers=headers)

    assert _alerts(client, headers)["total"] == 0


# ── recovery (auto-resolve) ─────────────────────────────────────────────────


def test_offline_alert_auto_resolves_when_the_device_returns(client, db_session):
    """Left to a nurse, the queue would fill with alerts about devices that are
    demonstrably fine — and a queue of stale entries is one nobody reads."""
    headers = _register_and_login(client)
    _patient, _device, secret = _monitored(client, headers)
    _go_silent(db_session, "SH-WEAR-001", minutes=10)
    _alerts(client, headers)
    assert _alerts(client, headers)["total"] == 1

    _heartbeat(client, secret)

    assert _alerts(client, headers)["total"] == 0
    alert = db_session.query(SafetyAlert).one()
    assert alert.status is AlertStatus.RESOLVED
    # No clinician did this, so nobody is credited with it.
    assert alert.resolved_by is None


def test_auto_resolution_is_audited_as_system_with_a_reason(client, db_session):
    headers = _register_and_login(client)
    _patient, _device, secret = _monitored(client, headers)
    _go_silent(db_session, "SH-WEAR-001", minutes=10)
    _alerts(client, headers)
    _heartbeat(client, secret)

    event = (
        db_session.query(AuditEvent)
        .filter(
            AuditEvent.event_type == AuditEventType.SAFETY_ALERT_RESOLVED.value,
            AuditEvent.actor_type == ActorType.SYSTEM,
        )
        .one()
    )
    assert event.event_metadata["reason"] == "device_reconnected"


# ── low battery (§28 test 25) ───────────────────────────────────────────────


def test_low_battery_heartbeat_raises_a_low_priority_alert(client):
    """Derived from the heartbeat as well as accepted as a device-sent event,
    so low battery still surfaces if firmware never emits the event."""
    headers = _register_and_login(client)
    _patient, _device, secret = _monitored(client, headers)

    _heartbeat(client, secret, battery=15)

    body = _alerts(client, headers)
    assert body["total"] == 1
    assert body["results"][0]["alert_type"] == "DEVICE_LOW_BATTERY"
    assert body["results"][0]["priority"] == "LOW"


def test_low_battery_is_edge_triggered_not_per_heartbeat(client, db_session):
    """A battery sits at 19% for hours. One alert, not one every 30 seconds."""
    headers = _register_and_login(client)
    _patient, _device, secret = _monitored(client, headers)

    for battery in (18, 17, 16, 15, 14):
        _heartbeat(client, secret, battery=battery)

    assert db_session.query(SafetyAlert).count() == 1


def test_battery_exactly_at_the_threshold_alerts(client, db_session):
    headers = _register_and_login(client)
    _patient, _device, secret = _monitored(client, headers)
    _heartbeat(client, secret, battery=20)
    assert db_session.query(SafetyAlert).count() == 1


def test_healthy_battery_raises_nothing(client, db_session):
    headers = _register_and_login(client)
    _patient, _device, secret = _monitored(client, headers)
    _heartbeat(client, secret, battery=90)
    assert db_session.query(SafetyAlert).count() == 0


def test_battery_alert_auto_resolves_after_charging(client, db_session):
    headers = _register_and_login(client)
    _patient, _device, secret = _monitored(client, headers)
    _heartbeat(client, secret, battery=12)
    assert _alerts(client, headers)["total"] == 1

    _heartbeat(client, secret, battery=95)

    assert _alerts(client, headers)["total"] == 0
    assert db_session.query(SafetyAlert).one().status is AlertStatus.RESOLVED


def test_device_sent_battery_event_and_heartbeat_do_not_double_alert(client, db_session):
    """Both paths exist deliberately; the operational dedupe is what stops them
    producing two alerts for one flat battery."""
    headers = _register_and_login(client)
    _patient, _device, secret = _monitored(client, headers)

    _heartbeat(client, secret, battery=15)
    client.post(
        "/device-api/events",
        json={
            "device_event_id": "b1",
            "event_type": "DEVICE_LOW_BATTERY",
            "occurred_at_ms": int(datetime.now(timezone.utc).timestamp() * 1000),
            "battery_percent": 15,
            "firmware_version": "0.1.0",
            "metrics": {},
        },
        headers={"Authorization": f"Bearer {secret}"},
    )

    assert db_session.query(SafetyAlert).count() == 1


# ── clinical alerts are never auto-resolved ────────────────────────────────


def test_a_fall_alert_is_never_auto_resolved_by_a_heartbeat(client, db_session):
    """"The patient stopped moving" is not evidence that anyone checked on
    them. Only device-health alerts clear themselves."""
    headers = _register_and_login(client)
    _patient, _device, secret = _monitored(client, headers)
    client.post(
        "/device-api/events",
        json={
            "device_event_id": "f1",
            "event_type": "POSSIBLE_FALL",
            "occurred_at_ms": int(datetime.now(timezone.utc).timestamp() * 1000),
            "metrics": {"fall_score": 4, "stages_seen": ["freefall", "impact", "orientation", "inactivity"]},
        },
        headers={"Authorization": f"Bearer {secret}"},
    )
    assert _alerts(client, headers)["total"] == 1

    for _ in range(3):
        _heartbeat(client, secret, battery=90)

    body = _alerts(client, headers)
    assert body["total"] == 1
    assert body["results"][0]["alert_type"] == "POSSIBLE_FALL"
    assert body["results"][0]["status"] == "OPEN"


# ── edge-case review regressions ────────────────────────────────────────────


def test_discharge_resolves_device_health_alerts(client, db_session):
    """Regression: an open DEVICE_OFFLINE alert survived discharge and could
    never be cleared. The assignment ends, so the offline sweep no longer sees
    the device and a reconnect cannot auto-resolve it — the alert sat in the
    live queue forever, about a patient who had gone home.
    """
    headers = _register_and_login(client)
    patient, _device, secret = _monitored(client, headers)
    _go_silent(db_session, "SH-WEAR-001", minutes=30)
    _alerts(client, headers)
    assert _alerts(client, headers)["total"] == 1

    client.patch(
        f"/patients/{patient['id']}", json={"admission_status": "DISCHARGED"}, headers=headers
    )

    assert _alerts(client, headers)["total"] == 0
    assert db_session.query(SafetyAlert).one().status is AlertStatus.RESOLVED


def test_discharge_resolves_a_low_battery_alert_too(client, db_session):
    headers = _register_and_login(client)
    patient, _device, secret = _monitored(client, headers)
    _heartbeat(client, secret, battery=8)
    assert _alerts(client, headers)["total"] == 1

    client.patch(
        f"/patients/{patient['id']}", json={"admission_status": "DISCHARGED"}, headers=headers
    )
    assert _alerts(client, headers)["total"] == 0


def test_discharge_does_NOT_resolve_a_clinical_alert(client, db_session):
    """Deliberate asymmetry. A fall that happened is still a fall, and closing
    it is a human decision — not a side effect of paperwork. Only device-health
    alerts clear themselves at discharge."""
    headers = _register_and_login(client)
    patient, _device, secret = _monitored(client, headers)
    client.post(
        "/device-api/events",
        json={
            "device_event_id": "f1", "event_type": "POSSIBLE_FALL",
            "occurred_at_ms": int(datetime.now(timezone.utc).timestamp() * 1000),
            "metrics": {"fall_score": 4, "stages_seen": ["freefall", "impact", "orientation", "inactivity"]},
        },
        headers={"Authorization": f"Bearer {secret}"},
    )
    assert _alerts(client, headers)["total"] == 1

    client.patch(
        f"/patients/{patient['id']}", json={"admission_status": "DISCHARGED"}, headers=headers
    )

    body = _alerts(client, headers)
    assert body["total"] == 1
    assert body["results"][0]["alert_type"] == "POSSIBLE_FALL"
    assert body["results"][0]["status"] == "OPEN"
