"""Module 3 Stage 4 — alerts, deduplication and lifecycle.

Covers MODULE_3_IMPLEMENTATION_PLAN.md §28 tests 20–22, plus the demo scenarios
that turn on suppression: ordinary movement and a weak fall must produce
nothing, and one physical fall must produce exactly one alert.
"""

from datetime import datetime, timedelta, timezone

from app.audit.models import ActorType, AuditEvent, AuditEventType
from app.wearables.models import AlertStatus, SafetyAlert

STRONG_FALL = {
    "fall_score": 4,
    "peak_g": 4.025,
    "tilt_delta_deg": 90.2,
    "freefall_ms": 160,
    "inactive_ms": 2520,
    "stages_seen": ["freefall", "impact", "orientation", "inactivity"],
}
WEAK_FALL = {"fall_score": 1, "peak_g": 3.0, "stages_seen": ["impact"]}


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


def _send(client, secret, event_id="evt-1", event_type="POSSIBLE_FALL", metrics=None, age_s=0):
    occurred = datetime.now(timezone.utc) - timedelta(seconds=age_s)
    return client.post(
        "/device-api/events",
        json={
            "device_event_id": event_id,
            "event_type": event_type,
            "occurred_at_ms": int(occurred.timestamp() * 1000),
            "battery_percent": 73,
            "firmware_version": "0.1.0",
            "metrics": metrics if metrics is not None else STRONG_FALL,
        },
        headers={"Authorization": f"Bearer {secret}"},
    )


def _alerts(client, headers, **params):
    return client.get("/safety-alerts", headers=headers, params=params).json()


# ── an alert is raised, with the context a nurse needs ─────────────────────


def test_strong_fall_raises_a_high_priority_alert(client):
    headers = _register_and_login(client)
    patient, device, secret = _monitored(client, headers)

    _send(client, secret)

    body = _alerts(client, headers)
    assert body["total"] == 1
    alert = body["results"][0]
    assert alert["alert_type"] == "POSSIBLE_FALL"
    assert alert["priority"] == "HIGH"
    assert alert["status"] == "OPEN"
    assert alert["message"] == "Possible fall detected — check patient."
    # The context that makes it actionable.
    assert alert["patient_code"] == patient["patient_code"]
    assert alert["patient_name"] == "John Smith"
    assert alert["room_number"] == "204"
    assert alert["device_code"] == device["device_code"]
    assert alert["event_count"] == 1


def test_alert_message_never_states_a_cause(client):
    headers = _register_and_login(client)
    _patient, _device, secret = _monitored(client, headers, profile="RESTRICTED_MOBILITY")
    _send(client, secret, "e1", "ABNORMAL_MOVEMENT", {})
    _send(client, secret, "e2", "UNEXPECTED_MOBILITY", {})

    messages = " ".join(a["message"].lower() for a in _alerts(client, headers)["results"])
    for term in ("seizure", "left bed", "reaction", "neurolog", "diagnos"):
        assert term not in messages


# ── suppression: the demo scenarios that must produce NOTHING ──────────────


def test_weak_fall_raises_no_alert(client, db_session):
    """Demo scenario 3b — sitting down hard. The event is stored (it happened)
    but no nurse is disturbed."""
    headers = _register_and_login(client)
    _patient, _device, secret = _monitored(client, headers)

    resp = _send(client, secret, metrics=WEAK_FALL)
    assert resp.status_code == 201  # event accepted
    assert db_session.query(SafetyAlert).count() == 0
    assert _alerts(client, headers)["total"] == 0


def test_mobility_event_under_standard_profile_raises_no_alert(client, db_session):
    """Demo scenario 5 inverted: the same signal, monitoring not enabled."""
    headers = _register_and_login(client)
    _patient, _device, secret = _monitored(client, headers, profile="STANDARD")

    assert _send(client, secret, event_type="UNEXPECTED_MOBILITY", metrics={}).status_code == 201
    assert db_session.query(SafetyAlert).count() == 0


def test_mobility_event_under_restricted_profile_raises_medium(client):
    headers = _register_and_login(client)
    _patient, _device, secret = _monitored(client, headers, profile="RESTRICTED_MOBILITY")

    _send(client, secret, event_type="UNEXPECTED_MOBILITY", metrics={})

    alert = _alerts(client, headers)["results"][0]
    assert alert["alert_type"] == "UNEXPECTED_MOBILITY"
    assert alert["priority"] == "MEDIUM"


