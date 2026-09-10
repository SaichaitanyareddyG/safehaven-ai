"""Configurable completeness rules per instruction type.

These are prototype safety rules, not a clinically authoritative reference. They
are intentionally centralized here (rather than scattered across service methods)
so they can be reviewed, extended, or replaced without touching extraction or
workflow code. See validation/completeness.py for how they're applied.
"""

from app.instructions.models import InstructionType
from app.validation.schemas import FieldRule

RULES_BY_TYPE: dict[InstructionType, list[FieldRule]] = {
    InstructionType.MEDICATION: [
        FieldRule("medication_name", "critical", "Medication name is required."),
        FieldRule("dose_value", "critical", "Dose amount is required."),
        FieldRule("dose_unit", "critical", "Dose unit is required."),
        FieldRule("frequency", "critical", "Frequency is required."),
        FieldRule("route", "clarification", "Route of administration is unclear and should be confirmed."),
        FieldRule("timing", "optional", "Timing was not specified."),
        FieldRule("duration", "optional", "Course length was not specified."),
        FieldRule("with_food", "optional", "Food requirement was not specified."),
        FieldRule("reason", "optional", "Reason for this medication was not specified."),
    ],
    InstructionType.MOBILITY: [
        FieldRule("activity", "critical", "Activity is required."),
        FieldRule("timing", "critical", "Timing is required."),
        FieldRule(
            "assistance_required",
            "clarification",
            "Assistance requirement is unknown and should be confirmed for this patient's mobility plan.",
        ),
        FieldRule("duration", "optional", "Duration was not specified."),
        FieldRule("reason", "optional", "Reason for this activity was not specified."),
    ],
    InstructionType.DIET: [
        FieldRule(
            "restricted_intake", "clarification", "It is unclear what foods or intake should be restricted."
        ),
        FieldRule("allowed_intake", "optional", "Allowed intake was not specified."),
        FieldRule("timing", "optional", "Timing was not specified."),
        FieldRule("special_restrictions", "optional", "No special restrictions were noted."),
        FieldRule("reason", "optional", "Reason for this diet instruction was not specified."),
    ],
    InstructionType.WOUND_CARE: [
        FieldRule("body_site", "critical", "The wound or body site being treated is required."),
        FieldRule("action", "critical", "The care action (e.g. clean, change dressing) is required."),
        FieldRule(
            "frequency", "clarification", "How often this should be performed is unclear and should be confirmed."
        ),
        FieldRule("supplies", "optional", "Supplies needed were not specified."),
        FieldRule("warning_signs", "optional", "Warning signs to watch for were not specified."),
        FieldRule("reason", "optional", "Reason for this wound care instruction was not specified."),
    ],
    InstructionType.FOLLOW_UP: [
        FieldRule("timeframe", "critical", "A timeframe for follow-up is required."),
        FieldRule(
            "provider_or_specialty", "clarification", "Which provider or specialty to follow up with is unclear."
        ),
        FieldRule("purpose", "optional", "The purpose of the follow-up was not specified."),
    ],
    # GENERAL has no well-defined clinical fields to check — it's a catch-all for
    # content that didn't fit a specific type. completeness.py always routes GENERAL
    # to clarification directly (a type-level rule, not a field-level one), rather
    # than faking a field rule here just to trigger the same effect.
    InstructionType.GENERAL: [],
}
