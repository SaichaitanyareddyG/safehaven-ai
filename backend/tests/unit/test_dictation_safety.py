"""Unit tests for the deterministic dictation-safety scan (see
app/validation/dictation_safety.py) — ISMP error-prone dose designations,
flagged on a dictated transcript because no downstream validator can catch a
transcription error (the transcript IS the source they all validate against).

Advisory only: nothing here blocks submission, and no empty result means
"verified correct"."""

from app.validation.dictation_safety import check_dictation


def _codes(text: str) -> list[str]:
    return [w.code for w in check_dictation(text)]


def test_clean_transcript_produces_no_warnings():
    assert check_dictation("Take Metoprolol Succinate ER 25 mg orally twice daily.") == []


def test_empty_text_produces_no_warnings():
    assert check_dictation("") == []
    assert check_dictation("   ") == []


def test_trailing_zero_is_flagged():
    warnings = check_dictation("Take Metoprolol 25.0 mg orally twice daily.")
    assert [w.code for w in warnings] == ["TRAILING_ZERO"]
    assert "25.0" in warnings[0].message
    assert "25.0" in warnings[0].excerpt


def test_naked_decimal_is_flagged():
    warnings = check_dictation("Take Digoxin .25 mg orally once daily.")
    assert "NAKED_DECIMAL" in [w.code for w in warnings]
    assert "0.25" in next(w.message for w in warnings if w.code == "NAKED_DECIMAL")


def test_leading_zero_decimal_is_not_flagged():
    """0.25 mg is the CORRECT form — flagging it would train clinicians to
    ignore the warnings."""
    assert "NAKED_DECIMAL" not in _codes("Take Digoxin 0.25 mg orally once daily.")


def test_mcg_is_flagged_for_mg_confusion():
    assert "MCG_MG_CONFUSION" in _codes("Take Levothyroxine 50 mcg orally once daily.")


def test_plain_mg_is_not_flagged_for_mcg_confusion():
    assert "MCG_MG_CONFUSION" not in _codes("Take Levothyroxine 50 mg orally once daily.")


def test_unit_abbreviation_is_flagged():
    assert "UNIT_ABBREVIATION" in _codes("Give 10U of insulin subcutaneously.")
    assert "UNIT_ABBREVIATION" in _codes("Give 4 IU subcutaneously.")


def test_units_written_in_full_is_not_flagged():
    assert "UNIT_ABBREVIATION" not in _codes("Give 10 units of insulin subcutaneously.")


def test_error_prone_frequency_abbreviations_are_flagged():
    for abbreviation in ("QD", "QOD", "QID", "BID", "TID", "HS"):
        assert "FREQUENCY_ABBREVIATION" in _codes(f"Take Metoprolol 25 mg {abbreviation}."), abbreviation


def test_frequency_written_in_words_is_not_flagged():
    assert "FREQUENCY_ABBREVIATION" not in _codes("Take Metoprolol 25 mg twice daily.")


def test_medication_shaped_text_with_no_dose_is_flagged():
    assert "NO_DOSE_DETECTED" in _codes("Take Metoprolol orally twice daily.")


def test_non_medication_instruction_is_not_nagged_about_a_missing_dose():
    """A mobility or diet instruction legitimately has no dose."""
    assert "NO_DOSE_DETECTED" not in _codes("Walk to the bathroom with your nurse for the first two days.")


def test_multiple_problems_are_all_reported():
    codes = _codes("Give 10U of insulin QD, and Digoxin .25 mg.")
    assert "UNIT_ABBREVIATION" in codes
    assert "FREQUENCY_ABBREVIATION" in codes
    assert "NAKED_DECIMAL" in codes
