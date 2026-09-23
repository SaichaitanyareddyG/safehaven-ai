"""Deterministic rules turning a reported event into an alert decision.

Pure functions: no database, no I/O, no LLM. That is not incidental — it is the
Module 3 answer to this codebase's governing principle, "AI proposes,
deterministic code decides, a clinician approves" (DOCUMENTATION.md §1). The
device proposes a candidate with its evidence; this module decides whether a
nurse is told; the nurse assesses the patient. No model is involved anywhere in
that path, and Module 3 V1 requires zero LLM calls.

Two things this module deliberately does NOT do:

  • It does not trust the device's own conclusion. The firmware already applied
    a score threshold before sending, but a device with stale configuration,
    modified firmware, or a bug could send a weak candidate. The threshold is
    re-checked here, server-side, where the value is controlled.

  • It does not diagnose. A matched pattern becomes "possible fall" or
    "abnormal repetitive movement", never a cause.
"""

from dataclasses import dataclass

from app.wearables.models import (
    AlertPriority,
    AlertType,
    MonitoringProfile,
    SensorEventType,
)


@dataclass(frozen=True)
class AlertDecision:
    """Whether to alert, and why not if not.

    `reason` exists so a suppressed event is explainable. "Nothing happened" is
    the hardest outcome to debug, and the most important one to get right —
    most real-world wrist motion should end here.
    """

    should_alert: bool
    alert_type: AlertType | None = None
    priority: AlertPriority | None = None
    reason: str = ""


# Event types that map one-to-one onto an alert type.
_EVENT_TO_ALERT = {
    SensorEventType.POSSIBLE_FALL: AlertType.POSSIBLE_FALL,
    SensorEventType.ABNORMAL_MOVEMENT: AlertType.ABNORMAL_MOVEMENT,
    SensorEventType.UNEXPECTED_MOBILITY: AlertType.UNEXPECTED_MOBILITY,
    SensorEventType.DEVICE_LOW_BATTERY: AlertType.DEVICE_LOW_BATTERY,
}

# Profiles under which a heightened-risk patient's abnormal movement is treated
# as urgent rather than routine.
_ELEVATED_PROFILES = (MonitoringProfile.FALL_RISK, MonitoringProfile.RESTRICTED_MOBILITY)


def evaluate(
    event_type: SensorEventType,
    metrics: dict,
    profile: MonitoringProfile,
    min_fall_score: int,
) -> AlertDecision:
    """Decide whether one event warrants a nurse alert."""

    if event_type is SensorEventType.POSSIBLE_FALL:
        # Re-check the evidence server-side rather than trusting the device's
        # conclusion. `stages_seen` is the basis; fall_score is its count.
        score = int(metrics.get("fall_score") or 0)
        if score < min_fall_score:
            return AlertDecision(
                False,
                reason=f"fall score {score} below threshold {min_fall_score}",
            )
        return AlertDecision(True, AlertType.POSSIBLE_FALL, AlertPriority.HIGH)

    if event_type is SensorEventType.ABNORMAL_MOVEMENT:
        # HIGH for a patient already flagged as higher-risk, MEDIUM otherwise.
        # The signal is identical; what differs is how quickly someone should
        # look, which is an operational judgement the profile already encodes.
        priority = (
            AlertPriority.HIGH if profile in _ELEVATED_PROFILES else AlertPriority.MEDIUM
        )
        return AlertDecision(True, AlertType.ABNORMAL_MOVEMENT, priority)

    if event_type is SensorEventType.UNEXPECTED_MOBILITY:
        # Gated on explicit configuration, not inferred from anything clinical.
        # A device sending this under another profile is misconfigured or
        # running stale config; either way it must not alert.
        if profile is not MonitoringProfile.RESTRICTED_MOBILITY:
            return AlertDecision(
                False,
                reason=f"mobility monitoring not enabled for profile {profile.value}",
            )
        # MEDIUM, not HIGH, and this is deliberate: a wrist IMU cannot prove a
        # patient left a bed, so the most inferential signal in Module 3 must
        # not outrank a possible fall.
        return AlertDecision(True, AlertType.UNEXPECTED_MOBILITY, AlertPriority.MEDIUM)

    if event_type is SensorEventType.DEVICE_LOW_BATTERY:
        # Operational, not clinical. It matters because a dead wearable stops
        # monitoring, but it is not itself a patient event.
        return AlertDecision(True, AlertType.DEVICE_LOW_BATTERY, AlertPriority.LOW)

    return AlertDecision(False, reason=f"no rule for event type {event_type}")


def is_operational(alert_type: AlertType) -> bool:
    """Device-health alerts, as opposed to patient-observation alerts.

    They dedupe differently: a battery stays low for hours, so the short
    time-window used for clinical episodes would re-alert repeatedly. See
    service.evaluate_event.
    """
    return alert_type in (AlertType.DEVICE_LOW_BATTERY, AlertType.DEVICE_OFFLINE)
