from app.instructions.models import InstructionType
from app.validation.fact_preservation import (
    compare_facts,
    scan_for_preserved_dose,
    scan_for_preserved_warnings,
    validate_fact_preservation,
)


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


def _mobility_facts(**overrides) -> dict:
    facts = {"activity": "walking", "timing": "after meals", "duration": "10 minutes", "assistance_required": True}
    facts.update(overrides)
    return facts


# ---------------------------------------------------------------------------
# compare_facts — CHANGED / MISSING / ADDED
# ---------------------------------------------------------------------------


def test_identical_facts_produce_no_differences():
    facts = _medication_facts()
    assert compare_facts(InstructionType.MEDICATION, facts, dict(facts)) == []


def test_changed_numeric_dose_is_detected():
    original = _medication_facts(dose_value=25.0)
    generated = _medication_facts(dose_value=50.0)

    diffs = compare_facts(InstructionType.MEDICATION, original, generated)

    assert len(diffs) == 1
    assert diffs[0].field == "dose_value"
    assert diffs[0].type == "CHANGED"
    assert diffs[0].source == 25.0
    assert diffs[0].generated == 50.0


def test_changed_frequency_is_detected():
    original = _medication_facts(frequency="twice daily")
    generated = _medication_facts(frequency="once daily")

    diffs = compare_facts(InstructionType.MEDICATION, original, generated)

    assert any(d.field == "frequency" and d.type == "CHANGED" for d in diffs)


def test_changed_medication_name_is_detected():
    original = _medication_facts(medication_name="Metoprolol")
    generated = _medication_facts(medication_name="Atenolol")

    diffs = compare_facts(InstructionType.MEDICATION, original, generated)

    assert any(d.field == "medication_name" and d.type == "CHANGED" for d in diffs)


def test_changed_medication_duration_is_detected():
    """Regression test for a real gap found in live testing: a medication's
    course length ("for 3 days") had nowhere to be tracked or checked at all
    until this field was added — this proves a changed duration is now
    caught the same way a changed dose or frequency already is."""
    original = _medication_facts(duration="3 days")
    generated = _medication_facts(duration="5 days")

    diffs = compare_facts(InstructionType.MEDICATION, original, generated)

    assert any(d.field == "duration" and d.type == "CHANGED" for d in diffs)


def test_dropped_medication_duration_is_detected():
    original = _medication_facts(duration="3 days")
    generated = _medication_facts(duration=None)

    diffs = compare_facts(InstructionType.MEDICATION, original, generated)

    assert any(d.field == "duration" and d.type == "MISSING" for d in diffs)


def test_casing_only_difference_is_not_flagged():
    """Regression test for a real Step 10 finding: re-extraction of generated/
    back-translated text regularly re-cases a proper noun (e.g. a medication
    name mid-sentence) with no change in clinical meaning — this must not be
    treated as a changed fact."""
    original = _medication_facts(medication_name="Metoprolol")
    generated = _medication_facts(medication_name="metoprolol")

    diffs = compare_facts(InstructionType.MEDICATION, original, generated)

    assert not any(d.field == "medication_name" for d in diffs)


def test_timing_with_added_clarifying_words_is_not_flagged():
    """Regression test for a real, user-observed false positive: the model
    added clarifying scaffolding ("one dose ... the other dose ...") around an
    unchanged two-dose timing description. Every original word/number is still
    present in the generated phrase, so this must not be flagged as changed."""
    original = _medication_facts(timing="exactly 1 hour after breakfast and 1 hour after dinner")
    generated = _medication_facts(
        timing="one dose exactly 1 hour after breakfast and the other dose exactly 1 hour after dinner"
    )

    diffs = compare_facts(InstructionType.MEDICATION, original, generated)

    assert not any(d.field == "timing" for d in diffs)


def test_timing_with_changed_number_is_still_detected():
    """The leniency added for timing must not swallow an actual change — a
    different hour count is a real, unsafe difference."""
    original = _medication_facts(timing="exactly 1 hour after breakfast and 1 hour after dinner")
    generated = _medication_facts(timing="exactly 2 hours after breakfast and 1 hour after dinner")

    diffs = compare_facts(InstructionType.MEDICATION, original, generated)

    assert any(d.field == "timing" and d.type == "CHANGED" for d in diffs)


def test_timing_with_dropped_reference_is_still_detected():
    """Dropping one of two dose timings entirely must still fail, even though
    every remaining word is still technically present."""
    original = _mobility_facts(timing="after breakfast and after dinner")
    generated = _mobility_facts(timing="after breakfast")

    diffs = compare_facts(InstructionType.MOBILITY, original, generated)

    assert any(d.field == "timing" and d.type == "CHANGED" for d in diffs)


