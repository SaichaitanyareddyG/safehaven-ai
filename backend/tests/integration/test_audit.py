import uuid
from datetime import datetime, timedelta, timezone

from app.audit.models import ActorType, AuditEvent
from app.patient_access.models import PatientCareAccessToken

MEDICATION_TEXT = "Take Metoprolol 25 mg orally twice daily with food."
MOBILITY_TEXT = "Walk for 10 minutes after meals with nurse assistance."


def _register_and_login(client, email="clinician@example.com", password="supersecret123"):
    client.post("/auth/register", json={"email": email, "password": password, "full_name": "Test Clinician"})
    login_resp = client.post("/auth/login", json={"email": email, "password": password})
    token = login_resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _current_user_id(client, headers) -> str:
    return client.get("/auth/me", headers=headers).json()["id"]


def _create_active_patient(client, headers, **overrides) -> dict:
    payload = {
        "first_name": "John",
        "last_name": "Doe",
        "date_of_birth": "1950-01-01",
        "preferred_language": "ENGLISH",
    }
    payload.update(overrides)
    return client.post("/patients", json=payload, headers=headers).json()


def _with_fixture(text: str, fixture: str) -> str:
    return f"{text} __FIXTURE__:{fixture}"


def _audit_events(client, headers, patient_id, **params) -> dict:
    resp = client.get(f"/patients/{patient_id}/audit", headers=headers, params=params)
    assert resp.status_code == 200
    return resp.json()


def _event_types(events: list[dict]) -> list[str]:
    return [e["event_type"] for e in events]


# ---------------------------------------------------------------------------
# Per-operation event coverage
# ---------------------------------------------------------------------------


def test_login_emits_user_login_event(client, db_session):
    headers = _register_and_login(client)
    user_id = uuid.UUID(_current_user_id(client, headers))

    event = db_session.query(AuditEvent).filter(AuditEvent.event_type == "USER_LOGIN").one()
    assert event.actor_type == ActorType.CLINICIAN
    assert event.actor_id == user_id
    assert event.patient_id is None


def test_patient_created_emits_event(client):
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)

    events = _audit_events(client, headers, patient["id"])
    assert events["total"] == 1
    assert events["results"][0]["event_type"] == "PATIENT_CREATED"
    assert events["results"][0]["actor_type"] == "CLINICIAN"
    assert events["results"][0]["patient_id"] == patient["id"]


def test_patient_updated_emits_event_with_field_names_only(client):
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)

    client.patch(f"/patients/{patient['id']}", json={"room_number": "412B"}, headers=headers)

    events = _audit_events(client, headers, patient["id"])
    updated = [e for e in events["results"] if e["event_type"] == "PATIENT_UPDATED"]
    assert len(updated) == 1
    assert updated[0]["event_metadata"]["fields_updated"] == ["room_number"]
    # Never the raw new value — just that the field changed.
    assert "412B" not in str(updated[0]["event_metadata"])


def test_instruction_lifecycle_emits_expected_event_sequence(client):
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)

    created = client.post(
        f"/patients/{patient['id']}/instructions", json={"text": MEDICATION_TEXT}, headers=headers
    ).json()
    client.post(f"/instructions/{created['id']}/analyze", headers=headers)
    generated = client.post(f"/instructions/{created['id']}/generate", headers=headers).json()
    assert generated["status"] == "READY_FOR_APPROVAL"
    client.post(f"/instructions/{created['id']}/approve", headers=headers)

    events = _audit_events(client, headers, patient["id"])["results"]
    types = _event_types(events)

    assert "INSTRUCTION_CREATED" in types
    assert "INSTRUCTION_ANALYSIS_STARTED" in types
    assert "INSTRUCTION_ANALYSIS_PASSED" in types
    assert "PATIENT_OUTPUT_GENERATED" in types
    assert "FACT_VALIDATION_PASSED" in types
    assert "INSTRUCTION_APPROVED" in types

    # Chronological order (ascending), matching the clinical sequence above.
    assert types.index("INSTRUCTION_CREATED") < types.index("INSTRUCTION_ANALYSIS_STARTED")
    assert types.index("INSTRUCTION_ANALYSIS_STARTED") < types.index("INSTRUCTION_ANALYSIS_PASSED")
    assert types.index("PATIENT_OUTPUT_GENERATED") < types.index("FACT_VALIDATION_PASSED")
    assert types.index("FACT_VALIDATION_PASSED") < types.index("INSTRUCTION_APPROVED")


