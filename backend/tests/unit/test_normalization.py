from app.instructions.models import InstructionType
from app.validation.normalization import normalize_facts


def test_dose_unit_casing_is_normalized():
    facts = {"dose_value": 25.0, "dose_unit": "MG", "route": None, "frequency": None}

    normalized, changes = normalize_facts(InstructionType.MEDICATION, facts)

    assert normalized["dose_unit"] == "mg"
    assert normalized["dose_value"] == 25.0  # untouched
    assert any(c.field == "dose_unit" and c.source_value == "MG" and c.normalized_value == "mg" for c in changes)


def test_dose_value_number_is_never_changed():
    facts = {"dose_value": 25.0, "dose_unit": "mg", "route": None, "frequency": None}

    normalized, changes = normalize_facts(InstructionType.MEDICATION, facts)

    assert normalized["dose_value"] == 25.0
    assert not any(c.field == "dose_value" for c in changes)


def test_frequency_abbreviation_is_normalized_and_source_preserved():
    facts = {"dose_value": 25.0, "dose_unit": "mg", "route": "oral", "frequency": "BID"}

    normalized, changes = normalize_facts(InstructionType.MEDICATION, facts)

    assert normalized["frequency"] == "twice daily"
    change = next(c for c in changes if c.field == "frequency")
    assert change.source_value == "BID"
    assert change.normalized_value == "twice daily"


def test_route_abbreviation_po_becomes_oral():
    facts = {"dose_value": 25.0, "dose_unit": "mg", "route": "PO", "frequency": "once daily"}

    normalized, _changes = normalize_facts(InstructionType.MEDICATION, facts)

    assert normalized["route"] == "oral"


def test_already_normalized_values_produce_no_changes():
    facts = {"dose_value": 25.0, "dose_unit": "mg", "route": "oral", "frequency": "twice daily"}

    normalized, changes = normalize_facts(InstructionType.MEDICATION, facts)

    assert normalized == facts
    assert changes == []


def test_none_values_pass_through_untouched():
    facts = {"dose_value": None, "dose_unit": None, "route": None, "frequency": None}

    normalized, changes = normalize_facts(InstructionType.MEDICATION, facts)

    assert normalized == facts
    assert changes == []


def test_mobility_timing_is_lowercased():
    facts = {"activity": "walking", "timing": "After Meals", "duration": None, "assistance_required": None}

    normalized, changes = normalize_facts(InstructionType.MOBILITY, facts)

    assert normalized["timing"] == "after meals"
    assert any(c.field == "timing" for c in changes)


def test_route_by_mouth_becomes_oral():
    """Regression test for a real Step 10 finding: gpt-4o-mini and gpt-5-mini
    both consistently paraphrase 'oral' as 'by mouth' during patient-friendly
    generation (a safer, plainer word choice, not an error) and back-translation
    — without this normalization, the fact-preservation validator falsely
    blocked that safe paraphrase as a changed route on nearly every medication
    case evaluated."""
    facts = {"dose_value": 25.0, "dose_unit": "mg", "route": "by mouth", "frequency": "once daily"}

    normalized, changes = normalize_facts(InstructionType.MEDICATION, facts)

    assert normalized["route"] == "oral"
    assert any(c.field == "route" and c.source_value == "by mouth" for c in changes)


def test_frequency_once_a_day_becomes_once_daily():
    """Regression test for a real Step 10 finding: real-model back-translation
    consistently rendered 'once daily'/'twice daily' as 'once a day'/'twice a
    day', which the validator falsely flagged as a changed frequency."""
    facts = {"dose_value": 25.0, "dose_unit": "mg", "route": "oral", "frequency": "once a day"}

    normalized, _changes = normalize_facts(InstructionType.MEDICATION, facts)

    assert normalized["frequency"] == "once daily"

    facts_twice = {"dose_value": 25.0, "dose_unit": "mg", "route": "oral", "frequency": "twice a day"}
    normalized_twice, _changes = normalize_facts(InstructionType.MEDICATION, facts_twice)
    assert normalized_twice["frequency"] == "twice daily"


def test_once_every_morning_frequency_splits_into_frequency_and_timing():
    """Regression test for a real, repeatedly observed back-translation
    finding: 'once daily' + 'in the morning' re-extracts as a single phrase
    like 'once every morning' entirely inside frequency, with timing left
    null — the exact same clinical fact, just re-drawn across the field
    boundary. Without this, translation validation falsely blocked it."""
    facts = {"dose_value": 10.0, "dose_unit": "mg", "route": "oral", "frequency": "once every morning", "timing": None}

    normalized, changes = normalize_facts(InstructionType.MEDICATION, facts)

    assert normalized["frequency"] == "once daily"
    assert normalized["timing"] == "in the morning"
    assert any(c.field == "frequency+timing" for c in changes)


