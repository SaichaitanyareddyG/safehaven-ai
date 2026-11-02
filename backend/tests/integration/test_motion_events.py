"""The fall detector's log: bands send summaries, staff label them."""

import pytest


def _login(client, email="n@example.com"):
    client.post("/auth/register", json={"email": email, "password": "supersecret123", "full_name": "N"})
    token = client.post("/auth/login", json={"email": email, "password": "supersecret123"}).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def staff(client):
    return _login(client)


@pytest.fixture()
def band(client, staff):
    registered = client.post("/wearable-devices", json={"device_code": "SH-TEST-M"}, headers=staff).json()
    secret = client.post(
        "/device-api/enroll",
        json={"enrollment_code": registered["enrollment_code"], "hardware_id": "EFUSE-MOTION1"},
    ).json()["device_secret"]
    return {"headers": {"Authorization": f"Bearer {secret}"}, "id": registered["device"]["id"]}


FLIP = {
    "occurred_at_ms": 1761400000000,
    "outcome": "CHECK",
    "freefall_ms": 0,
    "drop_cm": 0.0,
    "peak_g": 5.4,
    "turned_deg": 182.0,
    "tilt_change_deg": 171.0,
    "spin_dps": 2111.0,
    "axis": "X",
    "still_ms": 520,
}


def test_band_sends_staff_label(client, staff, band):
    drop = {**FLIP, "occurred_at_ms": FLIP["occurred_at_ms"] + 60000, "outcome": "ALERT", "freefall_ms": 320, "drop_cm": 50.2}
    resp = client.post(
        "/device-api/motion-events", json={"firmware_version": "0.7.7", "events": [FLIP, drop]}, headers=band["headers"]
    )
    assert resp.status_code == 204, resp.text

    rows = client.get(f"/wearable-devices/{band['id']}/motion-events", headers=staff).json()
    assert [r["outcome"] for r in rows] == ["ALERT", "CHECK"]  # newest first
    assert rows[0]["drop_cm"] == 50.2 and rows[1]["axis"] == "X" and rows[1]["label"] is None

    labelled = client.patch(f"/motion-events/{rows[1]['id']}", json={"label": "FLIP"}, headers=staff)
    assert labelled.status_code == 200 and labelled.json()["label"] == "FLIP"
    assert client.patch(f"/motion-events/{rows[1]['id']}", json={"label": None}, headers=staff).json()["label"] is None


def test_only_bands_send_and_only_staff_read(client, staff, band):
    assert client.post("/device-api/motion-events", json={"events": [FLIP]}).status_code == 401
    assert client.post("/device-api/motion-events", json={"events": [FLIP]}, headers=staff).status_code == 401
    assert client.get(f"/wearable-devices/{band['id']}/motion-events").status_code == 401


def test_bad_values_are_refused(client, band):
    bad = {**FLIP, "axis": "Q"}
    assert client.post("/device-api/motion-events", json={"events": [bad]}, headers=band["headers"]).status_code == 422
