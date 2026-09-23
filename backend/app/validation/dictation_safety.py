"""Deterministic safety scan of a dictated transcript, before a clinician
submits it as a clinical instruction.

This exists because of a structural gap, not a nice-to-have: every other AI
output in this codebase has a deterministic validator behind it
(fact_preservation.py re-extracts and diffs generated text;
translation_preservation.py does the same for translations; Module 2 compares
scans against structured order facts). A transcript cannot have one. It
*becomes* InstructionVersion.raw_text — the source of truth every one of those
validators checks against — so a mis-heard dose is invisible to all of them:
each would faithfully confirm fidelity to the corrupted source. See
MODULE_1_VOICE_DICTATION_DESIGN.md section 3.

So the only useful place to add a check is on the transcript itself. The
patterns below come from ISMP's published "Error-Prone Abbreviations, Symbols,
and Dose Designations" list, filtered to the entries that are specifically
*speech*-confusion or transcription failures — which is exactly the risk
dictation introduces and typing does not.

Advisory only, never blocking — same treatment as the Flesch-Kincaid reading
score (see PatientOutput.reading_grade_level). These are "look at this line
again" nudges on a draft the clinician is about to edit anyway, and a flagged
transcript can be perfectly correct (a real 0.5 mg order legitimately contains
a decimal). Nothing here decides anything; it only points.
"""

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class DictationWarning:
    code: str
    message: str
    excerpt: str


# Trailing zero after a decimal point: "5.0 mg". If the decimal point is lost
# (misread, poor print, a stray mark), 5.0 becomes 50 — a 10x overdose. ISMP's
# rule is to never write a trailing zero after a decimal.
_TRAILING_ZERO_RE = re.compile(r"\b(\d+\.0+)\s*(mg|mcg|g|ml|units?)\b", re.IGNORECASE)

# "Naked" decimal: ".5 mg" with no leading zero. If the point is missed, .5
# becomes 5 — again 10x. ISMP's rule is to always write a leading zero.
_NAKED_DECIMAL_RE = re.compile(r"(?<![\d.])\.(\d+)\s*(mg|mcg|g|ml|units?)\b", re.IGNORECASE)

# mg vs mcg — a 1000x difference, and near-indistinguishable when spoken
# quickly ("em-gee" / "em-see-gee"). Flagged whenever mcg appears at all,
# since the failure is that the dictation was heard as the *other* one.
_MCG_RE = re.compile(r"\b\d+(?:\.\d+)?\s*mcg\b", re.IGNORECASE)

# "U" or "IU" for units: ISMP's most-cited abbreviation error — "10U" reads as
# "100", "4U" as "44". Must be written out as "units".
_UNIT_ABBREV_RE = re.compile(r"\b\d+(?:\.\d+)?\s*(IU|U)\b")

# Sound-alike/look-alike frequency abbreviations. QD (daily) vs QOD (every
# other day) vs QID (four times daily) are routinely confused for each other.
_FREQUENCY_ABBREV_RE = re.compile(r"\b(QD|QOD|QID|BID|TID|HS)\b", re.IGNORECASE)

# Does the text look like a medication order at all? Used only to decide
# whether a *missing* dose is worth mentioning — a mobility or diet
# instruction has no dose and shouldn't be nagged about one.
_MEDICATION_SHAPED_RE = re.compile(r"\b(take|give|administer|tablet|capsule|injection|dose)\b", re.IGNORECASE)
_ANY_DOSE_RE = re.compile(r"\b\d+(?:\.\d+)?\s*(mg|mcg|g|ml|units?|tablets?|capsules?)\b", re.IGNORECASE)


def _excerpt(text: str, match: re.Match) -> str:
    """A small window around the match, so the UI can show *where* without
    re-highlighting the whole transcript."""
    start = max(0, match.start() - 20)
    end = min(len(text), match.end() + 20)
    return ("…" if start > 0 else "") + text[start:end].strip() + ("…" if end < len(text) else "")


def check_dictation(text: str) -> list[DictationWarning]:
    """Returns every applicable warning, most-dangerous-first. An empty list
    means nothing matched — NOT that the transcript is verified correct. No
    check here can confirm the transcript says what the clinician said; only
    the clinician can."""
    if not text or not text.strip():
        return []

    warnings: list[DictationWarning] = []

    for match in _TRAILING_ZERO_RE.finditer(text):
        warnings.append(
            DictationWarning(
                code="TRAILING_ZERO",
                message=(
                    f"'{match.group(1)}' has a trailing zero — if the decimal point is missed this reads as a "
                    f"10x larger dose. Write it without the trailing zero."
                ),
                excerpt=_excerpt(text, match),
            )
        )

    for match in _NAKED_DECIMAL_RE.finditer(text):
        warnings.append(
            DictationWarning(
                code="NAKED_DECIMAL",
                message=(
                    f"'.{match.group(1)}' has no leading zero — if the decimal point is missed this reads as a "
                    f"10x larger dose. Write it as '0.{match.group(1)}'."
                ),
                excerpt=_excerpt(text, match),
            )
        )

    for match in _UNIT_ABBREV_RE.finditer(text):
        warnings.append(
            DictationWarning(
                code="UNIT_ABBREVIATION",
                message=(
                    f"'{match.group(1)}' for units can be misread as a digit (e.g. 10U as 100). "
                    f"Write 'units' in full."
                ),
                excerpt=_excerpt(text, match),
            )
        )

    for match in _MCG_RE.finditer(text):
        warnings.append(
            DictationWarning(
                code="MCG_MG_CONFUSION",
                message="Confirm this is mcg and not mg — they sound alike when spoken and differ by 1000x.",
                excerpt=_excerpt(text, match),
            )
        )

    for match in _FREQUENCY_ABBREV_RE.finditer(text):
        warnings.append(
            DictationWarning(
                code="FREQUENCY_ABBREVIATION",
                message=(
                    f"'{match.group(1)}' is an error-prone frequency abbreviation (QD/QOD/QID are easily "
                    f"confused). Write the frequency in words."
                ),
                excerpt=_excerpt(text, match),
            )
        )

    if _MEDICATION_SHAPED_RE.search(text) and not _ANY_DOSE_RE.search(text):
        warnings.append(
            DictationWarning(
                code="NO_DOSE_DETECTED",
                message="This looks like a medication instruction but no dose was detected — confirm nothing was missed.",
                excerpt=text[:60].strip() + ("…" if len(text) > 60 else ""),
            )
        )

    return warnings
