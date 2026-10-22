"""Caregiver (family) logins to a patient's app: their own invite, email,
session and switch, with the patient's agreement."""

import pytest

from app.core import email as email_module
from app.core.email import EmailResult
from app.patient_app.models import DoseLog, PatientAppAccount
from app.patient_app.security import create_patient_token

MED = "Take Metoprolol 25 mg orally twice daily with food."


@pytest.fixture()
def outbox(monkeypatch):
    sent = []
    monkeypatch.setattr(
        email_module, "send_email", lambda to, subject, text, html: sent.append({"to": to, "text": text, "html": html}) or EmailResult(sent=True)
    )
    return sent


def _token(mail):
    return mail["text"].split("#token=", 1)[1].split()[0]


@pytest.fixture()
def setup(client, outbox):
    client.post("/auth/register", json={"email": "n@example.com", "password": "supersecret123", "full_name": "N"})
    staff = {"Authorization": "Bearer " + client.post("/auth/login", json={"email": "n@example.com", "password": "supersecret123"}).json()["access_token"]}
    patient = client.post(
        "/patients",
        json={"first_name": "Maria", "last_name": "Lopez", "date_of_birth": "1950-01-01", "email": "maria@example.com", "app_consent": True},
        headers=staff,
    ).json()
    created = client.post(f"/patients/{patient['id']}/instructions", json={"text": MED}, headers=staff).json()
    for step in ("analyze", "generate", "approve"):
        client.post(f"/instructions/{created['id']}/{step}", headers=staff)
    me = {"Authorization": "Bearer " + client.post("/patient-app/exchange", json={"token": _token(outbox[0])}).json()["access_token"]}
    return {"staff": staff, "patient": patient, "me": me, "instruction": created["id"]}


def _invite(client, setup, email="priya@example.com", **extra):
    payload = {"email": email, "name": "Priya", "relationship": "daughter", "consent": True, **extra}
    return client.post(f"/patients/{setup['patient']['id']}/app-access/caregivers", json=payload, headers=setup["staff"])


def _sign_in(client, mail):
    resp = client.post("/patient-app/exchange", json={"token": _token(mail)})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def test_caregiver_gets_their_own_invite_and_sees_the_care_plan(client, setup, outbox):
    resp = _invite(client, setup)
    assert resp.status_code == 200 and resp.json()["emailed"] is True
    mail = outbox[-1]
    assert mail["to"] == "priya@example.com"
    for part in ("text", "html"):  # no patient name, no medical details
        assert "Maria" not in mail[part] and "Lopez" not in mail[part] and "Metoprolol" not in mail[part]

    caregiver = _sign_in(client, mail)
    me = client.get("/patient-app/me", headers=caregiver).json()
    assert me["viewer_role"] == "CAREGIVER" and me["viewer_name"] == "Priya" and me["first_name"] == "Maria"
    plan = client.get("/patient-app/me/care-plan", headers=caregiver).json()
    assert "Metoprolol" in plan["instructions"][0]["text_by_language"]["ENGLISH"]

    access = client.get(f"/patients/{setup['patient']['id']}/app-access", headers=setup["staff"]).json()
    assert [(c["display_name"], c["relationship"], c["status"]) for c in access["caregivers"]] == [("Priya", "daughter", "ACTIVE")]
    assert access["status"] == "ACTIVE"  # the patient's own login, unchanged


def test_each_login_has_its_own_switch(client, setup, outbox):
    caregiver_id = _invite(client, setup).json()["caregiver"]["id"]
    caregiver = _sign_in(client, outbox[-1])

    client.post(f"/patients/{setup['patient']['id']}/app-access/caregivers/{caregiver_id}/revoke", headers=setup["staff"])
    assert client.get("/patient-app/me", headers=caregiver).status_code == 401
    assert client.get("/patient-app/me", headers=setup["me"]).status_code == 200

    # And the other way round.
    _invite(client, setup)
    caregiver = _sign_in(client, outbox[-1])
    client.post(f"/patients/{setup['patient']['id']}/app-access/revoke", headers=setup["staff"])
    assert client.get("/patient-app/me", headers=setup["me"]).status_code == 401
    assert client.get("/patient-app/me", headers=caregiver).status_code == 200


