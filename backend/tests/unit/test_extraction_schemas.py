import pytest
from pydantic import ValidationError

from app.ai.schemas import extraction_result_adapter
from app.instructions.models import InstructionType


def test_valid_medication_payload_validates():
    payload = {
        "instruction_type": "MEDICATION",
        "facts": {
            "medication_name": "Metoprolol",
            "dose_value": 25,
            "dose_unit": "mg",
            "route": "oral",
            "frequency": "twice daily",
            "timing": None,
            "with_food": True,
            "warnings": [],
        },
        "ambiguities": [],
    }

    result = extraction_result_adapter.validate_python(payload)

    assert result.instruction_type == InstructionType.MEDICATION
    assert result.facts.medication_name == "Metoprolol"
    assert result.facts.dose_value == 25


def test_valid_mobility_payload_with_nulls_validates():
    payload = {
        "instruction_type": "MOBILITY",
        "facts": {"activity": "walking", "timing": "after meals", "duration": None, "assistance_required": None},
        "ambiguities": [],
    }

    result = extraction_result_adapter.validate_python(payload)

    assert result.facts.duration is None
    assert result.facts.assistance_required is None


def test_unknown_instruction_type_is_rejected():
    payload = {"instruction_type": "SURGERY", "facts": {}, "ambiguities": []}

    with pytest.raises(ValidationError):
        extraction_result_adapter.validate_python(payload)


def test_facts_as_wrong_type_is_rejected():
    payload = {"instruction_type": "MEDICATION", "facts": "not-an-object", "ambiguities": []}

    with pytest.raises(ValidationError):
        extraction_result_adapter.validate_python(payload)


def test_missing_required_top_level_key_is_rejected():
    payload = {"facts": {"activity": "walking"}, "ambiguities": []}

    with pytest.raises(ValidationError):
        extraction_result_adapter.validate_python(payload)


def test_dose_value_as_non_numeric_string_is_rejected():
    payload = {
        "instruction_type": "MEDICATION",
        "facts": {
            "medication_name": "Metoprolol",
            "dose_value": "a lot",
            "dose_unit": "mg",
            "route": None,
            "frequency": None,
            "timing": None,
            "with_food": None,
            "warnings": [],
        },
        "ambiguities": [],
    }

    with pytest.raises(ValidationError):
        extraction_result_adapter.validate_python(payload)


def test_general_facts_shape_validates():
    payload = {
        "instruction_type": "GENERAL",
        "facts": {"summary": "See attached brochure.", "details": []},
        "ambiguities": [],
    }

    result = extraction_result_adapter.validate_python(payload)

    assert result.instruction_type == InstructionType.GENERAL
    assert result.facts.summary == "See attached brochure."


def test_ambiguities_defaults_to_empty_list_when_omitted():
    payload = {
        "instruction_type": "MOBILITY",
        "facts": {"activity": "walking", "timing": None, "duration": None, "assistance_required": None},
    }

    result = extraction_result_adapter.validate_python(payload)

    assert result.ambiguities == []
