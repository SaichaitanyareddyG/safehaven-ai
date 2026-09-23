"""Deterministic reading-level scoring for AI-generated patient-facing text.

AMA/CDC guidance targets roughly a 5th-6th grade reading level for patient
education materials. This computes the standard Flesch-Kincaid Grade Level
formula (words/sentence and syllables/word — a well-established, purely
arithmetic readability metric, not an LLM judgment call) so a clinician
reviewing generated text has a concrete, comparable number, the same spirit
as this codebase's other deterministic checks (fact_preservation.py,
medication_verification's dose/route comparisons).

Deliberately informational only — see PatientOutput.reading_grade_level's
docstring for why this is never a pass/fail gate the way fact-preservation
is: a higher score can be entirely legitimate (a long medication name raises
syllable count without making the sentence actually harder to follow), so
this is surfaced to the approving clinician's own judgment, never used to
silently block or rewrite content.
"""

import re

_SENTENCE_END_RE = re.compile(r"[.!?]+")
_WORD_RE = re.compile(r"[A-Za-z']+")
_VOWEL_GROUP_RE = re.compile(r"[aeiouy]+")


def _count_syllables(word: str) -> int:
    """A standard heuristic (vowel-group counting, with a silent trailing
    'e' correction) — not phonetically perfect, but accurate enough for a
    grade-level estimate, and the same approach used by most lightweight
    readability tools."""
    word = word.lower()
    groups = _VOWEL_GROUP_RE.findall(word)
    count = len(groups)
    if word.endswith("e") and count > 1:
        count -= 1
    return max(count, 1)


def flesch_kincaid_grade_level(text: str) -> float | None:
    """Returns None only when there's no scorable text at all (empty string,
    or no recognizable words/sentences) — never a fabricated 0.0, which
    would misleadingly read as "very easy" rather than "not measured"."""
    words = _WORD_RE.findall(text or "")
    sentences = [s for s in _SENTENCE_END_RE.split(text or "") if s.strip()]
    if not words or not sentences:
        return None

    syllables = sum(_count_syllables(w) for w in words)
    words_count = len(words)
    sentences_count = len(sentences)

    grade = 0.39 * (words_count / sentences_count) + 11.8 * (syllables / words_count) - 15.59
    return round(max(grade, 0.0), 1)