def test_needs_review_emits_event_with_reason_metadata(client):
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)

    created = client.post(
        f"/patients/{patient['id']}/instructions", json={"text": "Walk after meals."}, headers=headers
    ).json()
    client.post(f"/instructions/{created['id']}/analyze", headers=headers)

    events = _audit_events(client, headers, patient["id"])["results"]
    needs_review = [e for e in events if e["event_type"] == "INSTRUCTION_NEEDS_REVIEW"]
    assert len(needs_review) == 1
    assert needs_review[0]["event_metadata"]["reason"] == "CLARIFICATION_REQUIRED"


def test_clarification_emits_event(client):
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)
    created = client.post(
        f"/patients/{patient['id']}/instructions", json={"text": "Walk after meals."}, headers=headers
    ).json()
    client.post(f"/instructions/{created['id']}/analyze", headers=headers)

    client.post(
        f"/instructions/{created['id']}/clarify",
        json={"text": "Walk for 10 minutes after meals with nurse assistance required at all times."},
        headers=headers,
    )

    events = _audit_events(client, headers, patient["id"])["results"]
    assert "CLARIFICATION_CREATED" in _event_types(events)


def test_fact_validation_failed_emits_event(client):
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)
    created = client.post(
        f"/patients/{patient['id']}/instructions",
        json={"text": _with_fixture(MEDICATION_TEXT, "GENERATION_CHANGED_DOSE")},
        headers=headers,
    ).json()
    client.post(f"/instructions/{created['id']}/analyze", headers=headers)
    generated = client.post(f"/instructions/{created['id']}/generate", headers=headers).json()
    assert generated["status"] == "NEEDS_REVIEW"

    events = _audit_events(client, headers, patient["id"])["results"]
    failed = [e for e in events if e["event_type"] == "FACT_VALIDATION_FAILED"]
    assert len(failed) == 1
    assert failed[0]["event_metadata"]["reason"] == "FACT_PRESERVATION_FAILED"
    assert failed[0]["event_metadata"]["difference_count"] >= 1


def test_reject_emits_event_with_reason_but_no_raw_clinical_text(client):
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)
    created = client.post(
        f"/patients/{patient['id']}/instructions", json={"text": MEDICATION_TEXT}, headers=headers
    ).json()
    client.post(f"/instructions/{created['id']}/analyze", headers=headers)
    client.post(f"/instructions/{created['id']}/generate", headers=headers)

    client.post(
        f"/instructions/{created['id']}/reject", json={"reason": "Clinically inappropriate for this patient"}, headers=headers
    )

    events = _audit_events(client, headers, patient["id"])["results"]
    rejected = [e for e in events if e["event_type"] == "INSTRUCTION_REJECTED"]
    assert len(rejected) == 1
    assert rejected[0]["event_metadata"]["reason"] == "Clinically inappropriate for this patient"
    assert MEDICATION_TEXT not in str(rejected[0]["event_metadata"])


def test_translation_events_emitted_on_pass_and_fail(client):
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers, preferred_language="TELUGU")
    created = client.post(
        f"/patients/{patient['id']}/instructions",
        json={"text": _with_fixture(MEDICATION_TEXT, "TRANSLATION_TELUGU_CHANGED_DOSE")},
        headers=headers,
    ).json()
    client.post(f"/instructions/{created['id']}/analyze", headers=headers)
    client.post(f"/instructions/{created['id']}/generate", headers=headers)
    client.post(f"/instructions/{created['id']}/approve", headers=headers)

    client.post(
        f"/instructions/{created['id']}/translations", json={"languages": ["TELUGU", "HINDI"]}, headers=headers
    )

    events = _audit_events(client, headers, patient["id"])["results"]
    types = _event_types(events)
    assert types.count("TRANSLATION_CREATED") == 2
    assert "TRANSLATION_VALIDATION_PASSED" in types  # Hindi
    assert "TRANSLATION_VALIDATION_FAILED" in types  # Telugu (corrupted dose)


