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
    resp = client.post("/patient-app/exchange", json={"token": token})
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
    assert client.post("/patient-app/exchange", json={"token": token}).status_code == 410

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
    assert client.post("/patient-app/exchange", json={"token": _token_from(outbox[0])}).status_code == 410


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


def test_discharge_keeps_the_app_for_a_window_then_it_stops(client, outbox, db_session):
    staff = _staff(client)
    patient = _register(client, staff, email="maria@example.com", app_consent=True)
    me = _sign_in(client, _token_from(outbox[0]))

    client.patch(f"/patients/{patient['id']}", json={"admission_status": "DISCHARGED"}, headers=staff)
    profile = client.get("/patient-app/me", headers=me).json()
    assert profile["admission_status"] == "DISCHARGED" and profile["access_expires_at"] is not None

    db_session.query(PatientAppAccount).update(
        {PatientAppAccount.access_expires_at: datetime.now(timezone.utc) - timedelta(seconds=1)}
    )
    db_session.flush()
    assert client.get("/patient-app/me", headers=me).status_code == 401
    assert client.get(f"/patients/{patient['id']}/app-access", headers=staff).json()["status"] == "EXPIRED"


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
