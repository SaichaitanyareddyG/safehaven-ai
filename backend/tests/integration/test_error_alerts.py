"""Unexpected errors: a plain message with a reference, and a throttled
alert to the admins that carries no patient data."""

import pytest
from fastapi import APIRouter
from fastapi.testclient import TestClient

from app.core import error_alerts
from app.core.config import get_settings
from app.main import app

boom = APIRouter()


@boom.get("/__test_boom/{patient_id}")
def _boom(patient_id: str):
    raise ValueError(f"secret value for {patient_id}")


app.include_router(boom)


@pytest.fixture()
def alerts(monkeypatch):
    sent = []
    monkeypatch.setattr(get_settings(), "resend_api_key", "re_test_only")
    monkeypatch.setattr(error_alerts, "_send", lambda *args: sent.append(args))
    monkeypatch.setattr(error_alerts, "_dispatch", lambda fn, *args: fn(*args))
    error_alerts._last_sent.clear()
    error_alerts._sent_times.clear()
    error_alerts._suppressed.clear()
    return sent


def test_unexpected_error_gives_a_reference_and_alerts_without_details(alerts):
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/__test_boom/P1234", headers={"Origin": "http://localhost:5173"})
    assert resp.status_code == 500
    body = resp.json()["detail"]
    assert "reference" in body and "secret value" not in body and "Traceback" not in body
    assert resp.headers.get("access-control-allow-origin") == "http://localhost:5173"

    (kind, route, error_type, where, reference, repeats) = alerts[0]
    assert route == "GET /__test_boom/{patient_id}"  # the pattern, never the real id
    assert error_type == "ValueError" and reference in body
    assert "secret" not in str(alerts[0]) and "P1234" not in str(alerts[0])


def test_alerts_are_throttled(alerts):
    client = TestClient(app, raise_server_exceptions=False)
    for _ in range(5):
        client.get("/__test_boom/x")
    assert len(alerts) == 1  # same error, same route: one email per 30 minutes


def test_browser_errors_are_reported_with_ids_removed(client, alerts):
    resp = client.post(
        "/client-errors",
        json={"app": "staff", "path": "/patients/1b4e28ba-2fa1-11d2-883f-0016d3cca427?x=1", "error_type": "TypeError"},
    )
    assert resp.status_code == 202 and resp.json()["reference"]
    (kind, route, error_type, *_rest) = alerts[0]
    assert kind == "staff page" and route == "/patients/{id}" and error_type == "TypeError"