def test_discarded_event_raises_no_alert(client, db_session):
    """No assignment means no patient to alert about."""
    headers = _register_and_login(client)
    reg = client.post("/wearable-devices", json={"device_code": "SH-W-X"}, headers=headers).json()
    secret = client.post(
        "/device-api/enroll",
        json={"enrollment_code": reg["enrollment_code"], "hardware_id": "HW-X"},
    ).json()["device_secret"]

    assert _send(client, secret).status_code == 202
    assert db_session.query(SafetyAlert).count() == 0


# ── deduplication: one episode, one alert (§28 test 20) ────────────────────


def test_twenty_fall_events_produce_exactly_one_alert(client, db_session):
    """The alert-fatigue requirement, stated literally in the brief: one
    fall-like motion must not generate 20 alerts in 3 seconds."""
    headers = _register_and_login(client)
    _patient, _device, secret = _monitored(client, headers)

    for i in range(20):
        assert _send(client, secret, event_id=f"evt-{i:04d}").status_code == 201

    # Twenty real events...
    from app.wearables.models import SensorEvent

    assert db_session.query(SensorEvent).count() == 20
    # ...one alert.
    assert db_session.query(SafetyAlert).count() == 1

    alert = _alerts(client, headers)["results"][0]
    assert alert["event_count"] == 20  # the collapse is visible, not hidden


def test_different_alert_types_do_not_dedupe_together(client, db_session):
    headers = _register_and_login(client)
    _patient, _device, secret = _monitored(client, headers)

    _send(client, secret, "e1", "POSSIBLE_FALL", STRONG_FALL)
    _send(client, secret, "e2", "ABNORMAL_MOVEMENT", {})

    assert db_session.query(SafetyAlert).count() == 2


def test_different_patients_do_not_dedupe_together(client, db_session):
    headers = _register_and_login(client)
    _pa, _da, secret_a = _monitored(client, headers, "SH-WEAR-001", first_name="A")
    _pb, _db, secret_b = _monitored(client, headers, "SH-WEAR-002", first_name="B")

    _send(client, secret_a, "e1")
    _send(client, secret_b, "e1")

    assert db_session.query(SafetyAlert).count() == 2


def test_events_outside_the_dedupe_window_raise_a_second_alert(client, db_session):
    """A genuinely separate fall later deserves its own alert. Simulated by
    ageing the existing alert past the window."""
    headers = _register_and_login(client)
    _patient, _device, secret = _monitored(client, headers)
    _send(client, secret, "evt-1")

    alert = db_session.query(SafetyAlert).one()
    alert.created_at = datetime.now(timezone.utc) - timedelta(minutes=30)
    db_session.flush()

    _send(client, secret, "evt-2")
    assert db_session.query(SafetyAlert).count() == 2


def test_resolved_alert_does_not_absorb_new_events(client, db_session):
    """Once closed out, a new event is a new episode — otherwise a fall after a
    nurse finished dealing with the last one would be silently swallowed."""
    headers = _register_and_login(client)
    _patient, _device, secret = _monitored(client, headers)
    _send(client, secret, "evt-1")

    alert_id = _alerts(client, headers)["results"][0]["id"]
    client.post(f"/safety-alerts/{alert_id}/resolve", headers=headers)

    _send(client, secret, "evt-2")
    assert db_session.query(SafetyAlert).count() == 2


def test_acknowledged_alert_still_absorbs_events(client, db_session):
    """A nurse who has acknowledged and is walking to the room should not be
    handed a fresh alert for the same ongoing episode."""
    headers = _register_and_login(client)
    _patient, _device, secret = _monitored(client, headers)
    _send(client, secret, "evt-1")

    alert_id = _alerts(client, headers)["results"][0]["id"]
    client.post(f"/safety-alerts/{alert_id}/acknowledge", headers=headers)

    _send(client, secret, "evt-2")
    assert db_session.query(SafetyAlert).count() == 1
    assert db_session.query(SafetyAlert).one().event_count == 2


def test_duplicate_event_id_does_not_increment_event_count(client, db_session):
    """Idempotency and dedupe are different layers: a resent event is not a
    second observation."""
    headers = _register_and_login(client)
    _patient, _device, secret = _monitored(client, headers)

    for _ in range(3):
        _send(client, secret, event_id="evt-same")

    assert db_session.query(SafetyAlert).one().event_count == 1


