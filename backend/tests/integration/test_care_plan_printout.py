"""The printable care plan: approved content only, upcoming appointments,
staff only, and every printout recorded."""

from datetime import datetime, timedelta, timezone

MED = "Take Metoprolol 25 mg orally twice daily with food."


def _staff(client):
    client.post("/auth/register", json={"email": "n@example.com", "password": "supersecret123", "full_name": "N"})
    return {"Authorization": "Bearer " + client.post("/auth/login", json={"email": "n@example.com", "password": "supersecret123"}).json()["access_token"]}


def test_printout_has_the_approved_plan_and_upcoming_appointments(client):
    staff = _staff(client)
    patient = client.post(
        "/patients", json={"first_name": "Maria", "last_name": "Lopez", "date_of_birth": "1950-01-01"}, headers=staff
    ).json()
    approved = client.post(f"/patients/{patient['id']}/instructions", json={"text": MED}, headers=staff).json()
    for step in ("analyze", "generate", "approve"):
        client.post(f"/instructions/{approved['id']}/{step}", headers=staff)
    # A draft that was never approved must not be printed.
    client.post(f"/patients/{patient['id']}/instructions", json={"text": "Take Aspirin 81 mg daily."}, headers=staff)
    client.post(
        f"/patients/{patient['id']}/appointments",
        json={"title": "Cardiology check-up", "starts_at": (datetime.now(timezone.utc) + timedelta(days=5)).isoformat()},
        headers=staff,
    )

    body = client.get(f"/patients/{patient['id']}/care-plan-printout", headers=staff).json()
    assert body["patient_last_name"] == "Lopez" and body["patient_code"].startswith("P")
    texts = [i["text_by_language"]["ENGLISH"] for i in body["care_plan"]["instructions"]]
    assert len(texts) == 1 and "Metoprolol" in texts[0]
    assert body["care_plan"]["instructions"][0]["schedule"]["times"] == ["08:00", "20:00"]
    assert [a["title"] for a in body["appointments"]] == ["Cardiology check-up"]

    events = client.get(f"/patients/{patient['id']}/audit", headers=staff).json()["results"]
    assert "CARE_PLAN_PRINTED" in {e["event_type"] for e in events}


def test_printout_is_staff_only(client):
    staff = _staff(client)
    patient = client.post(
        "/patients", json={"first_name": "A", "last_name": "B", "date_of_birth": "1950-01-01"}, headers=staff
    ).json()
    assert client.get(f"/patients/{patient['id']}/care-plan-printout").status_code == 401
