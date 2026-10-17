"""Taken / Skipped, dose reminders by Web Push and the staff adherence view."""

from datetime import datetime, timedelta, timezone

import pytest

from app.core import email as email_module
from app.core.config import get_settings
from app.core.email import EmailResult
from app.patient_app import push as push_module
from app.patient_app.models import DoseReminderSent, PushSubscription
from scripts.generate_vapid_keys import generate

BID = "Take Metoprolol 25 mg orally twice daily with food."
PRN = "Take Paracetamol 500 mg orally every 6 hours as needed for pain."


@pytest.fixture()
def outbox(monkeypatch):
    sent = []
    monkeypatch.setattr(
        email_module, "send_email", lambda to, subject, text, html: sent.append(text) or EmailResult(sent=True)
    )
    return sent


@pytest.fixture()
def pushes(monkeypatch):
    """Web Push switched on with real keys; deliveries captured, not sent."""
    public_key, private_key = generate()
    settings = get_settings()
    monkeypatch.setattr(settings, "vapid_public_key", public_key)
    monkeypatch.setattr(settings, "vapid_private_key", private_key)
    monkeypatch.setattr(settings, "reminder_tick_secret", "tick-secret-for-tests")
    delivered = []

    def fake_send(db, subscription, payload):
        delivered.append({"endpoint": subscription.endpoint, **payload})
        return True

    monkeypatch.setattr(push_module, "send_to_subscription", fake_send)
    return delivered


def _staff(client):
    client.post("/auth/register", json={"email": "nurse@example.com", "password": "supersecret123", "full_name": "N"})
    token = client.post("/auth/login", json={"email": "nurse@example.com", "password": "supersecret123"}).json()
    return {"Authorization": f"Bearer {token['access_token']}"}


def _approve(client, staff, patient_id, text):
    created = client.post(f"/patients/{patient_id}/instructions", json={"text": text}, headers=staff).json()
    client.post(f"/instructions/{created['id']}/analyze", headers=staff)
    client.post(f"/instructions/{created['id']}/generate", headers=staff)
    assert client.post(f"/instructions/{created['id']}/approve", headers=staff).json()["status"] == "APPROVED"
    return created["id"]


@pytest.fixture()
def setup(client, outbox):
    staff = _staff(client)
    patient = client.post(
        "/patients",
        json={
            "first_name": "Maria",
            "last_name": "L",
            "date_of_birth": "1950-01-01",
            "email": "m@example.com",
            "app_consent": True,
            "reason_for_visit": "Hip surgery",
        },
        headers=staff,
    ).json()
    bid = _approve(client, staff, patient["id"], BID)
    _approve(client, staff, patient["id"], PRN)
    token = outbox[0].split("#token=", 1)[1].split()[0]
    session = client.post("/patient-app/exchange", json={"token": token}).json()
    me = {"Authorization": f"Bearer {session['access_token']}"}
    return {"staff": staff, "patient": patient, "me": me, "bid": bid}


def test_todays_doses_come_from_the_schedule(client, setup):
    body = client.get("/patient-app/me/doses", headers=setup["me"]).json()
    assert body["at_home"] is False
    # Twice daily -> two doses; the as-needed medicine has none.
    assert [(d["medication_name"], d["time"]) for d in body["doses"]] == [("Metoprolol", "08:00"), ("Metoprolol", "20:00")]
    assert all(d["status"] is None for d in body["doses"])


def test_taken_skipped_and_undo(client, setup):
    me, today = setup["me"], client.get("/patient-app/me/doses", headers=setup["me"]).json()["date"]
    dose = {"instruction_id": setup["bid"], "date": today, "time": "08:00"}
    assert client.post("/patient-app/me/doses", json={**dose, "status": "TAKEN"}, headers=me).status_code == 204
    assert client.post("/patient-app/me/doses", json={**dose, "time": "20:00", "status": "SKIPPED"}, headers=me).status_code == 204
    statuses = [d["status"] for d in client.get("/patient-app/me/doses", headers=me).json()["doses"]]
    assert statuses == ["TAKEN", "SKIPPED"]

    client.post("/patient-app/me/doses", json={**dose, "status": None}, headers=me)
    assert [d["status"] for d in client.get("/patient-app/me/doses", headers=me).json()["doses"]] == [None, "SKIPPED"]


