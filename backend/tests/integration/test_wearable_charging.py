"""Module 3 — a band on its charger: detection paused, patient not monitored.

The band says so in its heartbeat; staff must see it, and a charging band must
not raise a low-battery alert about the battery it is busy charging.
"""


def _login(client, email="clinician@example.com", password="supersecret123"):
    client.post("/auth/register", json={"email": email, "password": password, "full_name": "Test Clinician"})
    token = client.post("/auth/login", json={"email": email, "password": password}).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _assigned_band(client):
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
        json={"device_id": reg["device"]["id"], "monitoring_profile": "FALL_RISK"},
        headers=headers,
    )
    return headers, patient, {"Authorization": f"Bearer {secret}"}


def _beat(client, device, battery, charging):
    return client.post(
        "/device-api/heartbeat",
        json={"battery_percent": battery, "firmware_version": "0.6.0", "charging": charging},
        headers=device,
    )


def test_charging_is_shown_on_the_device_list_and_the_patient(client):
    headers, patient, device = _assigned_band(client)
    assert _beat(client, device, 60, True).status_code == 200
    devices = client.get("/wearable-devices", headers=headers).json()["results"]
    assert devices[0]["charging"] is True
    assignment = client.get(f"/patients/{patient['id']}/wearable-assignment", headers=headers).json()
    assert assignment["assignment"]["device_charging"] is True

    _beat(client, device, 60, False)
    assert client.get("/wearable-devices", headers=headers).json()["results"][0]["charging"] is False


def test_no_low_battery_alert_while_charging(client):
    headers, _, device = _assigned_band(client)
    _beat(client, device, 10, True)
    alerts = client.get("/safety-alerts", headers=headers).json()["results"]
    assert [a for a in alerts if a["alert_type"] == "DEVICE_LOW_BATTERY"] == []
    _beat(client, device, 10, False)  # unplugged and still low: now it alerts
    alerts = client.get("/safety-alerts", headers=headers).json()["results"]
    assert [a["alert_type"] for a in alerts] == ["DEVICE_LOW_BATTERY"]


def test_older_bands_without_the_flag_still_check_in(client):
    _, _, device = _assigned_band(client)
    r = client.post("/device-api/heartbeat", json={"battery_percent": 80, "firmware_version": "0.5.0"}, headers=device)
    assert r.status_code == 200
