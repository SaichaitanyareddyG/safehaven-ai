"""Module 3 Stage 4 — the deterministic rules, tested without a database.

These are the decisions that turn an observation into an alert, so they are
worth testing in isolation: no HTTP, no DB, no LLM. Covers
MODULE_3_IMPLEMENTATION_PLAN.md §28 tests 11 and 12.
"""

import pytest

from app.wearables import rules, service
from app.wearables.models import (
    AlertPriority,
    AlertType,
    MonitoringProfile,
    SensorEventType,
)

MIN_SCORE = 3

# Terms the alert wording must never contain. A wearable observes movement; it
# cannot establish a cause, and claiming one would be a clinical assertion the
# sensor cannot support.
FORBIDDEN_CLINICAL_TERMS = (
    "seizure",
    "epilep",
    "convuls",
    "stroke",
    "cardiac",
    "arrest",
    "overdose",
    "reaction",
    "neurolog",
    "tremor",
    "delirium",
    "syncope",
    "left bed",
    "out of bed",
    "fell",
    "diagnos",
)


def _evaluate(event_type, metrics=None, profile=MonitoringProfile.STANDARD):
    return rules.evaluate(event_type, metrics or {}, profile, MIN_SCORE)


# ── fall: the server re-checks the device's evidence ────────────────────────


def test_strong_fall_alerts_high():
    d = _evaluate(SensorEventType.POSSIBLE_FALL, {"fall_score": 4})
    assert d.should_alert
    assert d.alert_type is AlertType.POSSIBLE_FALL
    assert d.priority is AlertPriority.HIGH


def test_fall_at_exactly_the_threshold_alerts():
    assert _evaluate(SensorEventType.POSSIBLE_FALL, {"fall_score": MIN_SCORE}).should_alert


def test_weak_fall_is_silent():
    """A device with stale config, modified firmware or a bug could send a weak
    candidate. The threshold is re-applied server-side, where it is
    controlled."""
    d = _evaluate(SensorEventType.POSSIBLE_FALL, {"fall_score": 1})
    assert not d.should_alert
    assert "below threshold" in d.reason


def test_fall_with_missing_or_null_score_is_silent():
    """Absent evidence is not evidence. Defaulting a missing score to anything
    alerting would let a malformed payload raise a fall alert."""
    assert not _evaluate(SensorEventType.POSSIBLE_FALL, {}).should_alert
    assert not _evaluate(SensorEventType.POSSIBLE_FALL, {"fall_score": None}).should_alert


def test_fall_priority_is_high_under_every_profile():
    """A fall is a fall. The profile changes what else is watched, never how
    urgent a fall is."""
    for profile in MonitoringProfile:
        d = _evaluate(SensorEventType.POSSIBLE_FALL, {"fall_score": 4}, profile)
        assert d.priority is AlertPriority.HIGH


# ── abnormal movement: priority follows the profile ─────────────────────────


def test_abnormal_movement_is_medium_under_standard():
    d = _evaluate(SensorEventType.ABNORMAL_MOVEMENT, profile=MonitoringProfile.STANDARD)
    assert d.should_alert
    assert d.priority is AlertPriority.MEDIUM


@pytest.mark.parametrize(
    "profile", [MonitoringProfile.FALL_RISK, MonitoringProfile.RESTRICTED_MOBILITY]
)
def test_abnormal_movement_is_high_for_higher_risk_patients(profile):
    assert _evaluate(SensorEventType.ABNORMAL_MOVEMENT, profile=profile).priority is (
        AlertPriority.HIGH
    )


# ── unexpected mobility: explicitly gated (§28 test 9) ─────────────────────


def test_mobility_alerts_only_under_restricted_mobility():
    d = _evaluate(
        SensorEventType.UNEXPECTED_MOBILITY, profile=MonitoringProfile.RESTRICTED_MOBILITY
    )
    assert d.should_alert
    assert d.alert_type is AlertType.UNEXPECTED_MOBILITY


@pytest.mark.parametrize(
    "profile", [MonitoringProfile.STANDARD, MonitoringProfile.FALL_RISK]
)
def test_mobility_is_silent_under_other_profiles(profile):
    """A device sending this under another profile is misconfigured or running
    stale config. Either way it must not alert."""
    d = _evaluate(SensorEventType.UNEXPECTED_MOBILITY, profile=profile)
    assert not d.should_alert
    assert "not enabled" in d.reason


def test_mobility_is_medium_not_high():
    """A wrist IMU cannot prove a patient left a bed, so Module 3's most
    inferential signal must not outrank a possible fall."""
    d = _evaluate(
        SensorEventType.UNEXPECTED_MOBILITY, profile=MonitoringProfile.RESTRICTED_MOBILITY
    )
    assert d.priority is AlertPriority.MEDIUM


# ── low battery ─────────────────────────────────────────────────────────────


def test_low_battery_is_low_priority():
    d = _evaluate(SensorEventType.DEVICE_LOW_BATTERY)
    assert d.should_alert
    assert d.priority is AlertPriority.LOW


def test_operational_classification():
    """Device-health alerts dedupe differently from clinical ones, so the
    distinction has to be explicit."""
    assert rules.is_operational(AlertType.DEVICE_LOW_BATTERY)
    assert rules.is_operational(AlertType.DEVICE_OFFLINE)
    assert not rules.is_operational(AlertType.POSSIBLE_FALL)
    assert not rules.is_operational(AlertType.ABNORMAL_MOVEMENT)
    assert not rules.is_operational(AlertType.UNEXPECTED_MOBILITY)


# ── wording guard (§28 test 12) ─────────────────────────────────────────────


def test_every_alert_type_has_a_message():
    for alert_type in AlertType:
        assert service.alert_message(alert_type)


def test_no_alert_message_claims_a_diagnosis():
    """The product rule, enforced as a test.

    Module 3 must not become "AI diagnoses the patient". The device observes,
    SAFEHAVEN alerts, the nurse assesses — so the wording may describe what was
    measured and never what caused it. Note "fell" is forbidden too: the alert
    says "possible fall", not that a fall happened."""
    for alert_type in AlertType:
        message = service.alert_message(alert_type).lower()
        for term in FORBIDDEN_CLINICAL_TERMS:
            assert term not in message, (
                f"{alert_type.value} message states or implies a clinical cause "
                f"({term!r}): {message!r}"
            )


def test_movement_and_mobility_wording_is_the_agreed_phrasing():
    assert (
        service.alert_message(AlertType.ABNORMAL_MOVEMENT)
        == "Abnormal repetitive movement detected — patient check recommended."
    )
    assert (
        service.alert_message(AlertType.UNEXPECTED_MOBILITY)
        == "Unexpected mobility detected — assistance may be required."
    )
    assert service.alert_message(AlertType.POSSIBLE_FALL) == "Possible fall detected — check patient."
