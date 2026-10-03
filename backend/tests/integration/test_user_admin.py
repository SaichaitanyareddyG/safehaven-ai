"""Admin user management, one-time passwords, deactivation and the guided tour."""

import pytest

from app.auth.models import User
from app.core.config import get_settings


def _register_and_login(client, email, password="supersecret123"):
    client.post("/auth/register", json={"email": email, "password": password, "full_name": "Test User"})
    resp = client.post("/auth/login", json={"email": email, "password": password})
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


@pytest.fixture()
def admin(client, db_session):
    headers = _register_and_login(client, "boss@example.com")
    db_session.query(User).filter(User.email == "boss@example.com").update({User.role: "admin"})
    db_session.flush()
    return headers


def _create(client, admin, email="new.nurse@example.com", role="clinician"):
    resp = client.post("/admin/users", json={"email": email, "full_name": "New Nurse", "role": role}, headers=admin)
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_clinician_cannot_use_admin_endpoints(client):
    nurse = _register_and_login(client, "plain@example.com")
    assert client.get("/admin/users", headers=nurse).status_code == 403
    assert client.post("/admin/users", json={"email": "x@example.com", "full_name": "X"}, headers=nurse).status_code == 403


def test_admin_creates_user_with_one_time_password(client, admin):
    body = _create(client, admin, email="Mixed.Case@Example.com")
    otp = body["one_time_password"]
    assert len(otp) >= 12
    assert body["user"]["email"] == "mixed.case@example.com"
    assert body["user"]["must_change_password"] is True

    listed = client.get("/admin/users", headers=admin).json()
    assert any(u["email"] == "mixed.case@example.com" for u in listed)
    assert all("one_time_password" not in u and "hashed_password" not in u for u in listed)

    # Login is case-insensitive on the email.
    login = client.post("/auth/login", json={"email": "MIXED.case@example.com", "password": otp})
    assert login.status_code == 200


def test_one_time_password_only_allows_choosing_a_new_one(client, admin):
    otp = _create(client, admin)["one_time_password"]
    token = client.post("/auth/login", json={"email": "new.nurse@example.com", "password": otp}).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    me = client.get("/auth/me", headers=headers).json()
    assert me["must_change_password"] is True
    assert me["tour_completed"] is False
    assert client.get("/patients", headers=headers).status_code == 403

    bad = client.post(
        "/auth/change-password", json={"current_password": "wrong-one-xx", "new_password": "a-brand-new-pw"}, headers=headers
    )
    assert bad.status_code == 400
    ok = client.post("/auth/change-password", json={"current_password": otp, "new_password": "a-brand-new-pw"}, headers=headers)
    assert ok.status_code == 204

    assert client.get("/auth/me", headers=headers).json()["must_change_password"] is False
    assert client.get("/patients", headers=headers).status_code == 200
    assert client.post("/auth/login", json={"email": "new.nurse@example.com", "password": otp}).status_code == 401


def test_tour_completion_is_remembered(client, admin):
    otp = _create(client, admin)["one_time_password"]
    token = client.post("/auth/login", json={"email": "new.nurse@example.com", "password": otp}).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    assert client.post("/auth/tour-complete", headers=headers).status_code == 204
    assert client.get("/auth/me", headers=headers).json()["tour_completed"] is True


def test_self_registered_accounts_skip_the_tour(client):
    headers = _register_and_login(client, "devuser@example.com")
    assert client.get("/auth/me", headers=headers).json()["tour_completed"] is True


def test_deactivation_ends_the_session_and_blocks_login(client, admin):
    created = _create(client, admin)
    otp = created["one_time_password"]
    token = client.post("/auth/login", json={"email": "new.nurse@example.com", "password": otp}).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    resp = client.patch(f"/admin/users/{created['user']['id']}", json={"is_active": False}, headers=admin)
    assert resp.status_code == 200 and resp.json()["is_active"] is False
    assert client.get("/auth/me", headers=headers).status_code == 401
    assert client.post("/auth/login", json={"email": "new.nurse@example.com", "password": otp}).status_code == 401

    client.patch(f"/admin/users/{created['user']['id']}", json={"is_active": True}, headers=admin)
    assert client.post("/auth/login", json={"email": "new.nurse@example.com", "password": otp}).status_code == 200


def test_reset_password_issues_a_new_one_time_password(client, admin):
    created = _create(client, admin)
    resp = client.post(f"/admin/users/{created['user']['id']}/reset-password", headers=admin)
    assert resp.status_code == 200
    new_otp = resp.json()["one_time_password"]
    assert new_otp != created["one_time_password"]
    assert client.post("/auth/login", json={"email": "new.nurse@example.com", "password": new_otp}).status_code == 200


def test_admin_cannot_lock_themselves_out(client, admin):
    me = client.get("/auth/me", headers=admin).json()
    assert client.patch(f"/admin/users/{me['id']}", json={"is_active": False}, headers=admin).status_code == 400
    assert client.patch(f"/admin/users/{me['id']}", json={"role": "clinician"}, headers=admin).status_code == 400


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
