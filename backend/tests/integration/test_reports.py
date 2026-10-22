"""Patient reports: real PDF/PNG/JPEG only, hidden from the patient until
shared, every opening audited, removal deletes the document."""

import pytest

from app.core import email as email_module
from app.core.email import EmailResult
from app.reports.models import PatientReport

PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


@pytest.fixture()
def setup(client, monkeypatch):
    sent = []
    monkeypatch.setattr(email_module, "send_email", lambda to, s, text, html: sent.append(text) or EmailResult(sent=True))
    client.post("/auth/register", json={"email": "n@example.com", "password": "supersecret123", "full_name": "N"})
    staff = {"Authorization": "Bearer " + client.post("/auth/login", json={"email": "n@example.com", "password": "supersecret123"}).json()["access_token"]}
    patient = client.post(
        "/patients",
        json={"first_name": "Maria", "last_name": "L", "date_of_birth": "1950-01-01", "email": "m@example.com", "app_consent": True},
        headers=staff,
    ).json()
    token = sent[0].split("#token=", 1)[1].split()[0]
    me = {"Authorization": "Bearer " + client.post("/patient-app/exchange", json={"token": token}).json()["access_token"]}
    return {"staff": staff, "patient": patient, "me": me}


def _upload(client, setup, data=PDF, name="blood.pdf", mime="application/pdf", **form):
    fields = {"title": "Blood test", "category": "LAB", "report_date": "2026-10-20", **form}
    return client.post(
        f"/patients/{setup['patient']['id']}/reports",
        files={"file": (name, data, mime)},
        data=fields,
        headers=setup["staff"],
    )


def test_upload_and_open_as_staff(client, setup):
    resp = _upload(client, setup)
    assert resp.status_code == 201, resp.text
    report = resp.json()
    assert report["content_type"] == "application/pdf" and report["shared_with_patient"] is False
    opened = client.get(f"/reports/{report['id']}/file", headers=setup["staff"])
    assert opened.status_code == 200 and opened.content == PDF
    assert opened.headers["content-type"] == "application/pdf"
    assert opened.headers["x-content-type-options"] == "nosniff" and "no-store" in opened.headers["cache-control"]


def test_only_real_pdf_png_jpeg_whatever_the_name(client, setup):
    html = b"<html><script>alert(1)</script></html>"
    assert _upload(client, setup, data=html, name="report.pdf", mime="application/pdf").status_code == 422
    assert _upload(client, setup, data=b"", name="empty.pdf").status_code == 422
    png = _upload(client, setup, data=PNG, name="scan.pdf", mime="application/pdf")
    assert png.status_code == 201 and png.json()["content_type"] == "image/png"  # decided by the bytes


def test_too_big_is_refused(client, setup):
    big = PDF + b"0" * (10 * 1024 * 1024)
    resp = _upload(client, setup, data=big)
    assert resp.status_code == 422 and "10 MB" in resp.json()["detail"]


def test_patient_sees_only_shared_reports(client, setup):
    hidden = _upload(client, setup, title="Draft scan").json()
    shared = _upload(client, setup, title="Blood test", shared_with_patient="true").json()
    mine = client.get("/patient-app/me/reports", headers=setup["me"]).json()["results"]
    assert [r["title"] for r in mine] == ["Blood test"]
    assert client.get(f"/patient-app/me/reports/{shared['id']}/file", headers=setup["me"]).content == PDF
    assert client.get(f"/patient-app/me/reports/{hidden['id']}/file", headers=setup["me"]).status_code == 404

    client.patch(f"/reports/{hidden['id']}", json={"shared_with_patient": True}, headers=setup["staff"])
    assert len(client.get("/patient-app/me/reports", headers=setup["me"]).json()["results"]) == 2


def test_another_patients_report_is_unreachable(client, setup):
    other = client.post(
        "/patients", json={"first_name": "O", "last_name": "P", "date_of_birth": "1950-01-01"}, headers=setup["staff"]
    ).json()
    theirs = client.post(
        f"/patients/{other['id']}/reports",
        files={"file": ("x.pdf", PDF, "application/pdf")},
        data={"title": "Theirs", "shared_with_patient": "true"},
        headers=setup["staff"],
    ).json()
    assert client.get(f"/patient-app/me/reports/{theirs['id']}/file", headers=setup["me"]).status_code == 404


def test_every_opening_is_audited(client, setup):
    report = _upload(client, setup, shared_with_patient="true").json()
    client.get(f"/reports/{report['id']}/file", headers=setup["staff"])
    client.get(f"/patient-app/me/reports/{report['id']}/file", headers=setup["me"])
    events = client.get(f"/patients/{setup['patient']['id']}/audit", headers=setup["staff"]).json()["results"]
    views = [e for e in events if e["event_type"] == "REPORT_VIEWED"]
    assert sorted(e["actor_type"] for e in views) == ["CLINICIAN", "PATIENT"]
    assert "REPORT_UPLOADED" in {e["event_type"] for e in events}


def test_remove_deletes_the_document_but_keeps_the_record(client, setup, db_session):
    report = _upload(client, setup, shared_with_patient="true").json()
    assert client.delete(f"/reports/{report['id']}", headers=setup["staff"]).status_code == 204
    assert client.get(f"/reports/{report['id']}/file", headers=setup["staff"]).status_code == 404
    assert client.get("/patient-app/me/reports", headers=setup["me"]).json()["results"] == []
    row = db_session.get(PatientReport, report["id"])
    db_session.refresh(row)
    assert row.removed_at is not None and row.data == b""


def test_reports_are_staff_or_owner_only(client, setup):
    pid = setup["patient"]["id"]
    assert client.get(f"/patients/{pid}/reports").status_code == 401
    assert client.get(f"/patients/{pid}/reports", headers=setup["me"]).status_code == 401
    resp = client.post(
        f"/patients/{pid}/reports", files={"file": ("x.pdf", PDF, "application/pdf")}, data={"title": "x"}, headers=setup["me"]
    )
    assert resp.status_code == 401