def test_reason_field_is_not_compared_by_generation_validator():
    """'reason' is deliberately excluded from compare_facts' field list — the
    generation prompt tells the model NOT to restate it in the flowing
    patient_text (it's shown separately, in its own 'why' section), so its
    expected absence there must never be flagged as a missing/changed fact."""
    original = _medication_facts(reason="your blood pressure")
    generated = _medication_facts(reason=None)

    diffs = compare_facts(InstructionType.MEDICATION, original, generated)

    assert not any(d.field == "reason" for d in diffs)


def test_non_timing_field_still_requires_exact_match():
    """The added leniency is scoped to timing only — route must still be an
    exact (post-normalization) match, even if one is a superset of the other."""
    original = _medication_facts(route="oral")
    generated = _medication_facts(route="oral solution")

    diffs = compare_facts(InstructionType.MEDICATION, original, generated)

    assert any(d.field == "route" and d.type == "CHANGED" for d in diffs)


def test_removed_route_is_missing():
    original = _medication_facts(route="oral")
    generated = _medication_facts(route=None)

    diffs = compare_facts(InstructionType.MEDICATION, original, generated)

    assert any(d.field == "route" and d.type == "MISSING" for d in diffs)


def test_optional_field_missing_in_both_produces_no_difference():
    original = _medication_facts(timing=None)
    generated = _medication_facts(timing=None)

    assert compare_facts(InstructionType.MEDICATION, original, generated) == []


def test_added_unsupported_fact_is_detected():
    """The core Layer C example: a field absent from source but present in the
    generated output — an unsupported fact the AI introduced."""
    original = _mobility_facts(duration=None)
    generated = _mobility_facts(duration="10 minutes")

    diffs = compare_facts(InstructionType.MOBILITY, original, generated)

    assert len(diffs) == 1
    assert diffs[0].field == "duration"
    assert diffs[0].type == "ADDED"
    assert diffs[0].source is None
    assert diffs[0].generated == "10 minutes"


def test_assistance_flipped_false_to_true_is_changed():
    original = _mobility_facts(assistance_required=False)
    generated = _mobility_facts(assistance_required=True)

    diffs = compare_facts(InstructionType.MOBILITY, original, generated)

    assert len(diffs) == 1
    assert diffs[0].field == "assistance_required"
    assert diffs[0].type == "CHANGED"


def test_assistance_flipped_true_to_false_is_changed():
    original = _mobility_facts(assistance_required=True)
    generated = _mobility_facts(assistance_required=False)

    diffs = compare_facts(InstructionType.MOBILITY, original, generated)

    assert len(diffs) == 1
    assert diffs[0].type == "CHANGED"


def test_equivalent_already_normalized_values_produce_no_difference():
    """compare_facts assumes both sides are already normalized (see
    validation/normalization.py) — this documents that assumption: it does
    plain equality, not abbreviation-aware comparison, by design."""
    original = _medication_facts(route="oral", frequency="twice daily")
    generated = _medication_facts(route="oral", frequency="twice daily")

    assert compare_facts(InstructionType.MEDICATION, original, generated) == []


def test_list_field_removed_item_is_missing():
    original = {"activity": "walking", "restrictions": ["no stairs"]}
    generated = {"activity": "walking", "restrictions": []}

    diffs = compare_facts(InstructionType.MOBILITY, original, generated)

    assert any(d.field == "restrictions" and d.type == "MISSING" and d.source == "no stairs" for d in diffs)


def test_list_field_added_item_is_added():
    original = {"activity": "walking", "restrictions": []}
    generated = {"activity": "walking", "restrictions": ["use a cane"]}

    diffs = compare_facts(InstructionType.MOBILITY, original, generated)

    assert any(d.field == "restrictions" and d.type == "ADDED" and d.generated == "use a cane" for d in diffs)


# ---------------------------------------------------------------------------
# Layer A: raw-text scans
# ---------------------------------------------------------------------------


def test_scan_for_preserved_dose_finds_exact_number():
    assert scan_for_preserved_dose({"dose_value": 25.0}, "Take Metoprolol 25 mg by mouth.") is True


def test_scan_for_preserved_dose_fails_when_number_absent():
    assert scan_for_preserved_dose({"dose_value": 25.0}, "Take Metoprolol by mouth.") is False


def test_scan_for_preserved_dose_fails_when_number_changed():
    assert scan_for_preserved_dose({"dose_value": 25.0}, "Take Metoprolol 50 mg by mouth.") is False


def test_scan_for_preserved_dose_true_when_no_dose_in_source():
    assert scan_for_preserved_dose({"dose_value": None}, "Walk after meals.") is True


def test_scan_for_preserved_warnings_all_present():
    facts = {"warnings": ["Avoid grapefruit juice"]}
    assert scan_for_preserved_warnings(facts, "Take it. Avoid grapefruit juice.") == []


