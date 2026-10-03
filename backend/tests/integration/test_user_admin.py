"""Admin user management, invite and reset links, deactivation and the guided tour."""

import re

import pytest

from app.auth.models import User
from app.core import email as email_module
from app.core.config import get_settings
from app.core.email import EmailResult


def _register_and_login(client, email, password="supersecret123"):
    client.post("/auth/register", json={"email": email, "password": password, "full_name": "Test User"})
    resp = client.post("/auth/login", json={"email": email, "password": password})
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


@pytest.fixture()
def outbox(monkeypatch):
    """Captures account emails instead of sending them."""
    sent = []

    def fake_send(to, subject, text, html):
        sent.append({"to": to, "subject": subject, "text": text, "html": html})
        return EmailResult(sent=True)

    monkeypatch.setattr(email_module, "send_email", fake_send)
    return sent


@pytest.fixture()
def admin(client, db_session):
    headers = _register_and_login(client, "boss@example.com")
    db_session.query(User).filter(User.email == "boss@example.com").update({User.role: "admin"})
    db_session.flush()
    return headers


def _token(link: str) -> str:
    assert "/set-password#token=" in link
    return link.split("#token=", 1)[1]


def _create(client, admin, email="new.nurse@example.com", role="clinician"):
    resp = client.post("/admin/users", json={"email": email, "full_name": "New Nurse", "role": role}, headers=admin)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _accept(client, link, password="a-brand-new-pw"):
    resp = client.post("/auth/set-password", json={"token": _token(link), "new_password": password})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def test_clinician_cannot_use_admin_endpoints(client):
    nurse = _register_and_login(client, "plain@example.com")
    assert client.get("/admin/users", headers=nurse).status_code == 403
    assert client.post("/admin/users", json={"email": "x@example.com", "full_name": "X"}, headers=nurse).status_code == 403


def test_invite_is_emailed_with_a_single_use_link(client, admin, outbox):
    body = _create(client, admin, email="Mixed.Case@Example.com")
    assert body["emailed"] is True
    assert body["user"]["email"] == "mixed.case@example.com"
    assert body["user"]["must_change_password"] is True
    assert len(outbox) == 1 and outbox[0]["to"] == "mixed.case@example.com"
    assert body["link"] in outbox[0]["text"]

    info = client.get(f"/auth/password-link/{_token(body['link'])}").json()
    assert info == {"purpose": "invite", "email": "mixed.case@example.com", "full_name": "New Nurse"}

    headers = _accept(client, body["link"])
    me = client.get("/auth/me", headers=headers).json()
    assert me["must_change_password"] is False and me["tour_completed"] is False
    assert client.get("/patients", headers=headers).status_code == 200

    # Spent: a second use fails, and login works with the chosen password (any email case).
    again = client.post("/auth/set-password", json={"token": _token(body["link"]), "new_password": "another-password"})
    assert again.status_code == 410
    assert client.post("/auth/login", json={"email": "MIXED.case@example.com", "password": "a-brand-new-pw"}).status_code == 200


def test_invited_user_cannot_sign_in_before_choosing_a_password(client, admin):
    _create(client, admin)
    user_list = client.get("/admin/users", headers=admin).json()
    assert all("hashed_password" not in u for u in user_list)
    # No password was ever handed out, so there is nothing to try.
    assert client.post("/auth/login", json={"email": "new.nurse@example.com", "password": ""}).status_code in (401, 422)


def test_without_email_set_up_the_admin_still_gets_the_link(client, admin):
    body = _create(client, admin)
    assert body["emailed"] is False
    assert body["email_problem"]
    _accept(client, body["link"])


def test_only_the_link_hash_is_stored(client, admin, db_session):
    from app.auth.password_links import PasswordLink

    token = _token(_create(client, admin)["link"])
    stored = [r.token_hash for r in db_session.query(PasswordLink).all()]
    assert token not in stored and all(len(h) == 64 for h in stored)


def test_expired_link_is_refused(client, admin, db_session):
    from datetime import datetime, timedelta, timezone

    from app.auth.password_links import PasswordLink

    link = _create(client, admin)["link"]
    db_session.query(PasswordLink).update({PasswordLink.expires_at: datetime.now(timezone.utc) - timedelta(minutes=1)})
    db_session.flush()
    assert client.get(f"/auth/password-link/{_token(link)}").status_code == 410
    assert client.post("/auth/set-password", json={"token": _token(link), "new_password": "a-brand-new-pw"}).status_code == 410


def test_resending_cancels_the_older_link(client, admin, outbox):
    created = _create(client, admin)
    resent = client.post(f"/admin/users/{created['user']['id']}/send-link", headers=admin).json()
    assert "invited" in outbox[-1]["subject"].lower()
    assert client.get(f"/auth/password-link/{_token(created['link'])}").status_code == 410
    _accept(client, resent["link"])


