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