def test_caregiver_needs_consent_name_and_a_free_email(client, setup):
    assert _invite(client, setup, consent=False).status_code == 409
    assert _invite(client, setup, name=" ").status_code in (409, 422)
    assert _invite(client, setup, email="maria@example.com").status_code == 409  # the patient's own
    other = client.post(
        "/patients",
        json={"first_name": "O", "last_name": "P", "date_of_birth": "1950-01-01", "email": "busy@example.com", "app_consent": True},
        headers=setup["staff"],
    )
    assert other.status_code == 201
    assert _invite(client, setup, email="Busy@example.com").status_code == 409  # another login


def test_caregiver_signs_in_by_requesting_a_link(client, setup, outbox):
    _invite(client, setup)
    _sign_in(client, outbox[-1])
    outbox.clear()
    client.post("/patient-app/request-link", json={"email": "PRIYA@example.com"})
    caregiver = _sign_in(client, outbox[-1])
    assert client.get("/patient-app/me", headers=caregiver).json()["viewer_role"] == "CAREGIVER"


def test_dose_answer_records_who_gave_it(client, setup, outbox, db_session):
    _invite(client, setup)
    caregiver = _sign_in(client, outbox[-1])
    today = client.get("/patient-app/me/doses", headers=caregiver).json()["date"]
    resp = client.post(
        "/patient-app/me/doses",
        json={"instruction_id": setup["instruction"], "date": today, "time": "08:00", "status": "TAKEN"},
        headers=caregiver,
    )
    assert resp.status_code == 204
    log = db_session.query(DoseLog).one()
    recorder = db_session.get(PatientAppAccount, log.recorded_by_account_id)
    assert recorder.role == "CAREGIVER"


def test_discharge_window_applies_to_caregivers_too(client, setup, outbox, db_session):
    _invite(client, setup)
    client.patch(f"/patients/{setup['patient']['id']}", json={"admission_status": "DISCHARGED"}, headers=setup["staff"])
    accounts = db_session.query(PatientAppAccount).all()
    assert len(accounts) == 2 and all(a.access_expires_at is not None for a in accounts)


def test_sessions_from_before_caregivers_still_work(client, setup, db_session):
    own = db_session.query(PatientAppAccount).filter_by(role="PATIENT").one()
    import jwt

    from app.core.config import get_settings

    token, _ = create_patient_token(own.patient_id, own.id, own.session_version)
    payload = jwt.decode(token, get_settings().jwt_secret_key, algorithms=["HS256"])
    del payload["acc"]  # an old token had no login id
    old = jwt.encode(payload, get_settings().jwt_secret_key, algorithm="HS256")
    assert client.get("/patient-app/me", headers={"Authorization": f"Bearer {old}"}).status_code == 200


def test_changing_the_patient_email_moves_their_login(client, setup, outbox):
    client.patch(f"/patients/{setup['patient']['id']}", json={"email": "maria.new@example.com"}, headers=setup["staff"])
    outbox.clear()
    client.post("/patient-app/request-link", json={"email": "maria.new@example.com"})
    assert [m["to"] for m in outbox] == ["maria.new@example.com"]
    client.post("/patient-app/request-link", json={"email": "maria@example.com"})
    assert len(outbox) == 1  # the old address no longer gets links


def test_caregiver_events_are_audited(client, setup, outbox):
    caregiver_id = _invite(client, setup).json()["caregiver"]["id"]
    client.post(f"/patients/{setup['patient']['id']}/app-access/caregivers/{caregiver_id}/revoke", headers=setup["staff"])
    types = {e["event_type"] for e in client.get(f"/patients/{setup['patient']['id']}/audit", headers=setup["staff"]).json()["results"]}
    assert {"CAREGIVER_INVITED", "CAREGIVER_ACCESS_REVOKED"} <= types
