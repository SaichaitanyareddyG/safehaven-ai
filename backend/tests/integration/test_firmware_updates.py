"""Band firmware over Wi-Fi: offered only on the charger, only to bands,
checked by SHA-256, and every change of version is recorded."""

import hashlib

import pytest

from app.audit.models import AuditEvent
from app.wearables.firmware import FirmwareRelease, publish

# Smallest thing that passes the image check: the ESP32 magic byte first.
IMAGE = bytes([0xE9]) + b"\x00" * 4095


def _staff(client):
    client.post("/auth/register", json={"email": "n@example.com", "password": "supersecret123", "full_name": "N"})
    return {"Authorization": "Bearer " + client.post("/auth/login", json={"email": "n@example.com", "password": "supersecret123"}).json()["access_token"]}


@pytest.fixture()
def band(client):
    staff = _staff(client)
    code = client.post("/wearable-devices", json={"device_code": "SH-TEST-1"}, headers=staff).json()["enrollment_code"]
    secret = client.post("/device-api/enroll", json={"enrollment_code": code, "hardware_id": "EFUSE-TEST01"}).json()[
        "device_secret"
    ]
    return {"Authorization": f"Bearer {secret}"}


def _beat(client, band, version="0.4.0", charging=True):
    resp = client.post(
        "/device-api/heartbeat",
        json={"battery_percent": 80, "firmware_version": version, "charging": charging, "sensor_ok": True},
        headers=band,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_offered_only_on_the_charger_and_only_when_different(client, band, db_session):
    assert _beat(client, band)["firmware_update"] is None  # nothing published
    publish(db_session, "0.5.0", IMAGE)

    assert _beat(client, band, charging=False)["firmware_update"] is None  # on a wrist: never
    offer = _beat(client, band, charging=True)["firmware_update"]
    assert offer["version"] == "0.5.0" and offer["size"] == len(IMAGE)
    assert offer["sha256"] == hashlib.sha256(IMAGE).hexdigest()
    assert _beat(client, band, version="0.5.0")["firmware_update"] is None  # already running it


def test_download_needs_a_band_credential(client, band, db_session):
    release = publish(db_session, "0.5.0", IMAGE)
    path = f"/device-api/firmware/{release.id}"
    assert client.get(path).status_code == 401
    assert client.get(path, headers={"Authorization": "Bearer not-a-band"}).status_code == 401
    resp = client.get(path, headers=band)
    assert resp.status_code == 200 and resp.content == IMAGE


def test_publishing_switches_the_current_release_and_rejects_junk(db_session):
    publish(db_session, "0.5.0", IMAGE)
    publish(db_session, "0.5.1", IMAGE)
    assert [r.version for r in db_session.query(FirmwareRelease).filter_by(is_current=True)] == ["0.5.1"]
    with pytest.raises(ValueError):
        publish(db_session, "0.5.1", IMAGE)  # same version twice
    with pytest.raises(ValueError):
        publish(db_session, "0.6.0", b"not firmware")


def test_a_version_change_is_recorded(client, band, db_session):
    _beat(client, band, version="0.4.0")
    _beat(client, band, version="0.5.0")
    event = db_session.query(AuditEvent).filter_by(event_type="WEARABLE_FIRMWARE_CHANGED").one()
    assert event.event_metadata == {"from": "0.4.0", "to": "0.5.0"}