def test_scan_for_preserved_warnings_reports_missing_ones():
    facts = {"warnings": ["Avoid grapefruit juice", "Do not drive"]}
    missing = scan_for_preserved_warnings(facts, "Take it with food.")
    assert set(missing) == {"Avoid grapefruit juice", "Do not drive"}


def test_scan_for_preserved_warnings_is_case_insensitive():
    facts = {"warnings": ["Avoid Grapefruit Juice"]}
    assert scan_for_preserved_warnings(facts, "avoid grapefruit juice today") == []


def test_scan_for_preserved_warnings_allows_faithful_rewording():
    # Real case from manual testing: "maximum 4,000 mg in 24 hours" rendered
    # as "Do not take more than 4,000 mg in 24 hours" — same numbers, same
    # meaning, different connecting words. Exact substring matching used to
    # flag this as a dropped safety warning.
    facts = {"warnings": ["maximum 4,000 mg in 24 hours"]}
    generated = "Take paracetamol 1000 mg by mouth every 6 hours as needed. Do not take more than 4,000 mg in 24 hours."
    assert scan_for_preserved_warnings(facts, generated) == []


def test_scan_for_preserved_warnings_still_catches_changed_number():
    facts = {"warnings": ["maximum 4,000 mg in 24 hours"]}
    generated = "Do not take more than 3,000 mg in 24 hours."
    missing = scan_for_preserved_warnings(facts, generated)
    assert missing == ["maximum 4,000 mg in 24 hours"]


def test_scan_for_preserved_warnings_still_catches_fully_dropped_warning():
    facts = {"warnings": ["Do not drive after taking this medication"]}
    generated = "Take paracetamol 1000 mg by mouth every 6 hours as needed."
    missing = scan_for_preserved_warnings(facts, generated)
    assert missing == ["Do not drive after taking this medication"]


# ---------------------------------------------------------------------------
# validate_fact_preservation — the full orchestration
# ---------------------------------------------------------------------------


def test_validate_passes_when_everything_preserved():
    original = _medication_facts()
    result = validate_fact_preservation(
        InstructionType.MEDICATION,
        original,
        "Take Metoprolol 25 mg by mouth twice daily. Take it with food.",
        InstructionType.MEDICATION,
        dict(original),
        [],
    )
    assert result.passed is True
    assert result.differences == []


def test_validate_fails_when_dose_changed():
    original = _medication_facts(dose_value=25.0)
    generated_facts = _medication_facts(dose_value=50.0)
    result = validate_fact_preservation(
        InstructionType.MEDICATION,
        original,
        "Take Metoprolol 50 mg by mouth twice daily.",
        InstructionType.MEDICATION,
        generated_facts,
        [],
    )
    assert result.passed is False
    assert any(d.field == "dose_value" for d in result.differences)
    assert any("dose_value" in m for m in result.messages)


def test_validate_fails_when_reextraction_itself_failed():
    """If the generated text can't even be re-extracted, that's unsafe — never
    treated as "no differences found."."""
    original = _medication_facts()
    result = validate_fact_preservation(
        InstructionType.MEDICATION, original, "some garbled output", None, None, None
    )
    assert result.passed is False
    assert any(d.type == "AMBIGUOUS" for d in result.differences)


def test_validate_fails_when_regenerated_type_differs():
    original = _medication_facts()
    result = validate_fact_preservation(
        InstructionType.MEDICATION,
        original,
        "Walk for 10 minutes after meals.",
        InstructionType.MOBILITY,
        {"activity": "walking"},
        [],
    )
    assert result.passed is False
    assert any(d.field == "instruction_type" for d in result.differences)


def test_validate_fails_on_ambiguous_regenerated_field():
    original = _medication_facts()
    result = validate_fact_preservation(
        InstructionType.MEDICATION,
        original,
        "Take Metoprolol some amount by mouth twice daily.",
        InstructionType.MEDICATION,
        dict(original),
        ["dose_value"],
    )
    assert result.passed is False
    assert any(d.field == "dose_value" and d.type == "AMBIGUOUS" for d in result.differences)


def test_validate_fails_when_warning_dropped_even_if_structured_diff_matches():
    """Layer A catches this independently of Layer B — regenerated_facts can
    "match" (e.g. because the mock's extraction never parses free-text warnings)
    while the warning is still verifiably missing from the actual text."""
    original = _medication_facts(warnings=["Avoid grapefruit juice"])
    generated_facts = _medication_facts()  # no warnings key at all, as if never extracted
    result = validate_fact_preservation(
        InstructionType.MEDICATION,
        original,
        "Take Metoprolol 25 mg by mouth twice daily.",
        InstructionType.MEDICATION,
        generated_facts,
        [],
    )
    assert result.passed is False
    assert any(d.field == "warnings" for d in result.differences)
