"""Unit tests for the pure, deterministic comparison functions in
app/medication_verification/service.py — no DB, no HTTP, no LLM. See
MODULE_2_DESIGN_REPORT.md section 8 for the rules being tested."""

from datetime import datetime, timezone

from app.medication_verification.service import (
    _check_dose,
    _check_formulation,
    _check_route,
    _check_time,
    _drug_family_matches,
)
from app.reference.medication_products import MEDICATION_PRODUCTS


SUCCINATE_25 = MEDICATION_PRODUCTS["MED-METOPROLOL-SUCCINATE-25"]
SUCCINATE_50 = MEDICATION_PRODUCTS["MED-METOPROLOL-SUCCINATE-50"]
TARTRATE_25 = MEDICATION_PRODUCTS["MED-METOPROLOL-TARTRATE-25"]
LISINOPRIL_10 = MEDICATION_PRODUCTS["MED-LISINOPRIL-10"]


def test_drug_family_matches_base_name_only():
    assert _drug_family_matches("Metoprolol", "Metoprolol Succinate ER")
    assert _drug_family_matches("Metoprolol Succinate ER", "Metoprolol Succinate ER")


def test_drug_family_does_not_match_different_drug():
    assert not _drug_family_matches("Lisinopril", "Metoprolol Succinate ER")


def test_drug_family_no_order_name_never_matches():
    assert not _drug_family_matches(None, "Metoprolol Succinate ER")
    assert not _drug_family_matches("", "Metoprolol Succinate ER")


def test_dose_exact_match_passes():
    facts = {"dose_value": 25.0, "dose_unit": "mg"}
    result = _check_dose(facts, SUCCINATE_25)
    assert result.passed is True


def test_dose_mismatch_fails():
    facts = {"dose_value": 25.0, "dose_unit": "mg"}
    result = _check_dose(facts, SUCCINATE_50)
    assert result.passed is False


def test_dose_missing_on_order_fails_never_guesses():
    result = _check_dose({"dose_value": None, "dose_unit": None}, SUCCINATE_25)
    assert result.passed is False


def test_route_match_case_insensitive():
    result = _check_route({"route": "Oral"}, SUCCINATE_25)
    assert result.passed is True


def test_route_mismatch_fails():
    result = _check_route({"route": "topical"}, SUCCINATE_25)
    assert result.passed is False


def test_formulation_consistent_when_order_specifies_succinate():
    check, ambiguous = _check_formulation("Metoprolol Succinate ER", SUCCINATE_25)
    assert check.passed is True
    assert ambiguous is False


def test_formulation_contradicted_when_order_specifies_opposite_salt_form():
    check, ambiguous = _check_formulation("Metoprolol Succinate ER", TARTRATE_25)
    assert check.passed is False
    assert ambiguous is False


def test_formulation_ambiguous_when_order_does_not_specify():
    check, ambiguous = _check_formulation("Metoprolol", SUCCINATE_25)
    assert check.passed is False
    assert ambiguous is True


def test_formulation_ambiguous_is_distinct_from_contradicted():
    """The whole point of this distinction: an order that never documented a
    formulation is a data-quality gap (REVIEW_REQUIRED upstream), never
    treated as if it were a detected mismatch (BLOCKED upstream)."""
    ambiguous_check, is_ambiguous = _check_formulation("Metoprolol", SUCCINATE_25)
    contradicted_check, is_contradicted_ambiguous = _check_formulation("Metoprolol Tartrate", SUCCINATE_25)
    assert ambiguous_check.passed is False and is_ambiguous is True
    assert contradicted_check.passed is False and is_contradicted_ambiguous is False


def test_time_within_tolerance_passes():
    facts = {"timing": "in the morning", "frequency": "once daily"}
    now = datetime(2026, 1, 1, 8, 30, tzinfo=timezone.utc)  # 30 min after 08:00
    result = _check_time(facts, now)
    assert result.passed is True


def test_time_outside_tolerance_fails():
    facts = {"timing": "in the morning", "frequency": "once daily"}
    now = datetime(2026, 1, 1, 11, 0, tzinfo=timezone.utc)  # 3 hours after 08:00
    result = _check_time(facts, now)
    assert result.passed is False


def test_time_with_no_documented_schedule_is_skipped_not_penalized():
    facts = {"timing": None, "frequency": "twice daily"}
    now = datetime(2026, 1, 1, 23, 0, tzinfo=timezone.utc)
    result = _check_time(facts, now)
    assert result.passed is True


def test_lisinopril_single_product_product_identity_sanity():
    assert LISINOPRIL_10.medication_name == "Lisinopril"
