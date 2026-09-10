"""Unit tests for the three-tier "why" decision (patient_access/service.py's
resolve_why) — deterministic, not LLM-decided, same as completeness/
fact-preservation. Constructs StructuredExtraction directly (no DB needed;
resolve_why only reads .instruction_type/.normalized_facts)."""

from app.instructions.models import InstructionType, StructuredExtraction
from app.patient_access.schemas import WhyTier
from app.patient_access.service import resolve_why


def _extraction(instruction_type: InstructionType, **facts) -> StructuredExtraction:
    return StructuredExtraction(instruction_type=instruction_type, normalized_facts=facts)


def test_none_extraction_returns_none():
    assert resolve_why(None) is None


def test_documented_reason_wins_tier_1():
    extraction = _extraction(InstructionType.MEDICATION, medication_name="Metoprolol", reason="your blood pressure")

    result = resolve_why(extraction)

    assert result.tier == WhyTier.DOCUMENTED
    assert result.text == "your blood pressure"
    assert result.disclaimer is None


def test_general_reference_used_when_no_documented_reason_tier_2():
    extraction = _extraction(InstructionType.MEDICATION, medication_name="Metoprolol", reason=None)

    result = resolve_why(extraction)

    assert result.tier == WhyTier.GENERAL
    assert "blood pressure" in result.text.lower()
    assert result.disclaimer is not None


def test_documented_reason_takes_priority_over_general_reference():
    """Even though Metoprolol has a general-reference entry, the clinician's
    own documented reason must always win — never overridden by the generic
    fallback."""
    extraction = _extraction(
        InstructionType.MEDICATION, medication_name="Metoprolol", reason="an irregular heartbeat"
    )

    result = resolve_why(extraction)

    assert result.tier == WhyTier.DOCUMENTED
    assert result.text == "an irregular heartbeat"


def test_unknown_medication_no_reason_falls_to_tier_3_none():
    extraction = _extraction(InstructionType.MEDICATION, medication_name="SomeMadeUpDrugXYZ", reason=None)

    assert resolve_why(extraction) is None


def test_missing_medication_name_falls_to_tier_3_none():
    extraction = _extraction(InstructionType.MEDICATION, medication_name=None, reason=None)

    assert resolve_why(extraction) is None


def test_mobility_has_no_general_reference_table_falls_to_tier_3_when_undocumented():
    """Only MEDICATION has a general-reference table in this prototype — other
    instruction types with no documented reason must fall straight to Tier 3,
    never fabricate a general fallback that doesn't exist."""
    extraction = _extraction(InstructionType.MOBILITY, activity="walking", reason=None)

    assert resolve_why(extraction) is None


def test_mobility_documented_reason_still_works_tier_1():
    extraction = _extraction(InstructionType.MOBILITY, activity="walking", reason="your recovery after surgery")

    result = resolve_why(extraction)

    assert result.tier == WhyTier.DOCUMENTED
    assert result.text == "your recovery after surgery"


def test_follow_up_uses_purpose_field_not_reason():
    extraction = _extraction(InstructionType.FOLLOW_UP, purpose="suture removal")

    result = resolve_why(extraction)

    assert result.tier == WhyTier.DOCUMENTED
    assert result.text == "suture removal"
