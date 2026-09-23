"""Guard against an audit event existing in Python with no human-readable
label in the frontend.

This is a cross-language check, which is unusual — it lives here because the
backend is where the enum is defined and where the test suite runs, and
because the failure it catches is real and already happened: eight Module 2
event types (plus LOGIN_FAILED, INSTRUCTION_DICTATED, the allergy and
condition events) had no label, so the patient's activity timeline rendered
raw strings like "MEDICATION_MISMATCH". Worse, an unlabelled event also has
no category, so a BLOCKED wrong-drug scan displayed as a grey "info" dot
indistinguishable from "Clinician logged in" — the safety catch was recorded
and then made invisible.

Adding an AuditEventType without a label is easy to do and silent, so this
makes it loud instead."""

import re
from pathlib import Path

import pytest

from app.audit.models import AuditEventType

_LABELS_FILE = Path(__file__).resolve().parents[3] / "frontend" / "src" / "lib" / "audit-event-labels.ts"


def test_every_audit_event_type_has_a_frontend_label():
    if not _LABELS_FILE.exists():
        pytest.skip("frontend not present in this checkout")

    source = _LABELS_FILE.read_text()
    labelled = set(re.findall(r"case '([A-Z_]+)'", source))

    missing = sorted(event.value for event in AuditEventType if event.value not in labelled)

    assert missing == [], (
        f"AuditEventType values with no case in audit-event-labels.ts: {missing}. "
        "These render as raw enum strings on the patient activity timeline."
    )
