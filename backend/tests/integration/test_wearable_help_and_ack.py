"""Module 3 — the help button, and the band learning that a nurse responded.

Two halves of one loop: the wearer can ask for help without falling first,
and whatever raised the alert, the band can tell them "a nurse is coming" once
a nurse acknowledges it — without ever learning who it is worn by.
"""

import time


def _login(client, email="clinician@example.com", password="supersecret123"):
    client.post("/auth/register", json={"email": email, "password": password, "full_name": "Test Clinician"})
    token = client.post("/auth/login", json={"email": email, "password": password}).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _assigned_band(client, profile="STANDARD"):
    headers = _login(client)
    patient = client.post(
        "/patients",
        json={"first_name": "Elena", "last_name": "Ruiz", "date_of_birth": "1948-03-02",
              "preferred_language": "ENGLISH", "room_number": "212"},
        headers=headers,
    ).json()
    reg = client.post("/wearable-devices", json={"device_code": "SH-WEAR-001"}, headers=headers).json()
    secret = client.post(
        "/device-api/enroll", json={"enrollment_code": reg["enrollment_code"], "hardware_id": "HW-1"}
    ).json()["device_secret"]
    client.post(
        f"/patients/{patient['id']}/wearable-assignment",
        json={"device_id": reg["device"]["id"], "monitoring_profile": profile},
        headers=headers,
    )
    return headers, patient, {"Authorization": f"Bearer {secret}"}


def _event(client, device, event_type, event_id, metrics=None, occurred_ms=None):
    return client.post(
        "/device-api/events",
        json={
            "device_event_id": event_id,
            "event_type": event_type,
            "occurred_at_ms": occurred_ms or int(time.time() * 1000),
            "metrics": metrics or {},
        },
        headers=device,
    )


def _heartbeat(client, device):
    return client.post(
        "/device-api/heartbeat", json={"battery_percent": 80, "firmware_version": "0.5.0"}, headers=device
    ).json()


def _open_alerts(client, headers):
    return client.get("/safety-alerts", headers=headers).json()["results"]


def test_help_button_raises_a_high_priority_alert(client):
    headers, patient, device = _assigned_band(client)
    assert _event(client, device, "HELP_REQUESTED", "ev-1").status_code == 201
    alerts = _open_alerts(client, headers)
    assert len(alerts) == 1
    assert alerts[0]["alert_type"] == "HELP_REQUESTED"
    assert alerts[0]["priority"] == "HIGH"
    assert alerts[0]["patient_id"] == patient["id"]
    assert "help button" in alerts[0]["message"]


def test_help_alerts_regardless_of_profile(client):
    headers, _, device = _assigned_band(client, profile="STANDARD")
    _event(client, device, "HELP_REQUESTED", "ev-1")
    assert _open_alerts(client, headers)[0]["priority"] == "HIGH"


def test_heartbeat_has_no_alert_when_nothing_happened(client):
    _, _, device = _assigned_band(client)
    assert _heartbeat(client, device)["alert"] is None


def test_band_sees_open_then_acknowledged_then_resolved(client):
    headers, _, device = _assigned_band(client)
    occurred = int(time.time() * 1000)
    _event(client, device, "POSSIBLE_FALL", "ev-1",
           metrics={"fall_score": 4, "stages_seen": ["freefall", "impact", "orientation", "inactivity"]},
           occurred_ms=occurred)

    view = _heartbeat(client, device)["alert"]
    assert view["alert_type"] == "POSSIBLE_FALL" and view["status"] == "OPEN"
    assert abs(view["last_event_at_ms"] - occurred) < 1000  # the band matches its own event by this

    alert_id = _open_alerts(client, headers)[0]["id"]
    client.post(f"/safety-alerts/{alert_id}/acknowledge", headers=headers)
    assert _heartbeat(client, device)["alert"]["status"] == "ACKNOWLEDGED"

    client.post(f"/safety-alerts/{alert_id}/resolve", headers=headers)
    assert _heartbeat(client, device)["alert"]["status"] == "RESOLVED"


def test_alert_view_tells_the_band_nothing_about_the_patient(client):
    _, patient, device = _assigned_band(client)
    _event(client, device, "HELP_REQUESTED", "ev-1")
    body = _heartbeat(client, device)
    assert set(body["alert"].keys()) == {"alert_type", "status", "last_event_at_ms"}
    blob = str(body)
    for leak in ("Elena", "Ruiz", "212", patient["patient_code"], patient["id"]):
        assert leak not in blob


def test_device_health_alerts_are_not_shown_to_the_wearer(client):
    _, _, device = _assigned_band(client)
    _event(client, device, "DEVICE_LOW_BATTERY", "ev-1")
    assert _heartbeat(client, device)["alert"] is None
