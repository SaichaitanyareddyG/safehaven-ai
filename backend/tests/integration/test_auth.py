def test_register_login_and_me(client):
    register_resp = client.post(
        "/auth/register",
        json={"email": "nurse@example.com", "password": "supersecret123", "full_name": "Test Clinician"},
    )
    assert register_resp.status_code == 201
    assert register_resp.json()["email"] == "nurse@example.com"
    assert register_resp.json()["role"] == "clinician"

    login_resp = client.post("/auth/login", json={"email": "nurse@example.com", "password": "supersecret123"})
    assert login_resp.status_code == 200
    token = login_resp.json()["access_token"]
    assert token

    me_resp = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me_resp.status_code == 200
    assert me_resp.json()["email"] == "nurse@example.com"


def test_login_with_wrong_password_is_rejected(client):
    client.post(
        "/auth/register",
        json={"email": "wrongpass@example.com", "password": "correct-password", "full_name": "Test Clinician"},
    )

    login_resp = client.post("/auth/login", json={"email": "wrongpass@example.com", "password": "incorrect"})
    assert login_resp.status_code == 401


def test_register_duplicate_email_is_rejected(client):
    payload = {"email": "dupe@example.com", "password": "supersecret123", "full_name": "Test Clinician"}
    first = client.post("/auth/register", json=payload)
    second = client.post("/auth/register", json=payload)

    assert first.status_code == 201
    assert second.status_code == 409


def test_me_requires_a_valid_token(client):
    response = client.get("/auth/me")
    assert response.status_code == 401

    response = client.get("/auth/me", headers={"Authorization": "Bearer not-a-real-token"})
    assert response.status_code == 401


def test_register_rejects_short_password(client):
    resp = client.post(
        "/auth/register",
        json={"email": "shortpw@example.com", "password": "short1", "full_name": "Test Clinician"},
    )
    assert resp.status_code == 422


def test_failed_login_is_recorded_in_audit_trail(client, db_session):
    from app.audit.models import AuditEvent, AuditEventType

    client.post(
        "/auth/register",
        json={"email": "auditme@example.com", "password": "supersecret123", "full_name": "Test Clinician"},
    )
    client.post("/auth/login", json={"email": "auditme@example.com", "password": "wrong-password"})

    events = db_session.query(AuditEvent).filter(AuditEvent.event_type == AuditEventType.LOGIN_FAILED.value).all()
    assert len(events) == 1
    assert events[0].event_metadata["email"] == "auditme@example.com"
    assert events[0].actor_id is None


def test_successful_login_does_not_record_login_failed(client, db_session):
    from app.audit.models import AuditEvent, AuditEventType

    client.post(
        "/auth/register",
        json={"email": "goodlogin@example.com", "password": "supersecret123", "full_name": "Test Clinician"},
    )
    resp = client.post("/auth/login", json={"email": "goodlogin@example.com", "password": "supersecret123"})
    assert resp.status_code == 200

    events = db_session.query(AuditEvent).filter(AuditEvent.event_type == AuditEventType.LOGIN_FAILED.value).all()
    assert events == []


def test_login_is_rate_limited_after_repeated_attempts(client):
    client.post(
        "/auth/register",
        json={"email": "ratelimited@example.com", "password": "supersecret123", "full_name": "Test Clinician"},
    )

    responses = [
        client.post("/auth/login", json={"email": "ratelimited@example.com", "password": "wrong-password"})
        for _ in range(31)
    ]

    assert responses[-1].status_code == 429


def test_register_is_rate_limited_after_repeated_attempts(client):
    responses = [
        client.post(
            "/auth/register",
            json={"email": f"spam{i}@example.com", "password": "supersecret123", "full_name": "Spam"},
        )
        for i in range(16)
    ]

    assert responses[-1].status_code == 429
