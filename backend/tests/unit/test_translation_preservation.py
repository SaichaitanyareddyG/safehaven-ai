from app.instructions.models import InstructionType
from app.validation.translation_preservation import validate_translation_preservation


def _medication_facts(**overrides) -> dict:
    facts = {
        "medication_name": "Metoprolol",
        "dose_value": 25.0,
        "dose_unit": "mg",
        "route": "oral",
        "frequency": "twice daily",
        "timing": None,
        "with_food": True,
    }
    facts.update(overrides)
    return facts


def test_valid_translation_passes():
    original = _medication_facts()
    result = validate_translation_preservation(
        InstructionType.MEDICATION,
        original,
        "[TELUGU_TR] Take Metoprolol 25 mg by mouth twice daily. Take it with food.",
        InstructionType.MEDICATION,
        dict(original),
        [],
    )
    assert result.passed is True
    assert result.differences == []


def test_dose_number_missing_from_translated_text_fails():
    original = _medication_facts(dose_value=25.0)
    result = validate_translation_preservation(
        InstructionType.MEDICATION,
        original,
        "[TELUGU_TR] Take Metoprolol by mouth twice daily.",  # no number at all
        InstructionType.MEDICATION,
        _medication_facts(dose_value=25.0),
        [],
    )
    assert result.passed is False
    assert any(d.field == "dose_value" and d.type == "MISSING" for d in result.differences)


def test_dose_changed_in_translated_text_fails_via_layer_a_even_if_backtranslation_matches():
    """Layer A (raw-text dose scan) is independent of Layer B — even if the
    back-translation/re-extraction step somehow produced matching facts, a
    translated text missing the exact source number must still fail."""
    original = _medication_facts(dose_value=25.0)
    result = validate_translation_preservation(
        InstructionType.MEDICATION,
        original,
        "[TELUGU_TR] Take Metoprolol 50 mg by mouth twice daily.",
        InstructionType.MEDICATION,
        _medication_facts(dose_value=25.0),  # back-translation "matches" original
        [],
    )
    assert result.passed is False
    assert any(d.field == "dose_value" and d.type == "MISSING" for d in result.differences)


def test_dose_changed_detected_via_backtranslation_comparison():
    original = _medication_facts(dose_value=25.0)
    result = validate_translation_preservation(
        InstructionType.MEDICATION,
        original,
        "[TELUGU_TR] Take Metoprolol 50 mg by mouth twice daily.",
        InstructionType.MEDICATION,
        _medication_facts(dose_value=50.0),
        [],
    )
    assert result.passed is False
    assert any(d.field == "dose_value" and d.type == "CHANGED" and d.generated == 50.0 for d in result.differences)


def test_frequency_change_fails():
    original = _medication_facts(frequency="twice daily")
    result = validate_translation_preservation(
        InstructionType.MEDICATION,
        original,
        "[TELUGU_TR] Take Metoprolol 25 mg by mouth once daily.",
        InstructionType.MEDICATION,
        _medication_facts(frequency="once daily"),
        [],
    )
    assert result.passed is False
    assert any(d.field == "frequency" and d.type == "CHANGED" for d in result.differences)


def test_mobility_duration_change_fails():
    original = {"activity": "walking", "timing": "after meals", "duration": "10 minutes", "assistance_required": True}
    changed = {**original, "duration": "15 minutes"}
    result = validate_translation_preservation(
        InstructionType.MOBILITY,
        original,
        "[TELUGU_TR] Walking for 15 minutes after meals with your nurse.",
        InstructionType.MOBILITY,
        changed,
        [],
    )
    assert result.passed is False
    assert any(d.field == "duration" and d.type == "CHANGED" for d in result.differences)


def test_assistance_requirement_change_fails():
    original = {"activity": "walking", "timing": "after meals", "duration": None, "assistance_required": True}
    changed = {**original, "assistance_required": False}
    result = validate_translation_preservation(
        InstructionType.MOBILITY,
        original,
        "[TELUGU_TR] Walking after meals on your own.",
        InstructionType.MOBILITY,
        changed,
        [],
    )
    assert result.passed is False
    assert any(d.field == "assistance_required" and d.type == "CHANGED" for d in result.differences)


def test_backtranslation_failure_is_treated_as_unsafe():
    original = _medication_facts()
    result = validate_translation_preservation(
        InstructionType.MEDICATION, original, "[TELUGU_TR] garbled text", None, None, None
    )
    assert result.passed is False
    assert any(d.type == "AMBIGUOUS" for d in result.differences)


def test_backtranslation_type_mismatch_fails():
    original = _medication_facts()
    result = validate_translation_preservation(
        InstructionType.MEDICATION,
        original,
        "[TELUGU_TR] Walk after meals.",
        InstructionType.MOBILITY,
        {"activity": "walking"},
        [],
    )
    assert result.passed is False
    assert any(d.field == "instruction_type" for d in result.differences)


def test_ambiguous_backtranslated_field_fails():
    original = _medication_facts()
    result = validate_translation_preservation(
        InstructionType.MEDICATION,
        original,
        "[TELUGU_TR] Take Metoprolol some amount by mouth twice daily.",
        InstructionType.MEDICATION,
        dict(original),
        ["dose_value"],
    )
    assert result.passed is False
    assert any(d.field == "dose_value" and d.type == "AMBIGUOUS" for d in result.differences)


def test_medication_name_unchanged_after_transliteration_passes():
    """The mock's own 'translation' doesn't actually transliterate, but this
    documents the intent: as long as the structured facts agree, the field is
    not flagged just because the text itself differs script-wise."""
    original = _medication_facts(medication_name="Metoprolol")
    result = validate_translation_preservation(
        InstructionType.MEDICATION,
        original,
        "[TELUGU_TR] మెటోప్రొలాల్ 25 mg మౌత్ ద్వారా రోజుకు రెండుసార్లు తీసుకోండి.",
        InstructionType.MEDICATION,
        _medication_facts(medication_name="Metoprolol"),
        [],
    )
    assert result.passed is True


def test_mobility_type_not_medication_skips_dose_scan():
    """Layer A's dose scan only applies to MEDICATION — a mobility instruction
    with no dose_value must not spuriously fail it."""
    original = {"activity": "walking", "timing": "after meals", "duration": None, "assistance_required": None}
    result = validate_translation_preservation(
        InstructionType.MOBILITY,
        original,
        "[TELUGU_TR] Walking after meals.",
        InstructionType.MOBILITY,
        dict(original),
        [],
    )
    assert result.passed is True
