"""Wi-Fi networks for the bands: admins list them, passwords are encrypted at
rest and never shown again, and only an enrolled band receives them."""

import pytest

from app.audit.models import AuditEvent
from app.auth.models import User
from app.wearables.wifi import WifiNetwork


def _login(client, email):
    client.post("/auth/register", json={"email": email, "password": "supersecret123", "full_name": "X"})
    token = client.post("/auth/login", json={"email": email, "password": "supersecret123"}).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def admin(client, db_session):
    headers = _login(client, "boss@example.com")
    db_session.query(User).filter(User.email == "boss@example.com").update({User.role: "admin"})
    db_session.flush()
    return headers


@pytest.fixture()
def band(client, admin):
    registered = client.post("/wearable-devices", json={"device_code": "SH-TEST-W"}, headers=admin).json()
    secret = client.post(
        "/device-api/enroll",
        json={"enrollment_code": registered["enrollment_code"], "hardware_id": "EFUSE-WIFI01"},
    ).json()["device_secret"]
    return {"Authorization": f"Bearer {secret}"}


def _beat(client, band):
    resp = client.post(
        "/device-api/heartbeat",
        json={"battery_percent": 80, "firmware_version": "0.7.1", "charging": False, "sensor_ok": True},
        headers=band,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


WARD = {"label": "Ward 3", "ssid": "Hospital-Ward3", "password": "correct horse battery"}


def test_a_band_gets_the_networks_admins_add(client, admin, band, db_session):
    before = _beat(client, band)["wifi_networks_version"]
    assert client.get("/device-api/wifi-networks", headers=band).json()["networks"] == []

    resp = client.post("/wifi-networks", json=WARD, headers=admin)
    assert resp.status_code == 201, resp.text
    assert "password" not in resp.json()

    after = _beat(client, band)["wifi_networks_version"]
    assert after != before  # the band knows to fetch
    got = client.get("/device-api/wifi-networks", headers=band).json()
    assert got["version"] == after
    assert got["networks"] == [
        {"ssid": "Hospital-Ward3", "security": "PSK", "password": "correct horse battery", "username": None, "identity": None}
    ]

    # Stored encrypted, listed without it.
    stored = db_session.query(WifiNetwork).one()
    assert "correct horse" not in stored.password_encrypted
    listed = client.get("/wifi-networks", headers=admin).json()
    assert [n["ssid"] for n in listed["items"]] == ["Hospital-Ward3"] and "password" not in listed["items"][0]

    assert client.delete(f"/wifi-networks/{stored.id}", headers=admin).status_code == 204
    assert client.get("/device-api/wifi-networks", headers=band).json()["networks"] == []
    assert _beat(client, band)["wifi_networks_version"] == before

    kinds = [e.event_type for e in db_session.query(AuditEvent).filter(AuditEvent.entity_type == "WifiNetwork")]
    assert sorted(kinds) == ["WIFI_NETWORK_ADDED", "WIFI_NETWORK_REMOVED"]
    assert all("correct horse" not in str(e.event_metadata) for e in db_session.query(AuditEvent))


def test_only_admins_manage_and_only_bands_receive(client, admin, band):
    nurse = _login(client, "nurse@example.com")
    assert client.get("/wifi-networks", headers=nurse).status_code == 403
    assert client.post("/wifi-networks", json=WARD, headers=nurse).status_code == 403
    client.post("/wifi-networks", json=WARD, headers=admin)
    assert client.get("/device-api/wifi-networks").status_code == 401
    assert client.get("/device-api/wifi-networks", headers=nurse).status_code == 401


@pytest.mark.parametrize(
    "body, problem",
    [
        ({"ssid": "Short", "password": "1234567"}, "8 to 63"),
        ({"ssid": "Corp", "security": "EAP", "password": "pw"}, "username"),
    ],
)
def test_bad_networks_are_refused(client, admin, body, problem):
    resp = client.post("/wifi-networks", json=body, headers=admin)
    assert resp.status_code == 422 and problem in resp.json()["detail"]


def test_the_same_network_twice_is_refused(client, admin):
    assert client.post("/wifi-networks", json=WARD, headers=admin).status_code == 201
    assert client.post("/wifi-networks", json=WARD, headers=admin).status_code == 422


def test_enterprise_networks_carry_the_username(client, admin, band):
    body = {"ssid": "Corp", "security": "EAP", "username": "band01", "password": "pw-for-band"}
    assert client.post("/wifi-networks", json=body, headers=admin).status_code == 201
    (net,) = client.get("/device-api/wifi-networks", headers=band).json()["networks"]
    assert net["security"] == "EAP" and net["username"] == "band01" and net["password"] == "pw-for-band"