def test_bare_every_morning_timing_with_no_frequency_splits_too():
    """Real observed pattern: frequency comes back empty entirely, with
    'every morning' landing in timing alone."""
    facts = {"dose_value": 10.0, "dose_unit": "mg", "route": "oral", "frequency": None, "timing": "every morning"}

    normalized, _changes = normalize_facts(InstructionType.MEDICATION, facts)

    assert normalized["frequency"] == "once daily"
    assert normalized["timing"] == "in the morning"


def test_once_frequency_with_every_morning_timing_splits_too():
    """Real observed pattern: frequency drops 'daily' (becomes bare 'once')
    while timing absorbs 'every' instead of 'in the'."""
    facts = {"dose_value": 10.0, "dose_unit": "mg", "route": "oral", "frequency": "once", "timing": "every morning"}

    normalized, _changes = normalize_facts(InstructionType.MEDICATION, facts)

    assert normalized["frequency"] == "once daily"
    assert normalized["timing"] == "in the morning"


def test_already_canonical_once_daily_in_the_morning_reports_no_change():
    facts = {"dose_value": 10.0, "dose_unit": "mg", "route": "oral", "frequency": "once daily", "timing": "in the morning"}

    normalized, changes = normalize_facts(InstructionType.MEDICATION, facts)

    assert normalized["frequency"] == "once daily"
    assert normalized["timing"] == "in the morning"
    assert not any(c.field == "frequency+timing" for c in changes)


def test_twice_daily_with_time_of_day_is_never_touched():
    """A genuinely different interval mentioning a time of day must never be
    folded into 'once daily' — this would silently change a real dosing
    schedule, not just its wording."""
    facts = {"dose_value": 10.0, "dose_unit": "mg", "route": "oral", "frequency": "twice daily", "timing": "in the morning"}

    normalized, changes = normalize_facts(InstructionType.MEDICATION, facts)

    assert normalized["frequency"] == "twice daily"
    assert normalized["timing"] == "in the morning"
    assert not any(c.field == "frequency+timing" for c in changes)


def test_every_6_hours_is_never_touched():
    facts = {"dose_value": 10.0, "dose_unit": "mg", "route": "oral", "frequency": "every 6 hours", "timing": None}

    normalized, _changes = normalize_facts(InstructionType.MEDICATION, facts)

    assert normalized["frequency"] == "every 6 hours"
    assert normalized["timing"] is None


def test_every_other_day_with_time_of_day_is_never_touched():
    """'Every other day' is a genuinely different interval from 'once daily'
    — even with a time of day attached, must never be reclassified."""
    facts = {
        "dose_value": 10.0,
        "dose_unit": "mg",
        "route": "oral",
        "frequency": "every other day",
        "timing": "in the morning",
    }

    normalized, changes = normalize_facts(InstructionType.MEDICATION, facts)

    assert normalized["frequency"] == "every other day"
    assert normalized["timing"] == "in the morning"
    assert not any(c.field == "frequency+timing" for c in changes)


def test_as_needed_with_time_of_day_is_never_touched():
    facts = {
        "dose_value": 10.0,
        "dose_unit": "mg",
        "route": "oral",
        "frequency": "as needed",
        "timing": "in the morning",
    }

    normalized, changes = normalize_facts(InstructionType.MEDICATION, facts)

    assert normalized["frequency"] == "as needed"
    assert normalized["timing"] == "in the morning"
    assert not any(c.field == "frequency+timing" for c in changes)


def test_no_time_of_day_present_leaves_frequency_and_timing_alone():
    facts = {"dose_value": 10.0, "dose_unit": "mg", "route": "oral", "frequency": "once daily", "timing": None}

    normalized, changes = normalize_facts(InstructionType.MEDICATION, facts)

    assert normalized["frequency"] == "once daily"
    assert normalized["timing"] is None
    assert not any(c.field == "frequency+timing" for c in changes)


def test_unrecognized_instruction_type_passes_through_unchanged():
    facts = {"body_site": "left forearm", "action": "Clean and re-dress"}

    normalized, changes = normalize_facts(InstructionType.WOUND_CARE, facts)

    assert normalized == facts
    assert changes == []
