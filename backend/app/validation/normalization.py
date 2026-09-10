"""Deterministic, conservative normalization applied before completeness checks.

Only surface-level cleanup of strings the LLM already extracted — casing,
whitespace, and a small set of well-known clinical abbreviations. Never touches
numeric values (dose amounts, durations) and never invents or drops a field.
Keeping this intentionally small: a full clinical terminology engine is out of
scope for a prototype.
"""

import re
from dataclasses import dataclass

from app.instructions.models import InstructionType

_DOSE_UNIT_MAP = {"mg": "mg", "mcg": "mcg", "g": "g", "ml": "ml"}

_ROUTE_MAP = {
    "po": "oral",
    "orally": "oral",
    "oral": "oral",
    # "by mouth" is the plain-language phrasing our OWN generation prompt asks
    # for (see prompts.py's GENERATION_SYSTEM_PROMPT: "avoid medical jargon
    # where a common word works") — Step 10 real-model evaluation showed the
    # fact-preservation validator was blocking this safe, faithful paraphrase
    # as a "changed" route on nearly every medication case, in both directions
    # (generation and back-translation). Recognizing it here is the same fix
    # already applied for "po"/"orally", not a loosening of what still counts
    # as a genuine route change (e.g. oral -> topical still fails).
    "by mouth": "oral",
    "topically": "topical",
    "topical": "topical",
    "iv": "intravenous",
    "intravenous": "intravenous",
}

_FREQUENCY_MAP = {
    "bid": "twice daily",
    "b.i.d.": "twice daily",
    "twice daily": "twice daily",
    "twice a day": "twice daily",
    "qd": "once daily",
    "od": "once daily",
    "once daily": "once daily",
    "once a day": "once daily",
    "daily": "once daily",
    "tid": "three times daily",
    "t.i.d.": "three times daily",
    "three times daily": "three times daily",
    "three times a day": "three times daily",
}


# Real translation-validation runs (back-translate -> re-extract -> compare,
# see validation/translation_preservation.py) repeatedly showed the same
# once-per-day cadence landing differently across the frequency/timing
# boundary depending on re-extraction — "once daily" + "in the morning"
# coming back as frequency="once every morning" (timing empty), or
# frequency="once" + timing="every morning", or timing="every morning" alone
# with frequency empty. Not a different clinical fact each time, just where
# re-extraction drew the field line — see _split_once_daily_from_timing.
_TIME_OF_DAY_RE = re.compile(r"\b(morning|night|evening|afternoon|noon|bedtime)\b", re.IGNORECASE)
_ONCE_OR_DAILY_RE = re.compile(r"\bonce\b|\bdaily\b", re.IGNORECASE)
# Deliberately broad exclusion guard: if ANY of these appear, this is not a
# plain "once per day" cadence and must never be touched — a genuinely
# different interval (twice daily, every 6 hours, every other day, weekly,
# PRN) must keep comparing exactly as before, not get silently folded into
# "once daily".
_NOT_PLAIN_ONCE_DAILY_RE = re.compile(
    r"\btwice\b|\bthree times\b|\bfour times\b|\bevery\s+\d+\s*(hour|hr|day|week)s?\b"
    r"|\bevery other\b|\balternate\b|\bweekly\b|\bmonthly\b|\bas needed\b|\bprn\b|\btid\b|\bbid\b|\bqid\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class NormalizationChange:
    field: str
    source_value: object
    normalized_value: object


def _split_once_daily_from_timing(facts: dict) -> tuple[dict, NormalizationChange | None]:
    frequency = facts.get("frequency")
    timing = facts.get("timing")
    frequency_text = frequency if isinstance(frequency, str) else ""
    timing_text = timing if isinstance(timing, str) else ""
    combined = f"{frequency_text} {timing_text}".strip()
    if not combined:
        return facts, None

    if _NOT_PLAIN_ONCE_DAILY_RE.search(combined):
        return facts, None

    time_match = _TIME_OF_DAY_RE.search(combined)
    if time_match is None:
        return facts, None

    # frequency must be empty, or itself already say "once"/"daily" — if it
    # says something else entirely (and wasn't already caught by the
    # exclusion guard above), stay conservative and leave it alone rather
    # than risk reclassifying an unrecognized pattern.
    if frequency_text.strip() and not _ONCE_OR_DAILY_RE.search(frequency_text):
        return facts, None

    new_frequency = "once daily"
    new_timing = f"in the {time_match.group(1).lower()}"
    if frequency_text.strip().lower() == new_frequency and timing_text.strip().lower() == new_timing:
        return facts, None  # already canonical

    updated = dict(facts)
    updated["frequency"] = new_frequency
    updated["timing"] = new_timing
    return updated, NormalizationChange("frequency+timing", (frequency, timing), (new_frequency, new_timing))


def normalize_facts(
    instruction_type: InstructionType, facts: dict
) -> tuple[dict, list[NormalizationChange]]:
    if instruction_type == InstructionType.MEDICATION:
        return _normalize_medication(facts)
    if instruction_type == InstructionType.MOBILITY:
        return _normalize_mobility(facts)
    return dict(facts), []


def _normalize_lookup(facts: dict, field_name: str, table: dict[str, str]) -> tuple[dict, NormalizationChange | None]:
    value = facts.get(field_name)
    if not isinstance(value, str):
        return facts, None
    key = value.strip().lower()
    normalized = table.get(key, value.strip())
    if normalized == value:
        return facts, None
    updated = dict(facts)
    updated[field_name] = normalized
    return updated, NormalizationChange(field_name, value, normalized)


def _normalize_medication(facts: dict) -> tuple[dict, list[NormalizationChange]]:
    changes: list[NormalizationChange] = []

    facts, change = _normalize_lookup(facts, "dose_unit", _DOSE_UNIT_MAP)
    if change:
        changes.append(change)

    facts, change = _normalize_lookup(facts, "route", _ROUTE_MAP)
    if change:
        changes.append(change)

    facts, change = _normalize_lookup(facts, "frequency", _FREQUENCY_MAP)
    if change:
        changes.append(change)

    facts, change = _split_once_daily_from_timing(facts)
    if change:
        changes.append(change)

    # dose_value is numeric and passes through untouched — normalization never
    # changes numbers, only how units/abbreviations are written.
    return facts, changes


def _normalize_mobility(facts: dict) -> tuple[dict, list[NormalizationChange]]:
    changes: list[NormalizationChange] = []
    timing = facts.get("timing")
    if isinstance(timing, str):
        normalized_timing = timing.strip().lower()
        if normalized_timing != timing:
            changes.append(NormalizationChange("timing", timing, normalized_timing))
        facts = {**facts, "timing": normalized_timing}
    return facts, changes