def test_low_battery_dedupes_without_a_time_window(client, db_session):
    """A battery stays low for hours. A windowed rule would re-alert every
    couple of minutes, which is precisely the fatigue this avoids."""
    headers = _register_and_login(client)
    _patient, _device, secret = _monitored(client, headers)
    _send(client, secret, "b1", "DEVICE_LOW_BATTERY", {})

    alert = db_session.query(SafetyAlert).one()
    alert.created_at = datetime.now(timezone.utc) - timedelta(hours=6)
    db_session.flush()

    _send(client, secret, "b2", "DEVICE_LOW_BATTERY", {})
    assert db_session.query(SafetyAlert).count() == 1


def test_priority_escalates_but_never_downgrades(client, db_session):
    """An episode that gets worse should show it; one a nurse already saw as
    HIGH must not be quietly downgraded under them."""
    headers = _register_and_login(client)
    _patient, _device, secret = _monitored(client, headers, profile="STANDARD")

    # STANDARD abnormal movement is MEDIUM.
    _send(client, secret, "e1", "ABNORMAL_MOVEMENT", {})
    assert db_session.query(SafetyAlert).one().priority.value == "MEDIUM"

    # Escalate the assignment's profile, then send the same signal again.
    from app.wearables.models import DeviceAssignment, MonitoringProfile

    assignment = db_session.query(DeviceAssignment).one()
    assignment.monitoring_profile = MonitoringProfile.FALL_RISK
    db_session.flush()

    _send(client, secret, "e2", "ABNORMAL_MOVEMENT", {})
    alert = db_session.query(SafetyAlert).one()
    assert alert.priority.value == "HIGH"
    assert alert.event_count == 2


# ── delayed delivery ────────────────────────────────────────────────────────


def test_delayed_fall_still_alerts_and_is_flagged(client):
    """Suppressing an old fall would discard a real safety signal; presenting
    it as current would mislead. So: alert, and label it."""
    headers = _register_and_login(client)
    _patient, _device, secret = _monitored(client, headers)

    _send(client, secret, age_s=900)

    alert = _alerts(client, headers)["results"][0]
    assert alert["alert_type"] == "POSSIBLE_FALL"
    assert alert["delayed"] is True


# ── queue ordering and filtering ────────────────────────────────────────────


def test_queue_orders_high_priority_first_regardless_of_time(client):
    """A possible fall must never sit below a low battery."""
    headers = _register_and_login(client)
    _patient, _device, secret = _monitored(client, headers)

    _send(client, secret, "b1", "DEVICE_LOW_BATTERY", {})  # LOW, earlier
    _send(client, secret, "f1", "POSSIBLE_FALL", STRONG_FALL)  # HIGH, later

    results = _alerts(client, headers)["results"]
    assert [a["priority"] for a in results] == ["HIGH", "LOW"]


def test_queue_hides_resolved_alerts_by_default(client):
    """A dashboard showing resolved alerts by default would bury the ones
    needing action."""
    headers = _register_and_login(client)
    _patient, _device, secret = _monitored(client, headers)
    _send(client, secret)

    alert_id = _alerts(client, headers)["results"][0]["id"]
    client.post(f"/safety-alerts/{alert_id}/resolve", headers=headers)

    assert _alerts(client, headers)["total"] == 0
    assert _alerts(client, headers, status="RESOLVED")["total"] == 1


def test_queue_requires_a_clinician_jwt(client):
    headers = _register_and_login(client)
    _patient, _device, secret = _monitored(client, headers)

    assert client.get("/safety-alerts").status_code == 401
    # A device credential must not be able to read the ward's alert queue.
    assert client.get(
        "/safety-alerts", headers={"Authorization": f"Bearer {secret}"}
    ).status_code == 401


# ── lifecycle (§28 tests 21–22) ─────────────────────────────────────────────


