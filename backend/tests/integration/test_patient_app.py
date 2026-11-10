"""The patient app: invite on registration, passwordless sign-in, the
patient's own read-only API, revoke and discharge."""

from datetime import datetime, timedelta, timezone

import pytest

from app.core import email as email_module
from app.core.email import EmailResult
from app.patient_app.models import PatientAppAccount, PatientSignInLink

MEDICATION_TEXT = "Take Metoprolol 25 mg orally twice daily with food."


def _staff(client, email="nurse@example.com"):
    client.post("/auth/register", json={"email": email, "password": "supersecret123", "full_name": "Nurse"})
    resp = client.post("/auth/login", json={"email": email, "password": "supersecret123"})
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


@pytest.fixture()
def outbox(monkeypatch):
    sent = []

    def fake_send(to, subject, text, html):
        sent.append({"to": to, "subject": subject, "text": text, "html": html})
        return EmailResult(sent=True)

    monkeypatch.setattr(email_module, "send_email", fake_send)
    return sent


def _register(client, headers, **extra):
    payload = {"first_name": "Maria", "last_name": "Lopez", "date_of_birth": "1950-01-01", **extra}
    resp = client.post("/patients", json=payload, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _token_from(mail) -> str:
    assert "/my/sign-in#token=" in mail["text"]
    return mail["text"].split("#token=", 1)[1].split()[0]


def _sign_in(client, token) -> dict:
    resp = client.post("/patient-app/set-password", json={"token": token, "password": "patientpass1"})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def _approve(client, headers, patient_id, text):
    created = client.post(f"/patients/{patient_id}/instructions", json={"text": text}, headers=headers).json()
    client.post(f"/instructions/{created['id']}/analyze", headers=headers)
    generated = client.post(f"/instructions/{created['id']}/generate", headers=headers).json()
    assert generated["status"] == "READY_FOR_APPROVAL", generated
    assert client.post(f"/instructions/{created['id']}/approve", headers=headers).json()["status"] == "APPROVED"
    return created


def test_registering_with_email_and_consent_emails_an_invite(client, outbox):
    staff = _staff(client)
    patient = _register(client, staff, email=" Maria@Example.com ", phone="555 0100", app_consent=True)

    assert patient["email"] == "maria@example.com"
    assert patient["app_invite"] == {"emailed": True, "problem": None, "link": None}
    assert len(outbox) == 1 and outbox[0]["to"] == "maria@example.com"
    # No medical details, and not even the name, in the email.
    for part in ("text", "html"):
        assert "Maria" not in outbox[0][part] and "Lopez" not in outbox[0][part]

    access = client.get(f"/patients/{patient['id']}/app-access", headers=staff).json()
    assert access["status"] == "INVITED" and access["consent_at"] is not None


def test_no_invite_without_consent_or_email(client, outbox):
    staff = _staff(client)
    no_consent = _register(client, staff, email="a@example.com")
    no_email = _register(client, staff, app_consent=True)
    assert no_consent["app_invite"] is None and no_email["app_invite"] is None
    assert outbox == []
    assert client.get(f"/patients/{no_consent['id']}/app-access", headers=staff).json()["status"] == "NOT_INVITED"

    # Inviting later still needs consent.
    resp = client.post(f"/patients/{no_consent['id']}/app-access/invite", json={}, headers=staff)
    assert resp.status_code == 409
    resp = client.post(f"/patients/{no_consent['id']}/app-access/invite", json={"consent": True}, headers=staff)
    assert resp.status_code == 200 and resp.json()["emailed"] is True


def test_invalid_email_is_rejected(client):
    staff = _staff(client)
    resp = client.post(
        "/patients",
        json={"first_name": "A", "last_name": "B", "date_of_birth": "1950-01-01", "email": "not-an-email"},
        headers=staff,
    )
    assert resp.status_code == 422


def test_link_signs_in_once_and_shows_the_approved_care_plan(client, outbox):
    staff = _staff(client)
    patient = _register(client, staff, email="maria@example.com", app_consent=True)
    _approve(client, staff, patient["id"], MEDICATION_TEXT)
    token = _token_from(outbox[0])

    me = _sign_in(client, token)
    assert client.post("/patient-app/set-password", json={"token": token, "password": "patientpass1"}).status_code == 410

    profile = client.get("/patient-app/me", headers=me).json()
    assert profile["first_name"] == "Maria" and profile["admission_status"] == "ACTIVE"

    plan = client.get("/patient-app/me/care-plan", headers=me).json()
    assert len(plan["instructions"]) == 1
    assert plan["instructions"][0]["instruction_type"] == "MEDICATION"
    assert "Metoprolol" in plan["instructions"][0]["text_by_language"]["ENGLISH"]

    access = client.get(f"/patients/{patient['id']}/app-access", headers=staff).json()
    assert access["status"] == "ACTIVE" and access["last_sign_in_at"] is not None


def test_visits_come_from_encounters(client, outbox):
    staff = _staff(client)
    patient = _register(client, staff, email="maria@example.com", app_consent=True, reason_for_visit="Hip surgery")
    me = _sign_in(client, _token_from(outbox[0]))
    visits = client.get("/patient-app/me/visits", headers=me).json()["visits"]
    assert len(visits) == 1 and visits[0]["reason_for_visit"] == "Hip surgery" and visits[0]["status"] == "OPEN"


def test_patient_sees_only_their_own_records(client, outbox):
    staff = _staff(client)
    maria = _register(client, staff, email="maria@example.com", app_consent=True)
    other = _register(client, staff, first_name="Other")
    _approve(client, staff, other["id"], MEDICATION_TEXT)
    me = _sign_in(client, _token_from(outbox[0]))
    assert client.get("/patient-app/me/care-plan", headers=me).json()["instructions"] == []
    assert client.get("/patient-app/me", headers=me).json()["first_name"] == maria["first_name"]


def test_patient_and_staff_tokens_never_cross(client, outbox):
    staff = _staff(client)
    patient = _register(client, staff, email="maria@example.com", app_consent=True)
    me = _sign_in(client, _token_from(outbox[0]))

    assert client.get("/patients", headers=me).status_code == 401
    assert client.get(f"/patients/{patient['id']}", headers=me).status_code == 401
    assert client.get("/auth/me", headers=me).status_code == 401
    assert client.get("/patient-app/me", headers=staff).status_code == 401
    assert client.get("/patient-app/me").status_code == 401


def test_request_link_never_reveals_who_is_a_patient(client, outbox):
    staff = _staff(client)
    _register(client, staff, email="maria@example.com", app_consent=True)
    outbox.clear()

    unknown = client.post("/patient-app/request-link", json={"email": "nobody@example.com"})
    known = client.post("/patient-app/request-link", json={"email": "MARIA@example.com"})
    assert unknown.status_code == known.status_code == 202
    assert unknown.json() == known.json()
    assert [m["to"] for m in outbox] == ["maria@example.com"]
    # The fresh sign-in link works, and replaced the unused invite.
    _sign_in(client, _token_from(outbox[0]))


def test_sign_in_link_expires(client, outbox, db_session):
    staff = _staff(client)
    _register(client, staff, email="maria@example.com", app_consent=True)
    db_session.query(PatientSignInLink).update(
        {PatientSignInLink.expires_at: datetime.now(timezone.utc) - timedelta(seconds=1)}
    )
    db_session.flush()
    assert client.post("/patient-app/set-password", json={"token": _token_from(outbox[0]), "password": "patientpass1"}).status_code == 410


def test_revoke_signs_the_patient_out_and_blocks_new_links(client, outbox):
    staff = _staff(client)
    patient = _register(client, staff, email="maria@example.com", app_consent=True)
    me = _sign_in(client, _token_from(outbox[0]))

    resp = client.post(f"/patients/{patient['id']}/app-access/revoke", headers=staff)
    assert resp.status_code == 200 and resp.json()["status"] == "REVOKED"
    assert client.get("/patient-app/me", headers=me).status_code == 401

    outbox.clear()
    client.post("/patient-app/request-link", json={"email": "maria@example.com"})
    assert outbox == []

    # Staff can invite again; the old session stays dead.
    client.post(f"/patients/{patient['id']}/app-access/invite", json={}, headers=staff)
    again = _sign_in(client, _token_from(outbox[-1]))
    assert client.get("/patient-app/me", headers=again).status_code == 200
    assert client.get("/patient-app/me", headers=me).status_code == 401


def test_discharge_keeps_the_app_working_until_staff_turn_it_off(client, outbox, db_session):
    """No end date after discharge (2026-11-09): the app is how a patient at
    home gets reminders. Staff turning it off is what stops it."""
    staff = _staff(client)
    patient = _register(client, staff, email="maria@example.com", app_consent=True)
    me = _sign_in(client, _token_from(outbox[0]))

    client.patch(f"/patients/{patient['id']}", json={"admission_status": "DISCHARGED"}, headers=staff)
    profile = client.get("/patient-app/me", headers=me).json()
    assert profile["admission_status"] == "DISCHARGED" and profile["access_expires_at"] is None
    assert db_session.query(PatientAppAccount).one().access_expires_at is None

    client.post(f"/patients/{patient['id']}/app-access/revoke", headers=staff)
    assert client.get("/patient-app/me", headers=me).status_code == 401


def test_one_app_login_per_email(client, outbox):
    staff = _staff(client)
    _register(client, staff, email="family@example.com", app_consent=True)
    resp = client.post(
        "/patients",
        json={
            "first_name": "B",
            "last_name": "C",
            "date_of_birth": "1950-01-01",
            "email": "Family@example.com",
            "app_consent": True,
        },
        headers=staff,
    )
    assert resp.status_code == 409


def test_failed_email_returns_the_link_for_staff(client, monkeypatch):
    monkeypatch.setattr(
        email_module, "send_email", lambda *a, **k: EmailResult(sent=False, problem="Email is not set up on this server")
    )
    staff = _staff(client)
    patient = _register(client, staff, email="maria@example.com", app_consent=True)
    invite = patient["app_invite"]
    assert invite["emailed"] is False and "/my/sign-in#token=" in invite["link"]
    _sign_in(client, invite["link"].split("#token=", 1)[1])


def test_app_events_are_audited(client, outbox):
    staff = _staff(client)
    patient = _register(client, staff, email="maria@example.com", app_consent=True)
    _sign_in(client, _token_from(outbox[0]))
    client.post(f"/patients/{patient['id']}/app-access/revoke", headers=staff)
    events = client.get(f"/patients/{patient['id']}/audit", headers=staff)
    assert events.status_code == 200
    types = {e["event_type"] for e in events.json()["results"]}
    assert {"PATIENT_APP_INVITED", "PATIENT_APP_SIGNED_IN", "PATIENT_APP_ACCESS_REVOKED"} <= types


def test_dose_schedule_is_shown_to_staff_before_approval_and_to_the_patient_after(client, outbox):
    staff = _staff(client)
    patient = _register(client, staff, email="maria@example.com", app_consent=True)
    created = client.post(
        f"/patients/{patient['id']}/instructions", json={"text": MEDICATION_TEXT}, headers=staff
    ).json()
    analyzed = client.post(f"/instructions/{created['id']}/analyze", headers=staff).json()
    schedule = analyzed["current_version"]["dose_schedule"]
    assert schedule["kind"] == "SCHEDULED" and schedule["times_display"] == ["8:00 AM", "8:00 PM"]
    assert schedule["start_date"] is None  # starts on approval

    client.post(f"/instructions/{created['id']}/generate", headers=staff)
    client.post(f"/instructions/{created['id']}/approve", headers=staff)
    me = _sign_in(client, _token_from(outbox[0]))
    medicine = client.get("/patient-app/me/care-plan", headers=me).json()["instructions"][0]
    assert medicine["schedule"]["times"] == ["08:00", "20:00"]
    assert medicine["schedule"]["start_date"] is not None


def test_as_needed_medicine_has_no_dose_times(client, outbox):
    staff = _staff(client)
    patient = _register(client, staff, email="maria@example.com", app_consent=True)
    created = client.post(
        f"/patients/{patient['id']}/instructions",
        json={"text": "Take Paracetamol 500 mg orally every 6 hours as needed for pain."},
        headers=staff,
    ).json()
    analyzed = client.post(f"/instructions/{created['id']}/analyze", headers=staff).json()
    schedule = analyzed["current_version"]["dose_schedule"]
    assert schedule is None or schedule["kind"] in ("AS_NEEDED", "NEEDS_REVIEW")
    if schedule:
        assert schedule["times"] == []


def test_patient_can_ask_a_question_in_the_app(client, outbox):
    staff = _staff(client)
    patient = _register(client, staff, email="maria@example.com", app_consent=True)
    _approve(client, staff, patient["id"], MEDICATION_TEXT)
    me = _sign_in(client, _token_from(outbox[0]))

    resp = client.post("/patient-app/me/chat", json={"text": "When do I take my Metoprolol?"}, headers=me)
    assert resp.status_code == 200
    assert resp.json()["assistant_message"]["role"] == "ASSISTANT"
    history = client.get("/patient-app/me/chat", headers=me).json()["messages"]
    assert [m["role"] for m in history] == ["PATIENT", "ASSISTANT"]
    # Staff see the same conversation.
    assert len(client.get(f"/patients/{patient['id']}/chat", headers=staff).json()["messages"]) == 2


def test_app_chat_keeps_the_emergency_gate(client, outbox):
    staff = _staff(client)
    _register(client, staff, email="maria@example.com", app_consent=True)
    me = _sign_in(client, _token_from(outbox[0]))
    body = client.post("/patient-app/me/chat", json={"text": "I have severe chest pain"}, headers=me).json()
    assert body["patient_message"]["emergency_flagged"] is True
    assert "emergency" in body["assistant_message"]["text"].lower()


def test_app_chat_and_audio_need_the_patient_session(client):
    staff = _staff(client)
    assert client.post("/patient-app/me/chat", json={"text": "hi"}).status_code == 401
    assert client.post("/patient-app/me/chat", json={"text": "hi"}, headers=staff).status_code == 401
    assert client.post("/patient-app/me/audio", json={"text": "hi"}).status_code == 401


def test_app_audio_reads_text_aloud(client, outbox, monkeypatch):
    from app.patient_app import router as app_router

    async def fake_speech(text, language):
        assert language.value == "ENGLISH"
        return b"ID3-fake-mp3"

    monkeypatch.setattr(app_router, "synthesize_speech", fake_speech)
    staff = _staff(client)
    _register(client, staff, email="maria@example.com", app_consent=True)
    me = _sign_in(client, _token_from(outbox[0]))
    resp = client.post("/patient-app/me/audio", json={"text": "Take one tablet."}, headers=me)
    assert resp.status_code == 200 and resp.headers["content-type"] == "audio/mpeg" and resp.content == b"ID3-fake-mp3"


def test_correcting_a_mistyped_email_signs_the_stranger_out(client, outbox):
    """The invite went to the wrong address and that person signed in. Staff
    fix the address: the stranger's session and any unused link stop working."""
    staff = _staff(client)
    patient = _register(client, staff, email="wrong@example.com", app_consent=True)
    stranger = _sign_in(client, _token_from(outbox[0]))
    assert client.get("/patient-app/me", headers=stranger).status_code == 200
    client.post(f"/patients/{patient['id']}/app-access/invite", json={}, headers=staff)  # a second, unused link
    unused = _token_from(outbox[-1])

    resp = client.post(
        f"/patients/{patient['id']}/app-access/invite", json={"email": "right@example.com"}, headers=staff
    )
    assert resp.status_code in (200, 201), resp.text

    assert client.get("/patient-app/me", headers=stranger).status_code == 401
    assert client.post("/patient-app/set-password", json={"token": unused, "password": "patientpass1"}).status_code != 200
    assert outbox[-1]["to"] == "right@example.com"
    _sign_in(client, _token_from(outbox[-1]))  # the right person still gets in


# ── Passwords (2026-11-09) ────────────────────────────────────────────────────


def test_invite_link_creates_a_password_then_email_and_password_sign_in(client, outbox, db_session):
    staff = _staff(client)
    _register(client, staff, email="maria@example.com", app_consent=True)
    token = _token_from(outbox[0])
    # No time limit on the invite link (single use).
    link = db_session.query(PatientSignInLink).one()
    assert link.expires_at > datetime.now(timezone.utc) + timedelta(days=365 * 5)

    info = client.post("/patient-app/link-info", json={"token": token}).json()
    assert info == {"email": "maria@example.com", "first_time": True}
    assert client.post("/patient-app/set-password", json={"token": token, "password": "short"}).status_code == 422
    first = client.post("/patient-app/set-password", json={"token": token, "password": "patientpass1"})
    assert first.status_code == 200
    assert client.post("/patient-app/set-password", json={"token": token, "password": "patientpass1"}).status_code == 410

    ok = client.post("/patient-app/login", json={"email": " MARIA@example.com ", "password": "patientpass1"})
    assert ok.status_code == 200
    me = {"Authorization": "Bearer " + ok.json()["access_token"]}
    assert client.get("/patient-app/me", headers=me).status_code == 200
    wrong = client.post("/patient-app/login", json={"email": "maria@example.com", "password": "wrongpass99"})
    nobody = client.post("/patient-app/login", json={"email": "nobody@example.com", "password": "patientpass1"})
    assert wrong.status_code == nobody.status_code == 401
    assert wrong.json() == nobody.json()  # never says which part was wrong


def test_an_invited_login_cannot_sign_in_before_creating_a_password(client, outbox):
    staff = _staff(client)
    _register(client, staff, email="maria@example.com", app_consent=True)
    resp = client.post("/patient-app/login", json={"email": "maria@example.com", "password": ""})
    assert resp.status_code == 401


def test_forgot_password_sets_a_new_one_and_signs_out_other_devices(client, outbox):
    staff = _staff(client)
    _register(client, staff, email="maria@example.com", app_consent=True)
    old = _sign_in(client, _token_from(outbox[0]))
    client.post("/patient-app/request-link", json={"email": "maria@example.com"})
    reset = outbox[-1]
    assert "new password" in reset["text"]
    token = _token_from(reset)
    assert client.post("/patient-app/link-info", json={"token": token}).json()["first_time"] is False

    assert client.post("/patient-app/set-password", json={"token": token, "password": "brandnew123"}).status_code == 200
    assert client.get("/patient-app/me", headers=old).status_code == 401
    assert client.post("/patient-app/login", json={"email": "maria@example.com", "password": "patientpass1"}).status_code == 401
    assert client.post("/patient-app/login", json={"email": "maria@example.com", "password": "brandnew123"}).status_code == 200


def test_the_reminder_question_is_asked_once(client, outbox):
    staff = _staff(client)
    _register(client, staff, email="maria@example.com", app_consent=True)
    me = _sign_in(client, _token_from(outbox[0]))
    assert client.get("/patient-app/me", headers=me).json()["reminders_prompted"] is False
    assert client.post("/patient-app/me/reminders-prompted", headers=me).status_code == 204
    assert client.get("/patient-app/me", headers=me).json()["reminders_prompted"] is True


# ── Reminder calendar ─────────────────────────────────────────────────────────


def _feed(client, me) -> tuple[dict, str]:
    links = client.get("/patient-app/me/calendar", headers=me).json()
    path = "/" + links["feed_url"].split("/", 3)[3]
    resp = client.get(path)
    assert resp.status_code == 200 and resp.headers["content-type"].startswith("text/calendar")
    return links, resp.text


def test_calendar_has_generic_daily_reminders_once_home(client, outbox):
    staff = _staff(client)
    patient = _register(client, staff, email="maria@example.com", app_consent=True)
    _approve(client, staff, patient["id"], "Take Metoprolol 25 mg orally twice daily with food.")
    me = _sign_in(client, _token_from(outbox[0]))

    links, admitted = _feed(client, me)
    assert links["webcal_url"].startswith("webcal://") and "calendar.google.com" in links["google_url"]
    assert "BEGIN:VEVENT" not in admitted  # in hospital the nurse gives the doses

    client.patch(f"/patients/{patient['id']}", json={"admission_status": "DISCHARGED"}, headers=staff)
    _, home = _feed(client, me)
    assert home.count("BEGIN:VEVENT") == 2  # 08:00 and 20:00
    assert "RRULE:FREQ=DAILY" in home and "T080000" in home and "T200000" in home
    assert "SUMMARY:Time for your medicines" in home
    assert "Metoprolol" not in home  # no medicine names leave the hospital


def test_calendar_link_can_be_replaced_and_dies_with_access(client, outbox):
    staff = _staff(client)
    patient = _register(client, staff, email="maria@example.com", app_consent=True)
    _approve(client, staff, patient["id"], "Take Metoprolol 25 mg orally twice daily with food.")
    me = _sign_in(client, _token_from(outbox[0]))
    client.patch(f"/patients/{patient['id']}", json={"admission_status": "DISCHARGED"}, headers=staff)
    old_links, _ = _feed(client, me)
    old_path = "/" + old_links["feed_url"].split("/", 3)[3]

    new = client.post("/patient-app/me/calendar/reset", headers=me).json()
    assert new["feed_url"] != old_links["feed_url"]
    assert "BEGIN:VEVENT" not in client.get(old_path).text  # the old link now shows nothing

    client.post(f"/patients/{patient['id']}/app-access/revoke", headers=staff)
    new_path = "/" + new["feed_url"].split("/", 3)[3]
    assert "BEGIN:VEVENT" not in client.get(new_path).text  # access off: reminders disappear


def test_medicines_due_at_the_same_time_share_one_reminder(client, outbox):
    staff = _staff(client)
    patient = _register(client, staff, email="maria@example.com", app_consent=True)
    _approve(client, staff, patient["id"], "Take Metoprolol 25 mg orally twice daily with food for 7 days.")
    _approve(client, staff, patient["id"], "Take Atorvastatin 20 mg orally once daily.")
    me = _sign_in(client, _token_from(outbox[0]))
    client.patch(f"/patients/{patient['id']}", json={"admission_status": "DISCHARGED"}, headers=staff)
    _, home = _feed(client, me)
    # 08:00 both (merged, ongoing because one is), 20:00 the 7-day course only.
    assert home.count("BEGIN:VEVENT") == 2
    assert home.count("T080000") == 1 and home.count("T200000") == 1
    assert home.count("UNTIL=") == 1
