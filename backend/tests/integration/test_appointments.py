"""Appointments: staff book, edit and cancel; the patient sees them in the
app; reminders the evening before and 2 hours before, without details."""

from datetime import datetime, timedelta, timezone

import pytest

from app.appointments.models import AppointmentReminderSent
from app.core import email as email_module
from app.core.config import get_settings
from app.core.email import EmailResult
from app.patient_app import push as push_module
from scripts.generate_vapid_keys import generate


@pytest.fixture()
def outbox(monkeypatch):
    sent = []
    monkeypatch.setattr(email_module, "send_email", lambda to, s, text, html: sent.append(text) or EmailResult(sent=True))
    return sent


@pytest.fixture()
def pushes(monkeypatch):
    public_key, private_key = generate()
    monkeypatch.setattr(get_settings(), "vapid_public_key", public_key)
    monkeypatch.setattr(get_settings(), "vapid_private_key", private_key)
    delivered = []
    monkeypatch.setattr(push_module, "send_to_subscription", lambda db, s, p: delivered.append(p) or True)
    return delivered


@pytest.fixture()
def setup(client, outbox):
    client.post("/auth/register", json={"email": "n@example.com", "password": "supersecret123", "full_name": "N"})
    staff = {"Authorization": "Bearer " + client.post("/auth/login", json={"email": "n@example.com", "password": "supersecret123"}).json()["access_token"]}
    patient = client.post(
        "/patients",
        json={"first_name": "Maria", "last_name": "L", "date_of_birth": "1950-01-01", "email": "m@example.com", "app_consent": True},
        headers=staff,
    ).json()
    token = outbox[0].split("#token=", 1)[1].split()[0]
    me = {"Authorization": "Bearer " + client.post("/patient-app/exchange", json={"token": token}).json()["access_token"]}
    return {"staff": staff, "patient": patient, "me": me}


def _book(client, setup, starts_at, **extra):
    resp = client.post(
        f"/patients/{setup['patient']['id']}/appointments",
        json={"title": "Cardiology check-up", "starts_at": starts_at.isoformat(), "location": "Clinic B, 2nd floor", **extra},
        headers=setup["staff"],
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_staff_book_and_patient_sees_it(client, setup):
    when = datetime.now(timezone.utc) + timedelta(days=3)
    booked = _book(client, setup, when, notes="Bring your medicines.")
    mine = client.get("/patient-app/me/appointments", headers=setup["me"]).json()["results"]
    assert [a["id"] for a in mine] == [booked["id"]]
    assert mine[0]["notes"] == "Bring your medicines."


def test_cancelled_appointments_disappear_for_the_patient(client, setup):
    booked = _book(client, setup, datetime.now(timezone.utc) + timedelta(days=3))
    resp = client.patch(f"/appointments/{booked['id']}", json={"status": "CANCELLED"}, headers=setup["staff"])
    assert resp.status_code == 200 and resp.json()["status"] == "CANCELLED"
    assert client.get("/patient-app/me/appointments", headers=setup["me"]).json()["results"] == []
    # Staff still see it, as cancelled.
    staff_list = client.get(f"/patients/{setup['patient']['id']}/appointments", headers=setup["staff"]).json()["results"]
    assert [a["status"] for a in staff_list] == ["CANCELLED"]


def test_validation(client, setup):
    pid = setup["patient"]["id"]
    past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    assert client.post(f"/patients/{pid}/appointments", json={"title": "X", "starts_at": past}, headers=setup["staff"]).status_code == 422
    naive = (datetime.now() + timedelta(days=1)).replace(tzinfo=None).isoformat()
    assert client.post(f"/patients/{pid}/appointments", json={"title": "X", "starts_at": naive}, headers=setup["staff"]).status_code == 422
    future = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    assert client.post(f"/patients/{pid}/appointments", json={"title": "  ", "starts_at": future}, headers=setup["staff"]).status_code == 422


def test_appointments_are_audited(client, setup):
    booked = _book(client, setup, datetime.now(timezone.utc) + timedelta(days=3))
    client.patch(f"/appointments/{booked['id']}", json={"location": "Clinic C"}, headers=setup["staff"])
    client.patch(f"/appointments/{booked['id']}", json={"status": "CANCELLED"}, headers=setup["staff"])
    types = [e["event_type"] for e in client.get(f"/patients/{setup['patient']['id']}/audit", headers=setup["staff"]).json()["results"]]
    assert {"APPOINTMENT_CREATED", "APPOINTMENT_UPDATED", "APPOINTMENT_CANCELLED"} <= set(types)


def test_patient_and_strangers_cannot_manage_appointments(client, setup):
    when = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    path = f"/patients/{setup['patient']['id']}/appointments"
    assert client.post(path, json={"title": "X", "starts_at": when}, headers=setup["me"]).status_code == 401
    assert client.get(path).status_code == 401


def _subscribe_and_discharge(client, setup):
    client.post("/patient-app/me/push", json={"endpoint": "https://push.example.com/a", "keys": {"p256dh": "p", "auth": "a"}}, headers=setup["me"])
    client.patch(f"/patients/{setup['patient']['id']}", json={"admission_status": "DISCHARGED"}, headers=setup["staff"])


def test_reminders_evening_before_and_two_hours_before(client, setup, pushes, db_session):
    _subscribe_and_discharge(client, setup)
    pushes.clear()
    tomorrow_1030 = (datetime.now(timezone.utc) + timedelta(days=1)).replace(hour=10, minute=30, second=0, microsecond=0)
    booked = _book(client, setup, tomorrow_1030)

    evening = (tomorrow_1030 - timedelta(days=1)).replace(hour=18, minute=5)
    assert push_module.run_appointment_reminders(db_session, evening) == 1
    assert push_module.run_appointment_reminders(db_session, evening + timedelta(minutes=1)) == 0  # once
    assert pushes[-1]["title"] == "Hospital appointment tomorrow at 10:30 AM"
    assert "Cardiology" not in str(pushes[-1]) and "Clinic" not in str(pushes[-1])

    assert push_module.run_appointment_reminders(db_session, tomorrow_1030 - timedelta(hours=2, minutes=-3)) == 1
    assert pushes[-1]["title"] == "Hospital appointment at 10:30 AM"

    # Rescheduling clears the reminders so the new time is reminded too.
    client.patch(f"/appointments/{booked['id']}", json={"starts_at": (tomorrow_1030 + timedelta(days=1)).isoformat()}, headers=setup["staff"])
    assert db_session.query(AppointmentReminderSent).count() == 0


def test_no_appointment_reminder_in_hospital_or_when_cancelled(client, setup, pushes, db_session):
    client.post("/patient-app/me/push", json={"endpoint": "https://push.example.com/a", "keys": {"p256dh": "p", "auth": "a"}}, headers=setup["me"])
    pushes.clear()
    tomorrow_1030 = (datetime.now(timezone.utc) + timedelta(days=1)).replace(hour=10, minute=30, second=0, microsecond=0)
    booked = _book(client, setup, tomorrow_1030)
    evening = (tomorrow_1030 - timedelta(days=1)).replace(hour=18, minute=5)
    assert push_module.run_appointment_reminders(db_session, evening) == 0  # still admitted

    client.patch(f"/patients/{setup['patient']['id']}", json={"admission_status": "DISCHARGED"}, headers=setup["staff"])
    client.patch(f"/appointments/{booked['id']}", json={"status": "CANCELLED"}, headers=setup["staff"])
    assert push_module.run_appointment_reminders(db_session, evening) == 0
    assert pushes == []