def test_cannot_log_a_dose_that_is_not_scheduled(client, setup):
    me, today = setup["me"], client.get("/patient-app/me/doses", headers=setup["me"]).json()["date"]
    bad_time = {"instruction_id": setup["bid"], "date": today, "time": "14:00", "status": "TAKEN"}
    assert client.post("/patient-app/me/doses", json=bad_time, headers=me).status_code == 409
    future = (datetime.fromisoformat(today) + timedelta(days=1)).date().isoformat()
    tomorrow = {"instruction_id": setup["bid"], "date": future, "time": "08:00", "status": "TAKEN"}
    assert client.post("/patient-app/me/doses", json=tomorrow, headers=me).status_code == 409


def test_stopped_medicine_drops_off_today(client, setup):
    client.patch(f"/instructions/{setup['bid']}/clinical-status", json={"status": "STOPPED"}, headers=setup["staff"])
    assert client.get("/patient-app/me/doses", headers=setup["me"]).json()["doses"] == []


def test_another_patients_dose_cannot_be_logged(client, setup, outbox):
    other = client.post(
        "/patients", json={"first_name": "O", "last_name": "P", "date_of_birth": "1950-01-01"}, headers=setup["staff"]
    ).json()
    other_bid = _approve(client, setup["staff"], other["id"], BID)
    today = client.get("/patient-app/me/doses", headers=setup["me"]).json()["date"]
    resp = client.post(
        "/patient-app/me/doses",
        json={"instruction_id": other_bid, "date": today, "time": "08:00", "status": "TAKEN"},
        headers=setup["me"],
    )
    assert resp.status_code == 409


def _pin_clock(monkeypatch, hour):
    from app.patient_app import doses

    pinned = doses.hospital_now().replace(hour=hour, minute=0, second=0, microsecond=0)
    monkeypatch.setattr(doses, "hospital_now", lambda: pinned)


def test_adherence_for_staff(client, setup, monkeypatch):
    _pin_clock(monkeypatch, 21)
    me, today = setup["me"], client.get("/patient-app/me/doses", headers=setup["me"]).json()["date"]
    client.post("/patient-app/me/doses", json={"instruction_id": setup["bid"], "date": today, "time": "08:00", "status": "TAKEN"}, headers=me)
    body = client.get(f"/patients/{setup['patient']['id']}/app-access/adherence?days=7", headers=setup["staff"]).json()
    assert len(body["days"]) == 7
    assert body["days"][-1] == {"date": today, "due": 2, "taken": 1, "skipped": 0}
    assert body["days"][0]["due"] == 0  # before the medicine started
    assert client.get(f"/patients/{setup['patient']['id']}/app-access/adherence", headers=me).status_code == 401


def test_adherence_does_not_count_doses_not_yet_due(client, setup, monkeypatch):
    _pin_clock(monkeypatch, 12)
    body = client.get(f"/patients/{setup['patient']['id']}/app-access/adherence?days=1", headers=setup["staff"]).json()
    assert body["days"][-1]["due"] == 1  # the 8 AM dose; 8 PM is still to come


def _subscribe(client, me, endpoint="https://push.example.com/abc"):
    return client.post(
        "/patient-app/me/push", json={"endpoint": endpoint, "keys": {"p256dh": "p" * 87, "auth": "a" * 22}}, headers=me
    )


def test_subscribing_sends_a_test_notification(client, setup, pushes):
    assert client.get("/patient-app/push").json()["available"] is True
    assert _subscribe(client, setup["me"]).status_code == 204
    assert [p["title"] for p in pushes] == ["Reminders are on"]


def _tick(client, db_session, now):
    from app.patient_app.push import run_reminders

    return run_reminders(db_session, now=now)


def test_reminders_only_at_home_once_per_dose_time_without_medicine_names(client, setup, pushes, db_session):
    _subscribe(client, setup["me"])
    pushes.clear()
    today = datetime.fromisoformat(client.get("/patient-app/me/doses", headers=setup["me"]).json()["date"])
    at_8_05 = today.replace(hour=8, minute=5, tzinfo=timezone.utc)

    # In hospital: nurses give the doses, no reminder.
    assert _tick(client, db_session, at_8_05) == 0 and pushes == []

    client.patch(f"/patients/{setup['patient']['id']}", json={"admission_status": "DISCHARGED"}, headers=setup["staff"])
    assert _tick(client, db_session, at_8_05) == 1
    assert _tick(client, db_session, at_8_05 + timedelta(minutes=1)) == 0  # once only
    assert pushes[0]["title"] == "Time for your 8:00 AM medicine"
    assert "Metoprolol" not in str(pushes[0])

    # Too early, and far past the window: nothing.
    assert _tick(client, db_session, today.replace(hour=19, minute=59, tzinfo=timezone.utc)) == 0
    assert _tick(client, db_session, today.replace(hour=21, minute=0, tzinfo=timezone.utc)) == 0


