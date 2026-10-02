"""Module 3 Stage 10 — the band's QR code.

The QR carries an opaque token, never patient identity (plan §11). These tests
pin the properties that make that safe: the token is random, reaches only the
device it belongs to, resolves only for a clinician, and stops resolving the
moment monitoring ends — so a reused band can never point at its last patient.
"""

from app.audit.models import AuditEvent, AuditEventType
from app.wearables.models import DeviceAssignment


def _register_and_login(client, email="clinician@example.com", password="supersecret123"):
    client.post("/auth/register", json={"email": email, "password": password, "full_name": "Test Clinician"})
    login_resp = client.post("/auth/login", json={"email": email, "password": password})
    return {"Authorization": f"Bearer {login_resp.json()['access_token']}"}


def _patient(client, headers, **overrides) -> dict:
    payload = {
        "first_name": "Elena",
        "last_name": "Ruiz",
        "date_of_birth": "1948-03-02",
        "preferred_language": "ENGLISH",
        "room_number": "12B",
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


def _qr(client, secret) -> str | None:
    body = client.post(
        "/device-api/heartbeat",
        json={"battery_percent": 70, "firmware_version": "0.4.0"},
        headers={"Authorization": f"Bearer {secret}"},
    ).json()
    return (body["assignment"] or {}).get("qr_token")


def _resolve(client, headers, token):
    return client.post("/wearable-assignments/resolve", json={"token": token}, headers=headers)


def _assigned_band(client):
    headers = _register_and_login(client)
    patient = _patient(client, headers)
    device, secret = _enrolled_device(client, headers)
    _assign(client, headers, patient["id"], device["id"])
    return headers, patient, device, secret


def test_assigned_device_receives_a_qr_token(client):
    _, _, _, secret = _assigned_band(client)
    token = _qr(client, secret)
    assert token and 12 <= len(token) <= 32


def test_qr_token_carries_nothing_about_the_patient(client):
    _, patient, _, secret = _assigned_band(client)
    token = _qr(client, secret)
    for leak in ("Elena", "Ruiz", "12B", "1948", patient["patient_code"], patient["id"]):
        assert leak.lower() not in token.lower()


def test_clinician_scan_resolves_the_patient(client):
    headers, patient, device, secret = _assigned_band(client)
    token = _qr(client, secret)

    resp = _resolve(client, headers, f"SH:{token}")  # as scanned, prefix included
    assert resp.status_code == 200
    body = resp.json()
    assert body["patient_id"] == patient["id"]
    assert body["patient_code"] == patient["patient_code"]
    assert body["patient_name"] == "Elena Ruiz"
    assert body["room_number"] == "12B"
    assert body["device_code"] == device["device_code"]
    assert body["monitoring_profile"] == "FALL_RISK"

    assert _resolve(client, headers, token).status_code == 200  # prefix optional


def test_resolve_requires_a_clinician_jwt(client):
    _, _, _, secret = _assigned_band(client)
    token = _qr(client, secret)
    assert _resolve(client, {}, token).status_code == 401
    # The device's own credential must not open the staff route either.
    assert _resolve(client, {"Authorization": f"Bearer {secret}"}, token).status_code == 401


def test_unknown_token_is_a_generic_404(client):
    headers, _, _, _ = _assigned_band(client)
    resp = _resolve(client, headers, "SH:not-a-real-token")
    assert resp.status_code == 404


def test_unassigning_kills_the_old_qr(client):
    headers, patient, _, secret = _assigned_band(client)
    token = _qr(client, secret)
    client.delete(f"/patients/{patient['id']}/wearable-assignment", headers=headers)

    assert _resolve(client, headers, token).status_code == 404
    assert _qr(client, secret) is None


def test_discharge_kills_the_old_qr(client):
    headers, patient, _, secret = _assigned_band(client)
    token = _qr(client, secret)
    client.patch(f"/patients/{patient['id']}", json={"admission_status": "DISCHARGED"}, headers=headers)

    assert _resolve(client, headers, token).status_code == 404


def test_reassigned_band_never_resolves_to_its_previous_patient(client):
    headers, first, device, secret = _assigned_band(client)
    old_token = _qr(client, secret)
    client.delete(f"/patients/{first['id']}/wearable-assignment", headers=headers)

    second = _patient(client, headers, first_name="Arjun", last_name="Rao", room_number="7")
    _assign(client, headers, second["id"], device["id"])
    new_token = _qr(client, secret)

    assert new_token != old_token
    assert _resolve(client, headers, old_token).status_code == 404
    assert _resolve(client, headers, new_token).json()["patient_id"] == second["id"]


def test_every_assignment_gets_a_distinct_token(client, db_session):
    headers = _register_and_login(client)
    tokens = set()
    for i in range(5):
        p = _patient(client, headers, first_name=f"P{i}")
        d, _ = _enrolled_device(client, headers, device_code=f"SH-WEAR-{100 + i}")
        _assign(client, headers, p["id"], d["id"])
    for a in db_session.query(DeviceAssignment).all():
        tokens.add(a.qr_token)
    assert len(tokens) == 5 and None not in tokens


def test_scan_is_audited_on_the_patients_trail(client, db_session):
    headers, patient, _, secret = _assigned_band(client)
    _resolve(client, headers, _qr(client, secret))
    rows = (
        db_session.query(AuditEvent)
        .filter(AuditEvent.event_type == AuditEventType.WEARABLE_QR_RESOLVED)
        .all()
    )
    assert len(rows) == 1
    assert str(rows[0].patient_id) == patient["id"]
