"""Unit tests for the deterministic Flesch-Kincaid grade-level scorer (see
app/validation/readability.py) — informational reading-level signal shown to
the clinician approving generated patient text, never a pass/fail gate."""

from app.validation.readability import flesch_kincaid_grade_level


def test_empty_text_returns_none():
    assert flesch_kincaid_grade_level("") is None
    assert flesch_kincaid_grade_level(None) is None


def test_simple_short_sentences_score_low():
    text = "Take one pill. Drink water. Call your doctor if you feel sick."
    grade = flesch_kincaid_grade_level(text)
    assert grade is not None
    assert grade <= 6.0


def test_complex_long_sentence_scores_higher_than_simple_text():
    simple = "Take one pill each day."
    complex_text = (
        "The administration of this pharmaceutical preparation necessitates careful consideration "
        "of the patient's concurrent medications, comorbidities, and individualized physiological "
        "characteristics prior to initiation of the prescribed therapeutic regimen."
    )
    assert flesch_kincaid_grade_level(complex_text) > flesch_kincaid_grade_level(simple)


def test_score_never_negative():
    # A single short word/sentence shouldn't produce a negative grade level.
    assert flesch_kincaid_grade_level("Okay.") >= 0.0


def test_realistic_patient_text_example():
    text = (
        "Take Lisinopril 10 mg by mouth once a day. This medicine helps control your blood "
        "pressure. Take it at the same time each day, with or without food."
    )
    grade = flesch_kincaid_grade_level(text)
    assert grade is not None
    assert 0 < grade < 12  # sane bound — not an exact target, just plausibility
