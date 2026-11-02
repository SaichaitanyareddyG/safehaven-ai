"""Module 3 — alert lifecycle edges found in the 2026-11-02 review.

Each test is one way a real signal was lost or misfiled before.
"""

from datetime import datetime, timedelta, timezone

from app.wearables.models import DeviceAssignment, SafetyAlert, SensorEvent, WearableDevice
from tests.integration.test_wearable_events import FALL_METRICS, _assign, _enrolled_device, _send
from tests.integration.test_wearable_health import (
    _alerts,
    _create_active_patient,
    _heartbeat,
    _monitored,
    _register_and_login,
)


def _silent_since_yesterday(db_session, device_id, minutes=10):
    device = db_session.get(WearableDevice, device_id)
    device.last_seen_at = datetime.now(timezone.utc) - timedelta(minutes=minutes)
    for a in db_session.query(DeviceAssignment).filter(DeviceAssignment.device_id == device_id):
        a.assigned_at = datetime.now(timezone.utc) - timedelta(days=1)
    db_session.flush()


def _offline_alerts(client, headers):
    return [a for a in _alerts(client, headers)["results"] if a["alert_type"] == "DEVICE_OFFLINE"]


def test_swapping_a_dead_band_closes_its_alert_and_the_new_band_can_still_alert(client, db_session):
    headers = _register_and_login(client)
    patient, band1, secret1 = _monitored(client, headers, "SH-WEAR-001")
    _heartbeat(client, secret1)
    _silent_since_yesterday(db_session, band1["id"])
    [first] = _offline_alerts(client, headers)
    client.post(f"/safety-alerts/{first['id']}/acknowledge", headers=headers)

    # The nurse swaps bands without resolving the alert.
    client.delete(f"/patients/{patient['id']}/wearable-assignment", headers=headers)
    assert db_session.get(SafetyAlert, first["id"]).status.value == "RESOLVED"
    band2, secret2 = _enrolled_device(client, headers, "SH-WEAR-002")
    _assign(client, headers, patient["id"], band2["id"])
    _heartbeat(client, secret2)

    # Band 2 goes silent too: a new alert, not folded into band 1's.
    _silent_since_yesterday(db_session, band2["id"])
    [second] = _offline_alerts(client, headers)
    assert second["id"] != first["id"]
    assert second["device_code"] == "SH-WEAR-002"


def test_a_band_assigned_just_now_is_not_offline_because_it_was_in_a_drawer(client, db_session):
    headers = _register_and_login(client)
    _patient, band, _secret = _monitored(client, headers)
    device = db_session.get(WearableDevice, band["id"])
    device.last_seen_at = datetime.now(timezone.utc) - timedelta(days=1)  # off in a drawer, assigned just now
    db_session.flush()
    assert _offline_alerts(client, headers) == []


def test_a_band_taken_off_again_raises_a_new_alert(client, db_session):
    headers = _register_and_login(client)
    _patient, _band, secret = _monitored(client, headers)
    assert _send(client, secret, event_id="off-1", event_type="DEVICE_NOT_WORN", metrics={}).status_code == 201
    first = db_session.query(SafetyAlert).one()
    client.post(f"/safety-alerts/{first.id}/acknowledge", headers=headers)
    first.created_at = datetime.now(timezone.utc) - timedelta(hours=3)  # put back on, never resolved
    db_session.flush()

    assert _send(client, secret, event_id="off-2", event_type="DEVICE_NOT_WORN", metrics={}).status_code == 201
    assert db_session.query(SafetyAlert).filter(SafetyAlert.alert_type == first.alert_type).count() == 2


def test_an_event_after_the_old_patient_was_unassigned_goes_to_the_new_patient(client, db_session):
    """The band restarted with patient A saved and had not checked in when B,
    who has it now, pressed help."""
    headers = _register_and_login(client)
    patient_a, band, secret = _monitored(client, headers)
    old_assignment = client.get(
        f"/patients/{patient_a['id']}/wearable-assignment", headers=headers
    ).json()["assignment"]["id"]
    client.delete(f"/patients/{patient_a['id']}/wearable-assignment", headers=headers)
    patient_b = _create_active_patient(client, headers, first_name="Bea")
    _assign(client, headers, patient_b["id"], band["id"])

    resp = _send(client, secret, event_id="help-1", event_type="HELP_REQUESTED", metrics={},
                 assignment_id=old_assignment)
    assert resp.status_code == 201
    [alert] = db_session.query(SafetyAlert).all()
    assert str(alert.patient_id) == patient_b["id"]


def test_an_event_without_a_clock_is_dated_on_arrival_not_1970(client, db_session):
    headers = _register_and_login(client)
    _patient, _band, secret = _monitored(client, headers)
    before = datetime.now(timezone.utc) - timedelta(seconds=5)
    assert _send(client, secret, event_id="noclock", occurred_at_ms=0, metrics=FALL_METRICS).status_code == 201
    event = db_session.query(SensorEvent).one()
    assert event.occurred_at >= before


def test_a_timestamp_past_2100_is_refused_not_a_server_error(client):
    headers = _register_and_login(client)
    _patient, _band, secret = _monitored(client, headers)
    resp = _send(client, secret, event_id="far", occurred_at_ms=10**15)
    assert resp.status_code == 422