# ---------------------------------------------------------------------------
# Token security
# ---------------------------------------------------------------------------


def test_token_created_emits_event_without_raw_token_in_metadata(client, db_session):
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)

    resp = client.post(f"/patients/{patient['id']}/care-access-tokens", headers=headers)
    raw_token = resp.json()["token"]

    event = db_session.query(AuditEvent).filter(AuditEvent.event_type == "CARE_ACCESS_TOKEN_CREATED").one()
    assert raw_token not in str(event.event_metadata)


def test_token_revoke_emits_event_and_is_idempotent(client):
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)
    resp = client.post(f"/patients/{patient['id']}/care-access-tokens", headers=headers)

    tokens = client.get(f"/patients/{patient['id']}/care-access-tokens", headers=headers).json()
    token_id = tokens["results"][0]["id"]

    first = client.post(f"/care-access-tokens/{token_id}/revoke", headers=headers)
    assert first.status_code == 200
    assert first.json()["status"] == "REVOKED"

    second = client.post(f"/care-access-tokens/{token_id}/revoke", headers=headers)
    assert second.status_code == 200  # idempotent, not an error

    events = _audit_events(client, headers, patient["id"])["results"]
    revoked = [e for e in events if e["event_type"] == "CARE_ACCESS_TOKEN_REVOKED"]
    assert len(revoked) == 1  # not duplicated by the second, no-op revoke call


def test_revoked_token_immediately_denies_care_plan_access(client):
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)
    resp = client.post(f"/patients/{patient['id']}/care-access-tokens", headers=headers)
    raw_token = resp.json()["token"]
    token_id = client.get(f"/patients/{patient['id']}/care-access-tokens", headers=headers).json()["results"][0]["id"]

    client.post(f"/care-access-tokens/{token_id}/revoke", headers=headers)

    denied = client.get("/care-plan", params={"token": raw_token})
    assert denied.status_code == 401


def test_discharge_auto_revokes_active_tokens_and_link_stops_working(client):
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)
    resp = client.post(f"/patients/{patient['id']}/care-access-tokens", headers=headers)
    raw_token = resp.json()["token"]

    client.patch(f"/patients/{patient['id']}", json={"admission_status": "DISCHARGED"}, headers=headers)

    denied = client.get("/care-plan", params={"token": raw_token})
    assert denied.status_code == 401

    events = _audit_events(client, headers, patient["id"])["results"]
    types = _event_types(events)
    assert "PATIENT_DISCHARGED" in types
    revoked = [e for e in events if e["event_type"] == "CARE_ACCESS_TOKEN_REVOKED"]
    assert len(revoked) == 1
    assert revoked[0]["actor_type"] == "SYSTEM"
    assert revoked[0]["event_metadata"]["reason"] == "patient_discharged"


def test_clinician_can_request_shorter_token_expiry_capped_at_default(client, db_session):
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)

    resp = client.post(
        f"/patients/{patient['id']}/care-access-tokens", json={"expires_in_hours": 999}, headers=headers
    )
    record = db_session.query(PatientCareAccessToken).filter(
        PatientCareAccessToken.patient_id == uuid.UUID(patient["id"])
    ).one()
    # Capped at the configured default (24h) — cannot request a longer-lived link.
    assert record.expires_at <= datetime.now(timezone.utc) + timedelta(hours=24, minutes=1)

    resp_short = client.post(
        f"/patients/{patient['id']}/care-access-tokens", json={"expires_in_hours": 1}, headers=headers
    )
    assert resp_short.status_code == 201


# ---------------------------------------------------------------------------
# CARE_PLAN_VIEWED + deduplication
# ---------------------------------------------------------------------------


def test_care_plan_view_emits_event(client):
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)
    raw_token = client.post(f"/patients/{patient['id']}/care-access-tokens", headers=headers).json()["token"]

    client.get("/care-plan", params={"token": raw_token})

    events = _audit_events(client, headers, patient["id"])["results"]
    assert "CARE_PLAN_VIEWED" in _event_types(events)
    viewed = [e for e in events if e["event_type"] == "CARE_PLAN_VIEWED"][0]
    assert viewed["actor_type"] == "PATIENT"