def test_acknowledge_records_who_and_when(client, db_session):
    headers = _register_and_login(client)
    _patient, _device, secret = _monitored(client, headers)
    _send(client, secret)
    alert_id = _alerts(client, headers)["results"][0]["id"]

    resp = client.post(f"/safety-alerts/{alert_id}/acknowledge", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["status"] == "ACKNOWLEDGED"
    assert resp.json()["acknowledged_by"] is not None
    assert resp.json()["acknowledged_at"] is not None

    event = (
        db_session.query(AuditEvent)
        .filter(AuditEvent.event_type == AuditEventType.SAFETY_ALERT_ACKNOWLEDGED.value)
        .one()
    )
    assert event.actor_type is ActorType.CLINICIAN
    assert event.actor_id is not None


def test_acknowledge_is_idempotent_and_keeps_the_first_acknowledger(client):
    """A double-click must not rewrite who acknowledged it first."""
    headers_a = _register_and_login(client, "a@example.com")
    _patient, _device, secret = _monitored(client, headers_a)
    _send(client, secret)
    alert_id = _alerts(client, headers_a)["results"][0]["id"]

    first = client.post(f"/safety-alerts/{alert_id}/acknowledge", headers=headers_a).json()

    headers_b = _register_and_login(client, "b@example.com")
    second = client.post(f"/safety-alerts/{alert_id}/acknowledge", headers=headers_b).json()

    assert second["acknowledged_by"] == first["acknowledged_by"]
    assert second["acknowledged_at"] == first["acknowledged_at"]


def test_resolve_from_open_is_allowed(client):
    headers = _register_and_login(client)
    _patient, _device, secret = _monitored(client, headers)
    _send(client, secret)
    alert_id = _alerts(client, headers)["results"][0]["id"]

    resp = client.post(f"/safety-alerts/{alert_id}/resolve", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["status"] == "RESOLVED"
    assert resp.json()["resolved_at"] is not None


def test_acknowledging_a_resolved_alert_is_rejected(client):
    """It would move the record backwards."""
    headers = _register_and_login(client)
    _patient, _device, secret = _monitored(client, headers)
    _send(client, secret)
    alert_id = _alerts(client, headers)["results"][0]["id"]
    client.post(f"/safety-alerts/{alert_id}/resolve", headers=headers)

    resp = client.post(f"/safety-alerts/{alert_id}/acknowledge", headers=headers)
    assert resp.status_code == 409


def test_unknown_alert_is_404(client):
    headers = _register_and_login(client)
    resp = client.post(
        "/safety-alerts/00000000-0000-0000-0000-000000000000/acknowledge", headers=headers
    )
    assert resp.status_code == 404


def test_alert_lifecycle_is_fully_audited(client, db_session):
    headers = _register_and_login(client)
    patient, _device, secret = _monitored(client, headers)
    _send(client, secret)
    alert_id = _alerts(client, headers)["results"][0]["id"]
    client.post(f"/safety-alerts/{alert_id}/acknowledge", headers=headers)
    client.post(f"/safety-alerts/{alert_id}/resolve", headers=headers)

    types = {
        e.event_type
        for e in db_session.query(AuditEvent).filter(AuditEvent.patient_id == patient["id"]).all()
    }
    assert AuditEventType.SAFETY_ALERT_RAISED.value in types
    assert AuditEventType.SAFETY_ALERT_ACKNOWLEDGED.value in types
    assert AuditEventType.SAFETY_ALERT_RESOLVED.value in types


def test_alert_raised_is_audited_as_system(client, db_session):
    """No clinician raised it — the rules did."""
    headers = _register_and_login(client)
    _patient, _device, secret = _monitored(client, headers)
    _send(client, secret)

    event = (
        db_session.query(AuditEvent)
        .filter(AuditEvent.event_type == AuditEventType.SAFETY_ALERT_RAISED.value)
        .one()
    )
    assert event.actor_type is ActorType.SYSTEM
    assert event.actor_id is None
    assert event.event_metadata["priority"] == "HIGH"


def test_suppressed_event_writes_no_alert_audit_event(client, db_session):
    headers = _register_and_login(client)
    _patient, _device, secret = _monitored(client, headers)
    _send(client, secret, metrics=WEAK_FALL)

    assert (
        db_session.query(AuditEvent)
        .filter(AuditEvent.event_type == AuditEventType.SAFETY_ALERT_RAISED.value)
        .count()
        == 0
    )


def test_deduped_events_write_only_one_alert_audit_event(client, db_session):
    headers = _register_and_login(client)
    _patient, _device, secret = _monitored(client, headers)
    for i in range(5):
        _send(client, secret, event_id=f"e{i}")

    assert (
        db_session.query(AuditEvent)
        .filter(AuditEvent.event_type == AuditEventType.SAFETY_ALERT_RAISED.value)
        .count()
        == 1
    )


# ── alerts are immutable except through the lifecycle routes ───────────────


def test_no_patch_or_delete_route_exists_for_alerts(client):
    """Mirrors the existing audit-immutability test: the only ways to change an
    alert are acknowledge and resolve."""
    headers = _register_and_login(client)
    _patient, _device, secret = _monitored(client, headers)
    _send(client, secret)
    alert_id = _alerts(client, headers)["results"][0]["id"]

    assert client.patch(f"/safety-alerts/{alert_id}", json={}, headers=headers).status_code in (
        404,
        405,
    )
    assert client.delete(f"/safety-alerts/{alert_id}", headers=headers).status_code in (404, 405)
