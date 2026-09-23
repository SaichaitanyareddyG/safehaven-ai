"""Unit tests for the pure, deterministic comparison functions in
app/medication_verification/service.py — no DB, no HTTP, no LLM. See
MODULE_2_DESIGN_REPORT.md section 8 for the rules being tested."""

from datetime import datetime, timezone

import pytest

from app.medication_verification.service import (
    _check_dose,
    _check_formulation,
    _check_route,
    _check_time,
    _drug_family_matches,
)
from app.reference.medication_products import MEDICATION_PRODUCTS


@pytest.fixture
def utc_hospital(monkeypatch):
    """Pins the hospital clock to UTC for tests that assert on specific times.

    Without this these tests silently depend on whatever HOSPITAL_TIMEZONE the
    local .env happens to carry — which is exactly how the original UTC
    assumption stayed invisible: the tests passed because the deployment
    config and the test expectations shared the same unstated assumption."""
    from app.core.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("HOSPITAL_TIMEZONE", "UTC")
    yield
    get_settings.cache_clear()


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


def test_time_within_tolerance_passes(utc_hospital):
    facts = {"timing": "in the morning", "frequency": "once daily"}
    now = datetime(2026, 1, 1, 8, 30, tzinfo=timezone.utc)  # 30 min after 08:00
    result = _check_time(facts, now)
    assert result.passed is True


def test_time_outside_tolerance_fails(utc_hospital):
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


# ---------------------------------------------------------------------------
# Timezone-aware administration timing. "In the morning" is a wall-clock
# instruction and must be compared against the HOSPITAL's clock — comparing it
# against UTC warned on every correct morning dose outside a UTC±0 hospital.
# ---------------------------------------------------------------------------


def test_morning_dose_at_local_morning_passes_in_a_non_utc_hospital(monkeypatch):
    from datetime import datetime, timezone

    from app.core.config import Settings, get_settings
    from app.medication_verification.service import _check_time

    get_settings.cache_clear()
    monkeypatch.setenv("HOSPITAL_TIMEZONE", "Asia/Kolkata")
    try:
        # 02:30 UTC == 08:00 in Kolkata: exactly on schedule for the nurse.
        check = _check_time(
            {"timing": "in the morning", "frequency": "once daily"},
            datetime(2026, 9, 15, 2, 30, tzinfo=timezone.utc),
        )
        assert check.passed is True
        assert "Asia/Kolkata" in check.detail
    finally:
        get_settings.cache_clear()


def test_morning_dose_given_in_the_local_afternoon_still_warns(monkeypatch):
    from datetime import datetime, timezone

    from app.core.config import get_settings
    from app.medication_verification.service import _check_time

    get_settings.cache_clear()
    monkeypatch.setenv("HOSPITAL_TIMEZONE", "Asia/Kolkata")
    try:
        # 08:30 UTC == 14:00 in Kolkata — genuinely off-schedule.
        check = _check_time(
            {"timing": "in the morning", "frequency": "once daily"},
            datetime(2026, 9, 15, 8, 30, tzinfo=timezone.utc),
        )
        assert check.passed is False
        assert "14:00" in check.detail  # tells the nurse the local time it thinks it is
    finally:
        get_settings.cache_clear()


def test_invalid_hospital_timezone_is_rejected_at_config_load(monkeypatch):
    import pytest

    from app.core.config import Settings

    with pytest.raises(Exception):
        Settings(hospital_timezone="Not/AZone")


# ---------------------------------------------------------------------------
# Allergen matching must not turn a typo into an ALLERGY ALERT.
# ---------------------------------------------------------------------------


def test_allergen_matches_same_drug_and_drug_family():
    from app.medication_verification.service import _allergen_matches

    assert _allergen_matches("Metoprolol", "metoprolol") is True
    assert _allergen_matches("metoprolol tartrate", "metoprolol") is True
    assert _allergen_matches("  MetoproLOL  ", "metoprolol") is True


def test_allergen_does_not_match_an_unrelated_drug():
    from app.medication_verification.service import _allergen_matches

    assert _allergen_matches("Penicillin", "metoprolol") is False


def test_short_allergen_entries_do_not_block_unrelated_drugs():
    """A stray keystroke saved as an allergy used to block real medications
    outright, presented as an ALLERGY ALERT indistinguishable from a real
    one."""
    from app.medication_verification.service import _allergen_matches

    assert _allergen_matches("o", "metoprolol") is False
    assert _allergen_matches("in", "lisinopril") is False
    assert _allergen_matches("ol", "metoprolol") is False
    assert _allergen_matches("", "metoprolol") is False


def test_short_allergen_still_matches_itself_exactly():
    """Withdrawing substring matching for short entries must not silently drop
    a genuine short allergen."""
    from app.medication_verification.service import _allergen_matches

    assert _allergen_matches("ASA", "asa") is True


# ---------------------------------------------------------------------------
# PRN detection. These pin the shape the PRODUCTION model actually returns,
# not the shape the mock provider happens to produce — the original
# implementation read only the structured frequency/timing fields and so
# never detected PRN outside the test double.
# ---------------------------------------------------------------------------


def test_prn_detected_from_raw_text_when_extraction_drops_it():
    """The real extraction of "every 6 hours as needed for pain" returns
    frequency='every 6 hours', timing=None and no PRN marker anywhere in the
    structured facts. The order text is the only surviving evidence."""
    from app.medication_verification.service import _order_is_prn

    facts = {"frequency": "every 6 hours", "timing": None, "reason": "for pain"}
    assert _order_is_prn(facts, "Take Paracetamol 500 mg orally every 6 hours as needed for pain.") is True


def test_prn_detected_from_structured_frequency_when_present():
    from app.medication_verification.service import _order_is_prn

    assert _order_is_prn({"frequency": "as needed", "timing": None}, None) is True


def test_prn_markers_are_case_insensitive():
    from app.medication_verification.service import _order_is_prn

    assert _order_is_prn({}, "Take Paracetamol 500 mg PRN for pain.") is True


def test_scheduled_order_is_not_prn():
    from app.medication_verification.service import _order_is_prn

    facts = {"frequency": "twice daily", "timing": "in the morning"}
    assert _order_is_prn(facts, "Take Metoprolol Succinate ER 25 mg orally twice daily.") is False