def test_care_plan_view_is_deduplicated_within_window(client):
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)
    raw_token = client.post(f"/patients/{patient['id']}/care-access-tokens", headers=headers).json()["token"]

    client.get("/care-plan", params={"token": raw_token})
    client.get("/care-plan", params={"token": raw_token})
    client.get("/care-plan", params={"token": raw_token})

    events = _audit_events(client, headers, patient["id"])["results"]
    viewed = [e for e in events if e["event_type"] == "CARE_PLAN_VIEWED"]
    assert len(viewed) == 1


def test_care_plan_view_emits_new_event_after_dedup_window_elapses(client, db_session):
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)
    raw_token = client.post(f"/patients/{patient['id']}/care-access-tokens", headers=headers).json()["token"]

    client.get("/care-plan", params={"token": raw_token})

    # Simulate the dedup window having elapsed.
    event = db_session.query(AuditEvent).filter(AuditEvent.event_type == "CARE_PLAN_VIEWED").one()
    event.created_at = datetime.now(timezone.utc) - timedelta(minutes=10)
    db_session.commit()

    client.get("/care-plan", params={"token": raw_token})

    events = _audit_events(client, headers, patient["id"])["results"]
    viewed = [e for e in events if e["event_type"] == "CARE_PLAN_VIEWED"]
    assert len(viewed) == 2


def test_invalid_token_does_not_create_any_audit_event(client, db_session):
    before = db_session.query(AuditEvent).count()

    resp = client.get("/care-plan", params={"token": "totally-made-up-token"})
    assert resp.status_code == 401

    after = db_session.query(AuditEvent).count()
    assert after == before


# ---------------------------------------------------------------------------
# Authorization boundary
# ---------------------------------------------------------------------------


def test_audit_endpoint_requires_clinician_auth(client):
    patient_id = uuid.uuid4()
    resp = client.get(f"/patients/{patient_id}/audit")
    assert resp.status_code == 401


def test_audit_endpoint_404s_for_unknown_patient(client):
    headers = _register_and_login(client)
    resp = client.get(f"/patients/{uuid.uuid4()}/audit", headers=headers)
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Pagination / filtering
# ---------------------------------------------------------------------------


def test_audit_pagination(client):
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)
    for i in range(3):
        client.patch(f"/patients/{patient['id']}", json={"room_number": f"10{i}"}, headers=headers)

    page1 = _audit_events(client, headers, patient["id"], limit=2, offset=0)
    page2 = _audit_events(client, headers, patient["id"], limit=2, offset=2)

    assert page1["total"] == 4  # PATIENT_CREATED + 3 updates
    assert len(page1["results"]) == 2
    assert len(page2["results"]) == 2


def test_audit_filter_by_event_type(client):
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)
    client.patch(f"/patients/{patient['id']}", json={"room_number": "500"}, headers=headers)

    filtered = _audit_events(client, headers, patient["id"], event_type="PATIENT_UPDATED")
    assert filtered["total"] == 1
    assert filtered["results"][0]["event_type"] == "PATIENT_UPDATED"


def test_audit_filter_by_time_range(client):
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)

    far_future = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    filtered = _audit_events(client, headers, patient["id"], **{"from": far_future})
    assert filtered["total"] == 0


# ---------------------------------------------------------------------------
# Immutability
# ---------------------------------------------------------------------------


def test_no_modification_endpoints_exist_for_audit(client):
    headers = _register_and_login(client)
    patient = _create_active_patient(client, headers)

    patch_resp = client.patch(f"/patients/{patient['id']}/audit", headers=headers)
    delete_resp = client.delete(f"/patients/{patient['id']}/audit", headers=headers)

    assert patch_resp.status_code in (404, 405)
    assert delete_resp.status_code in (404, 405)


def test_no_modification_routes_registered_in_app(client):
    from app.main import app

    audit_routes = [r for r in app.routes if getattr(r, "path", "").endswith("/audit")]
    assert audit_routes, "expected the /patients/{patient_id}/audit route to be registered"
    for route in audit_routes:
        assert route.methods == {"GET"}