def test_no_reminder_for_a_dose_already_answered(client, setup, pushes, db_session):
    _subscribe(client, setup["me"])
    client.patch(f"/patients/{setup['patient']['id']}", json={"admission_status": "DISCHARGED"}, headers=setup["staff"])
    pushes.clear()
    today = client.get("/patient-app/me/doses", headers=setup["me"]).json()["date"]
    client.post(
        "/patient-app/me/doses",
        json={"instruction_id": setup["bid"], "date": today, "time": "20:00", "status": "TAKEN"},
        headers=setup["me"],
    )
    at_8pm = datetime.fromisoformat(today).replace(hour=20, minute=1, tzinfo=timezone.utc)
    assert _tick(client, db_session, at_8pm) == 0 and pushes == []
    assert db_session.query(DoseReminderSent).count() == 0


def test_revoking_access_removes_the_phone(client, setup, pushes, db_session):
    _subscribe(client, setup["me"])
    client.post(f"/patients/{setup['patient']['id']}/app-access/revoke", headers=setup["staff"])
    assert db_session.query(PushSubscription).count() == 0


def test_tick_endpoint_needs_the_secret(client, pushes):
    assert client.post("/internal/reminders/tick").status_code == 404
    assert client.post("/internal/reminders/tick", headers={"X-Tick-Secret": "wrong"}).status_code == 404
    resp = client.post("/internal/reminders/tick", headers={"X-Tick-Secret": "tick-secret-for-tests"})
    assert resp.status_code == 200 and resp.json() == {"sent": 0}


def test_discharge_closes_the_current_visit(client, setup):
    client.patch(f"/patients/{setup['patient']['id']}", json={"admission_status": "DISCHARGED"}, headers=setup["staff"])
    visits = client.get("/patient-app/me/visits", headers=setup["me"]).json()["visits"]
    assert all(v["status"] == "CLOSED" and v["discharge_date"] for v in visits)


def test_dose_times_are_saved_as_approved(client, setup, db_session, monkeypatch):
    """Later rule changes must never rewrite what the clinician approved."""
    from app.instructions.models import CareInstruction
    from app.schedules import instruction_schedule
    from app.schedules.dose_schedule import DoseSchedule

    saved = db_session.get(CareInstruction, setup["bid"]).dose_schedule
    assert saved["kind"] == "SCHEDULED" and saved["times"] == ["08:00", "20:00"] and saved["start_date"]

    monkeypatch.setattr(
        instruction_schedule, "derive_schedule", lambda *a, **k: DoseSchedule(kind="NEEDS_REVIEW", problem="changed")
    )
    medicine = next(
        i for i in client.get("/patient-app/me/care-plan", headers=setup["me"]).json()["instructions"] if i["id"] == setup["bid"]
    )
    assert medicine["schedule"]["times"] == ["08:00", "20:00"]
    assert [d["time"] for d in client.get("/patient-app/me/doses", headers=setup["me"]).json()["doses"]] == ["08:00", "20:00"]


def test_start_date_is_the_hospital_day_not_the_utc_day():
    from datetime import datetime, timezone

    from app.core.config import get_settings
    from app.schedules.instruction_schedule import hospital_date

    settings = get_settings()
    original = settings.hospital_timezone
    try:
        settings.hospital_timezone = "Asia/Kolkata"
        # 20:00 UTC on Oct 16 is 01:30 on Oct 17 in Delhi.
        assert hospital_date(datetime(2026, 10, 16, 20, 0, tzinfo=timezone.utc)).isoformat() == "2026-10-17"
    finally:
        settings.hospital_timezone = original


# --- Review follow-ups --------------------------------------------------------


def _at_home_with_phone(client, setup):
    _subscribe(client, setup["me"])
    client.patch(f"/patients/{setup['patient']['id']}", json={"admission_status": "DISCHARGED"}, headers=setup["staff"])


def _today(client, setup):
    return datetime.fromisoformat(client.get("/patient-app/me/doses", headers=setup["me"]).json()["date"])


def test_no_reminder_once_access_has_ended(client, setup, pushes, db_session):
    from app.patient_app.models import PatientAppAccount

    _at_home_with_phone(client, setup)
    today = _today(client, setup)  # before access ends: the patient API refuses after
    db_session.query(PatientAppAccount).update(
        {PatientAppAccount.access_expires_at: datetime.now(timezone.utc) - timedelta(minutes=1)}
    )
    db_session.flush()
    pushes.clear()
    assert _tick(client, db_session, today.replace(hour=8, minute=5, tzinfo=timezone.utc)) == 0