def test_admin_reset_link_keeps_the_old_password_until_used(client, admin, outbox):
    created = _create(client, admin)
    _accept(client, created["link"], password="first-password-1")
    reset = client.post(f"/admin/users/{created['user']['id']}/send-link", headers=admin).json()
    assert "reset" in outbox[-1]["subject"].lower()
    assert client.post("/auth/login", json={"email": "new.nurse@example.com", "password": "first-password-1"}).status_code == 200
    _accept(client, reset["link"], password="second-password-2")
    assert client.post("/auth/login", json={"email": "new.nurse@example.com", "password": "first-password-1"}).status_code == 401


def test_forgot_password_never_reveals_whether_an_account_exists(client, outbox):
    _register_and_login(client, "forgetful@example.com")
    known = client.post("/auth/forgot-password", json={"email": "Forgetful@example.com"})
    unknown = client.post("/auth/forgot-password", json={"email": "nobody@example.com"})
    assert known.status_code == unknown.status_code == 202
    assert known.json() == unknown.json()
    assert [m["to"] for m in outbox] == ["forgetful@example.com"]
    link = re.search(r"\S+/set-password#token=\S+", outbox[0]["text"]).group(0)
    assert link in outbox[0]["html"]
    assert client.get(f"/auth/password-link/{_token(link)}").json()["purpose"] == "reset"


def test_deactivated_user_gets_no_reset_and_link_stops_working(client, admin, outbox):
    created = _create(client, admin)
    client.patch(f"/admin/users/{created['user']['id']}", json={"is_active": False}, headers=admin)
    assert client.get(f"/auth/password-link/{_token(created['link'])}").status_code == 410
    outbox.clear()
    client.post("/auth/forgot-password", json={"email": "new.nurse@example.com"})
    assert outbox == []


def test_one_time_password_from_create_admin_only_allows_choosing_a_new_one(client, db_session):
    from app.auth.security import hash_password

    db_session.add(
        User(email="cli.admin@example.com", full_name="Cli Admin", role="admin",
             hashed_password=hash_password("one-time-pass"), must_change_password=True)
    )
    db_session.flush()
    token = client.post("/auth/login", json={"email": "cli.admin@example.com", "password": "one-time-pass"}).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    assert client.get("/patients", headers=headers).status_code == 403
    ok = client.post("/auth/change-password", json={"current_password": "one-time-pass", "new_password": "a-brand-new-pw"}, headers=headers)
    assert ok.status_code == 204
    assert client.get("/patients", headers=headers).status_code == 200


def test_tour_completion_is_remembered(client, admin):
    headers = _accept(client, _create(client, admin)["link"])
    assert client.post("/auth/tour-complete", headers=headers).status_code == 204
    assert client.get("/auth/me", headers=headers).json()["tour_completed"] is True


def test_self_registered_accounts_skip_the_tour(client):
    headers = _register_and_login(client, "devuser@example.com")
    assert client.get("/auth/me", headers=headers).json()["tour_completed"] is True


def test_deactivation_ends_the_session_and_blocks_login(client, admin):
    created = _create(client, admin)
    headers = _accept(client, created["link"])
    client.patch(f"/admin/users/{created['user']['id']}", json={"is_active": False}, headers=admin)
    assert client.get("/auth/me", headers=headers).status_code == 401
    assert client.post("/auth/login", json={"email": "new.nurse@example.com", "password": "a-brand-new-pw"}).status_code == 401
    client.patch(f"/admin/users/{created['user']['id']}", json={"is_active": True}, headers=admin)
    assert client.post("/auth/login", json={"email": "new.nurse@example.com", "password": "a-brand-new-pw"}).status_code == 200


def test_admin_cannot_lock_themselves_out(client, admin):
    me = client.get("/auth/me", headers=admin).json()
    assert client.patch(f"/admin/users/{me['id']}", json={"is_active": False}, headers=admin).status_code == 400
    assert client.patch(f"/admin/users/{me['id']}", json={"role": "clinician"}, headers=admin).status_code == 400
    assert client.post(f"/admin/users/{me['id']}/send-link", headers=admin).status_code == 400


def test_duplicate_email_is_rejected(client, admin):
    _create(client, admin)
    resp = client.post("/admin/users", json={"email": "NEW.nurse@example.com", "full_name": "Again"}, headers=admin)
    assert resp.status_code == 409


def test_admin_can_promote_a_clinician(client, admin):
    created = _create(client, admin)
    resp = client.patch(f"/admin/users/{created['user']['id']}", json={"role": "admin"}, headers=admin)
    assert resp.json()["role"] == "admin"


def test_registration_can_be_switched_off(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "allow_self_registration", False)
    resp = client.post("/auth/register", json={"email": "closed@example.com", "password": "supersecret123", "full_name": "X"})
    assert resp.status_code == 404


def test_email_without_a_key_reports_a_problem_instead_of_raising(monkeypatch):
    monkeypatch.setattr(get_settings(), "resend_api_key", "")
    result = email_module.send_email("a@example.com", "s", "t", "<p>h</p>")
    assert result.sent is False and result.problem
