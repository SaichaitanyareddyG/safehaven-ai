"""Dose schedules from approved medication facts. The rule under test: a
schedule is produced only when the facts say exactly when; anything else is
NEEDS_REVIEW (no reminders), never a guess."""

from datetime import date, time

import pytest

from app.schedules.dose_schedule import derive_schedule


def facts(frequency=None, timing=None, duration=None, with_food=None, dose_value=25, dose_unit="mg"):
    return {
        "medication_name": "Metoprolol",
        "dose_value": dose_value,
        "dose_unit": dose_unit,
        "frequency": frequency,
        "timing": timing,
        "duration": duration,
        "with_food": with_food,
    }


def hhmm(schedule):
    return [t.strftime("%H:%M") for t in schedule.times]


@pytest.mark.parametrize(
    ("frequency", "timing", "expected"),
    [
        ("once daily", None, ["08:00"]),
        ("daily", None, ["08:00"]),
        ("twice daily", None, ["08:00", "20:00"]),
        ("BID", None, ["08:00", "20:00"]),
        ("twice a day", None, ["08:00", "20:00"]),
        ("three times daily", None, ["08:00", "14:00", "20:00"]),
        ("tid", None, ["08:00", "14:00", "20:00"]),
        ("four times a day", None, ["08:00", "12:00", "16:00", "20:00"]),
        ("once daily", "in the morning", ["08:00"]),
        ("once daily", "at bedtime", ["22:00"]),
        ("once daily", "in the evening", ["20:00"]),
        ("once daily", "with breakfast", ["08:00"]),
        ("morning and evening", None, ["08:00", "20:00"]),
        ("twice daily", "in the morning and at night", ["08:00", "22:00"]),
        ("twice daily", "with breakfast and dinner", ["08:00", "18:00"]),
        ("every 8 hours", None, ["06:00", "14:00", "22:00"]),
        ("every 6 hours", None, ["00:00", "06:00", "12:00", "18:00"]),
        ("every 12 hours", None, ["08:00", "20:00"]),
        ("q8h", None, ["06:00", "14:00", "22:00"]),
        (None, "every morning", ["08:00"]),
    ],
)
def test_daily_patterns_become_fixed_times(frequency, timing, expected):
    schedule = derive_schedule(facts(frequency, timing))
    assert schedule.kind == "SCHEDULED", schedule.problem
    assert hhmm(schedule) == expected


@pytest.mark.parametrize(
    ("frequency", "timing", "raw"),
    [
        ("every 6 hours as needed", None, None),
        ("PRN", None, None),
        ("every 6 hours", None, "Take paracetamol 500 mg every 6 hours as needed for pain."),
        ("twice daily", "if needed for nausea", None),
    ],
)
def test_as_needed_never_gets_reminders(frequency, timing, raw):
    schedule = derive_schedule(facts(frequency, timing), raw)
    assert schedule.kind == "AS_NEEDED" and schedule.times == []


@pytest.mark.parametrize(
    ("frequency", "timing", "duration"),
    [
        ("every other day", None, None),
        ("once weekly", None, None),
        ("three times a week", None, None),
        ("every 3 days", None, None),
        ("once", None, None),  # could be a single dose
        ("stat", None, None),
        ("every 5 hours", None, None),
        ("twice daily", "at bedtime", None),  # two doses, one time given
        ("once daily", "morning and evening", None),
        ("every 8 hours", "in the morning", None),
        ("nightly-ish whenever", None, None),
        (None, None, None),
        ("twice daily", None, "until finished"),
        ("twice daily", None, "until the swelling goes down"),
        ("twice daily", None, "for 400 days"),
    ],
)
def test_anything_unclear_gets_no_reminders(frequency, timing, duration):
    schedule = derive_schedule(facts(frequency, timing, duration))
    assert schedule.kind == "NEEDS_REVIEW"
    assert schedule.times == [] and schedule.problem


@pytest.mark.parametrize(
    ("duration", "days"),
    [
        (None, None),
        ("for 7 days", 7),
        ("7 days", 7),
        ("for seven days", 7),
        ("x5 days", 5),
        ("for 2 weeks", 14),
        ("for a week", 7),
        ("for the next 3 days", 3),
        ("ongoing", None),
        ("long-term", None),
    ],
)
def test_course_length(duration, days):
    schedule = derive_schedule(facts("twice daily", duration=duration))
    assert schedule.kind == "SCHEDULED" and schedule.duration_days == days


def test_end_date_counts_the_start_day():
    schedule = derive_schedule(facts("twice daily", duration="for 7 days"))
    assert schedule.end_date(date(2026, 10, 17)) == date(2026, 10, 23)
    assert derive_schedule(facts("twice daily")).end_date(date(2026, 10, 17)) is None


def test_summary_and_dose():
    schedule = derive_schedule(facts("twice daily", duration="for 7 days", with_food=True))
    assert schedule.dose == "25 mg"
    assert schedule.summary() == "8:00 AM and 8:00 PM, with food, for 7 days"
    assert derive_schedule(facts("once daily", "at bedtime", dose_value=12.5)).dose == "12.5 mg"


def test_standard_times_match_the_bedside_time_check():
    """The patient's reminder and Module 2's on-time check use the same clock."""
    from app.medication_verification.service import _TIME_OF_DAY_KEYWORDS

    for word, expected in _TIME_OF_DAY_KEYWORDS.items():
        schedule = derive_schedule(facts("once daily", f"in the {word}"))
        assert schedule.times == [expected], word
    assert time(8, 0) in derive_schedule(facts("once daily")).times