def test_no_reminder_for_a_stopped_medicine(client, setup, pushes, db_session):
    _at_home_with_phone(client, setup)
    today = _today(client, setup)
    client.patch(f"/instructions/{setup['bid']}/clinical-status", json={"status": "STOPPED"}, headers=setup["staff"])
    pushes.clear()
    assert _tick(client, db_session, today.replace(hour=8, minute=5, tzinfo=timezone.utc)) == 0


def test_no_reminder_after_the_course_ends(client, setup, pushes, db_session):
    from app.instructions.models import CareInstruction

    _at_home_with_phone(client, setup)
    instruction = db_session.get(CareInstruction, setup["bid"])
    ended = dict(instruction.dose_schedule)
    ended["duration_days"] = 1
    ended["start_date"] = (_today(client, setup) - timedelta(days=3)).date().isoformat()
    instruction.dose_schedule = ended
    db_session.flush()
    pushes.clear()
    assert _tick(client, db_session, _today(client, setup).replace(hour=8, minute=5, tzinfo=timezone.utc)) == 0


def test_a_failed_delivery_is_tried_again(client, setup, monkeypatch, db_session):
    from app.patient_app import push as push_module

    public_key, private_key = generate()
    monkeypatch.setattr(get_settings(), "vapid_public_key", public_key)
    monkeypatch.setattr(get_settings(), "vapid_private_key", private_key)
    outcomes = [False, True]
    monkeypatch.setattr(push_module, "send_to_subscription", lambda db, s, p: outcomes.pop(0))
    db_session.add(PushSubscription(patient_id=setup["patient"]["id"], endpoint="https://push.example.com/x", p256dh="p", auth="a"))
    client.patch(f"/patients/{setup['patient']['id']}", json={"admission_status": "DISCHARGED"}, headers=setup["staff"])
    at = _today(client, setup).replace(hour=8, minute=5, tzinfo=timezone.utc)
    assert _tick(client, db_session, at) == 0  # push service failed
    assert _tick(client, db_session, at + timedelta(minutes=1)) == 1  # tried again


def test_minutes_away_from_any_dose_time_do_no_work(client, setup, pushes, db_session, monkeypatch):
    from app.patient_app import push as push_module

    _at_home_with_phone(client, setup)
    monkeypatch.setattr(push_module, "scheduled_doses", lambda *a, **k: (_ for _ in ()).throw(AssertionError("queried")))
    assert _tick(client, db_session, _today(client, setup).replace(hour=9, minute=45, tzinfo=timezone.utc)) == 0


def test_dose_two_days_ago_cannot_be_logged(client, setup):
    two_days_ago = (_today(client, setup) - timedelta(days=2)).date().isoformat()
    resp = client.post(
        "/patient-app/me/doses",
        json={"instruction_id": setup["bid"], "date": two_days_ago, "time": "08:00", "status": "TAKEN"},
        headers=setup["me"],
    )
    assert resp.status_code == 409


def test_answering_the_same_dose_twice_updates_it(client, setup):
    today = _today(client, setup).date().isoformat()
    dose = {"instruction_id": setup["bid"], "date": today, "time": "08:00"}
    assert client.post("/patient-app/me/doses", json={**dose, "status": "TAKEN"}, headers=setup["me"]).status_code == 204
    assert client.post("/patient-app/me/doses", json={**dose, "status": "SKIPPED"}, headers=setup["me"]).status_code == 204
    statuses = [d["status"] for d in client.get("/patient-app/me/doses", headers=setup["me"]).json()["doses"]]
    assert statuses == ["SKIPPED", None]


def test_past_days_count_until_the_day_a_medicine_was_stopped(client, setup, db_session):
    from app.instructions.models import CareInstruction, ClinicalStatus
    from app.patient_app.doses import scheduled_doses

    today = _today(client, setup).date()
    instruction = db_session.get(CareInstruction, setup["bid"])
    snapshot = dict(instruction.dose_schedule)
    snapshot["start_date"] = (today - timedelta(days=5)).isoformat()
    instruction.dose_schedule = snapshot
    instruction.clinical_status = ClinicalStatus.STOPPED
    instruction.clinical_end_date = today - timedelta(days=2)
    db_session.flush()
    patient_id = instruction.patient_id
    assert len(scheduled_doses(db_session, patient_id, today - timedelta(days=3), today)) == 2  # before the stop
    assert scheduled_doses(db_session, patient_id, today - timedelta(days=2), today) == []  # the stop day
    assert scheduled_doses(db_session, patient_id, today, today) == []


def test_tick_secret_with_unusual_characters_is_a_plain_404(client, pushes):
    resp = client.post("/internal/reminders/tick", headers={"X-Tick-Secret": "sécret".encode("latin-1")})
    assert resp.status_code == 404
