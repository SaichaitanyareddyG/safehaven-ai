"""Module 3 — device-initiated pairing ("Add device" from the dashboard).

A new band shows a code; a clinician types it in; the band collects a
single-use enrolment code and enrols through the ordinary path. These tests pin
the security properties: only a clinician can approve, only the band that
asked can collect, everything is single-use and expires.
"""

from datetime import datetime, timedelta, timezone

from app.wearables.models import DevicePairingRequest


def _login(client, email="clinician@example.com", password="supersecret123"):
    client.post("/auth/register", json={"email": email, "password": password, "full_name": "Test Clinician"})
    token = client.post("/auth/login", json={"email": email, "password": password}).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _start(client, hw="HW-NEW-1"):
    resp = client.post("/device-api/pairing", json={"hardware_id": hw})
    assert resp.status_code == 200
    return resp.json()


def _poll(client, start, token=None):
    return client.post(
        "/device-api/pairing/poll",
        json={"pairing_id": start["pairing_id"], "poll_token": token or start["poll_token"]},
    )


def _pair(client, headers, code, label="SH-WEAR-002"):
    return client.post("/wearable-devices/pair", json={"pairing_code": code, "device_code": label}, headers=headers)


def test_band_gets_a_six_digit_code(client):
    start = _start(client)
    assert len(start["pairing_code"]) == 6 and start["pairing_code"].isdigit()
    assert start["expires_in_s"] == 600
    assert _poll(client, start).json() == {"status": "PENDING", "enrollment_code": None}


def test_full_flow_ends_with_an_enrolled_device(client):
    headers = _login(client)
    start = _start(client, hw="HW-ABC")

    resp = _pair(client, headers, start["pairing_code"], "sh-wear-002")
    assert resp.status_code == 201
    assert resp.json()["device_code"] == "SH-WEAR-002"

    polled = _poll(client, start).json()
    assert polled["status"] == "APPROVED" and polled["enrollment_code"]

    enrolled = client.post(
        "/device-api/enroll", json={"enrollment_code": polled["enrollment_code"], "hardware_id": "HW-ABC"}
    )
    assert enrolled.status_code == 200
    secret = enrolled.json()["device_secret"]
    hb = client.post(
        "/device-api/heartbeat",
        json={"battery_percent": 80, "firmware_version": "0.5.0"},
        headers={"Authorization": f"Bearer {secret}"},
    )
    assert hb.status_code == 200


def test_enrolment_code_is_handed_over_only_once(client):
    headers = _login(client)
    start = _start(client)
    _pair(client, headers, start["pairing_code"])
    assert _poll(client, start).json()["status"] == "APPROVED"
    second = _poll(client, start).json()
    assert second == {"status": "EXPIRED", "enrollment_code": None}


def test_only_the_band_that_asked_can_collect(client):
    headers = _login(client)
    start = _start(client)
    _pair(client, headers, start["pairing_code"])
    assert _poll(client, start, token="x" * 40).status_code == 404
    # ...and the real band still gets it afterwards.
    assert _poll(client, start).json()["status"] == "APPROVED"


def test_approving_needs_a_clinician(client):
    start = _start(client)
    assert _pair(client, {}, start["pairing_code"]).status_code == 401


def test_unknown_code_is_404(client):
    headers = _login(client)
    assert _pair(client, headers, "123456").status_code == 404  # no band is showing any code


def test_code_cannot_be_used_twice(client):
    headers = _login(client)
    start = _start(client)
    assert _pair(client, headers, start["pairing_code"], "SH-WEAR-010").status_code == 201
    assert _pair(client, headers, start["pairing_code"], "SH-WEAR-011").status_code == 404


def test_expired_code_cannot_be_approved(client, db_session):
    headers = _login(client)
    start = _start(client)
    req = db_session.get(DevicePairingRequest, __import__("uuid").UUID(start["pairing_id"]))
    req.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    db_session.commit()
    assert _pair(client, headers, start["pairing_code"]).status_code == 404
    assert _poll(client, start).json()["status"] == "EXPIRED"


def test_duplicate_label_is_409(client):
    headers = _login(client)
    first = _start(client, hw="HW-1")
    assert _pair(client, headers, first["pairing_code"], "SH-WEAR-020").status_code == 201
    second = _start(client, hw="HW-2")
    # register_device rolls the session back on the unique violation. In
    # production that is one request's session and the pairing request (an
    # earlier request) survives for a retry; in this harness the rollback also
    # undoes the test's own rows, so the retry is not asserted here.
    assert _pair(client, headers, second["pairing_code"], "SH-WEAR-020").status_code == 409


def test_poll_token_is_stored_hashed(client, db_session):
    start = _start(client)
    req = db_session.get(DevicePairingRequest, __import__("uuid").UUID(start["pairing_id"]))
    assert req.poll_token_hash != start["poll_token"]
    assert len(req.poll_token_hash) == 64
