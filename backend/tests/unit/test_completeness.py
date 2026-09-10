from app.instructions.models import CompletenessStatus, InstructionType
from app.validation.completeness import evaluate_completeness


def test_complete_medication_passes():
    facts = {
        "medication_name": "Metoprolol",
        "dose_value": 25.0,
        "dose_unit": "mg",
        "route": "oral",
        "frequency": "twice daily",
        "timing": None,
        "with_food": True,
        "warnings": [],
    }

    result = evaluate_completeness(InstructionType.MEDICATION, facts, ambiguities=[])

    assert result.completeness_status == CompletenessStatus.PASSED
    assert result.clarification_required_fields == []
    assert "timing" in result.missing_fields  # optional-tier, noted but non-blocking


def test_missing_critical_medication_field_forces_clarification():
    facts = {
        "medication_name": "Metoprolol",
        "dose_value": None,
        "dose_unit": None,
        "route": None,
        "frequency": None,
        "timing": None,
        "with_food": None,
        "warnings": [],
    }

    result = evaluate_completeness(InstructionType.MEDICATION, facts, ambiguities=[])

    assert result.completeness_status == CompletenessStatus.NEEDS_CLARIFICATION
    assert "dose_value" in result.clarification_required_fields
    assert "dose_unit" in result.clarification_required_fields
    assert "frequency" in result.clarification_required_fields


def test_missing_optional_field_does_not_require_clarification():
    """This is the core rule the user wants demonstrated: a missing field is not
    automatically a blocker — only critical/clarification-tier fields are."""
    facts = {"activity": "walking", "timing": "after meals", "duration": None, "assistance_required": True}

    result = evaluate_completeness(InstructionType.MOBILITY, facts, ambiguities=[])

    assert "duration" in result.missing_fields
    assert "duration" not in result.clarification_required_fields
    assert result.completeness_status == CompletenessStatus.PASSED


def test_missing_clarification_tier_field_requires_clarification():
    """The exact "walk after meals" case: duration missing (optional, doesn't
    block) vs assistance_required missing (clarification-tier, does block)."""
    facts = {"activity": "walking", "timing": "after meals", "duration": None, "assistance_required": None}

    result = evaluate_completeness(InstructionType.MOBILITY, facts, ambiguities=[])

    assert set(result.missing_fields) == {"assistance_required", "duration", "reason"}
    assert result.clarification_required_fields == ["assistance_required"]
    assert result.completeness_status == CompletenessStatus.NEEDS_CLARIFICATION


def test_configurable_rule_can_make_assistance_required_mandatory():
    """Demonstrates the rule is genuinely table-driven: monkeypatch a copy of the
    rules to make `duration` critical too, and confirm the engine picks it up
    without any code change — i.e. the LLM has no say in this, the table does."""
    from app.validation import rules as rules_module
    from app.validation.schemas import FieldRule

    original = rules_module.RULES_BY_TYPE[InstructionType.MOBILITY]
    try:
        rules_module.RULES_BY_TYPE[InstructionType.MOBILITY] = [
            FieldRule("activity", "critical", "Activity is required."),
            FieldRule("timing", "critical", "Timing is required."),
            FieldRule("assistance_required", "clarification", "Assistance requirement is unknown."),
            FieldRule("duration", "critical", "Duration is now mandatory in this configuration."),
        ]
        facts = {"activity": "walking", "timing": "after meals", "duration": None, "assistance_required": True}
        result = evaluate_completeness(InstructionType.MOBILITY, facts, ambiguities=[])
        assert "duration" in result.clarification_required_fields
    finally:
        rules_module.RULES_BY_TYPE[InstructionType.MOBILITY] = original


def test_ambiguous_field_requires_clarification_even_if_present():
    facts = {"activity": "walking", "timing": "after meals", "duration": "some", "assistance_required": True}

    result = evaluate_completeness(InstructionType.MOBILITY, facts, ambiguities=["timing"])

    assert result.ambiguous_fields == ["timing"]
    assert "timing" in result.clarification_required_fields
    assert result.completeness_status == CompletenessStatus.NEEDS_CLARIFICATION


def test_general_type_always_requires_clarification():
    result = evaluate_completeness(InstructionType.GENERAL, {"summary": "some text", "details": []}, ambiguities=[])

    assert result.completeness_status == CompletenessStatus.NEEDS_CLARIFICATION
    assert "instruction_type" in result.clarification_required_fields
