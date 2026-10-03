"""Module 3 — the background job that notices silent bands without a dashboard."""

import asyncio
from datetime import datetime, timedelta, timezone

from app.wearables import sweeper
from app.wearables.models import SafetyAlert, WearableDevice


def _assigned_band(client):
    client.post("/auth/register", json={"email": "c@example.com", "password": "supersecret123", "full_name": "C"})
    headers = {"Authorization": "Bearer " + client.post(
        "/auth/login", json={"email": "c@example.com", "password": "supersecret123"}).json()["access_token"]}
    patient = client.post("/patients", json={"first_name": "Elena", "last_name": "Ruiz", "date_of_birth": "1948-03-02",
                                             "preferred_language": "ENGLISH", "room_number": "212"}, headers=headers).json()
    reg = client.post("/wearable-devices", json={"device_code": "SH-WEAR-001"}, headers=headers).json()
    secret = client.post("/device-api/enroll",
                         json={"enrollment_code": reg["enrollment_code"], "hardware_id": "HW-1"}).json()["device_secret"]
    client.post(f"/patients/{patient['id']}/wearable-assignment",
                json={"device_id": reg["device"]["id"], "monitoring_profile": "FALL_RISK"}, headers=headers)
    client.post("/device-api/heartbeat", json={"battery_percent": 80, "firmware_version": "0.6.0"},
                headers={"Authorization": f"Bearer {secret}"})
    return reg["device"]["id"]


def test_sweep_once_raises_offline_without_any_dashboard_request(client, db_session, monkeypatch):
    device_id = _assigned_band(client)
    db_session.query(WearableDevice).filter_by(id=device_id).update(
        {"last_seen_at": datetime.now(timezone.utc) - timedelta(minutes=10)})
    db_session.flush()
    # The job opens its own session; point it at the test transaction.
    monkeypatch.setattr(sweeper, "SessionLocal", lambda: _NoClose(db_session))
    assert sweeper.sweep_once() == 1
    assert sweeper.sweep_once() == 0  # dedupe: one alert per silence, not one per pass
    assert [a.alert_type.value for a in db_session.query(SafetyAlert).all()] == ["DEVICE_OFFLINE"]


def test_the_job_keeps_running_after_a_failed_pass(monkeypatch):
    calls = []

    def flaky():
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("database blip")
        return 0

    monkeypatch.setattr(sweeper, "sweep_once", flaky)

    async def run():
        task = asyncio.create_task(sweeper.run_offline_sweeper(0))
        while len(calls) < 3:
            await asyncio.sleep(0.01)
        task.cancel()

    asyncio.run(run())
    assert len(calls) >= 3


class _NoClose:
    """The test session, without close(): the fixture owns its lifetime."""

    def __init__(self, session):
        self._s = session

    def __getattr__(self, name):
        return getattr(self._s, name)

    def close(self):
        pass
