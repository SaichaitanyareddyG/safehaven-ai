"""Turn an approved medication instruction into a dose schedule: what time
each dose is due, how many a day, from which day until which day.

No AI here. The AI already extracted frequency, timing, duration, dose and
food from the clinician's words, and those facts were validated and approved.
This module only maps them, by fixed rules, onto the hospital's standard dose
times. Anything it cannot map with certainty — every other day, weekly,
"until finished", a frequency that contradicts its timing — becomes
NEEDS_REVIEW: no reminders at all, and the clinician sees why before
approving. A missing reminder is a nuisance; a wrong one is a dosing error.

Standard times match Module 2's bedside time check
(medication_verification/service.py), so the patient's reminder and the
nurse's "is this dose on time?" never disagree.
"""

import re
from dataclasses import dataclass, field
from datetime import date, time, timedelta
from typing import Literal

Kind = Literal["SCHEDULED", "AS_NEEDED", "NEEDS_REVIEW"]

# Hospital standard dose times. Prototype defaults, one place to change.
SLOT_TIMES: dict[str, time] = {
    "morning": time(8, 0),
    "breakfast": time(8, 0),
    "noon": time(12, 0),
    "lunch": time(12, 0),
    "afternoon": time(14, 0),
    "dinner": time(18, 0),
    "supper": time(18, 0),
    "evening": time(20, 0),
    "night": time(22, 0),
    "bedtime": time(22, 0),
    "nightly": time(22, 0),
}
TIMES_PER_DAY: dict[int, list[time]] = {
    1: [time(8, 0)],
    2: [time(8, 0), time(20, 0)],
    3: [time(8, 0), time(14, 0), time(20, 0)],
    4: [time(8, 0), time(12, 0), time(16, 0), time(20, 0)],
}
# "Every N hours": first dose at 06:00 (08:00 for 12 and 24), then every N.
_INTERVAL_ANCHOR = {4: time(6, 0), 6: time(6, 0), 8: time(6, 0), 12: time(8, 0), 24: time(8, 0)}

_PRN_RE = re.compile(r"\bas needed\b|\bprn\b|\bwhen required\b|\bif needed\b|\bas required\b", re.I)
# Patterns this module will not turn into reminders.
_UNSUPPORTED_RE = re.compile(
    r"\bevery other\b|\balternate\b|\bweekly\b|\bmonthly\b|\bonce a week\b|\btimes a week\b|\bper week\b"
    r"|\bevery \d+ days\b|\bstat\b|\bonce only\b|\bsingle dose\b|\bone dose\b",
    re.I,
)
_COUNT_WORDS = {"once": 1, "one": 1, "twice": 2, "two": 2, "three": 3, "thrice": 3, "four": 4}
_COUNT_RE = re.compile(
    # Needs "a day"/"daily": a bare "once" could be a single dose.
    r"\b(once|twice|thrice|one|two|three|four|[1-4])\s*(?:times?\s*)?(?:a|per|each)?\s*(?:day|daily)\b",
    re.I,
)
_ABBREV = {"bid": 2, "tid": 3, "qid": 4, "qd": 1, "od": 1, "daily": 1}
_INTERVAL_RE = re.compile(r"\bevery\s+(\d+)\s*(?:hours?|hrs?|h)\b|\bq\s?(\d+)\s?h\b", re.I)
_SLOT_RE = re.compile(r"\b(" + "|".join(SLOT_TIMES) + r")\b", re.I)

_NUMBER_WORDS = {
    "a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
}
_DURATION_RE = re.compile(
    r"^(?:for\s+|x\s*|×\s*)?(?:the\s+next\s+)?(\d+|" + "|".join(_NUMBER_WORDS) + r")\s*(days?|weeks?)$", re.I
)
_ONGOING_RE = re.compile(r"\b(ongoing|long[- ]term|indefinitely|continue|continuing|lifelong|regularly)\b", re.I)
_MAX_COURSE_DAYS = 180


@dataclass(frozen=True)
class DoseSchedule:
    kind: Kind
    times: list[time] = field(default_factory=list)
    dose: str | None = None
    with_food: bool | None = None
    # None = no end date: continues until the care team stops it.
    duration_days: int | None = None
    # Only for NEEDS_REVIEW: why there are no reminders, in plain words.
    problem: str | None = None

    @property
    def times_per_day(self) -> int:
        return len(self.times)

    def end_date(self, start: date) -> date | None:
        return None if self.duration_days is None else start + timedelta(days=self.duration_days - 1)

    def summary(self) -> str:
        if self.kind == "AS_NEEDED":
            return "Only when needed — no set times"
        if self.kind == "NEEDS_REVIEW":
            return "No reminders for this medicine"
        parts = [" and ".join(format_time(t) for t in self.times)]
        if self.with_food:
            parts.append("with food")
        parts.append(f"for {self.duration_days} day{'s' if self.duration_days != 1 else ''}" if self.duration_days else "ongoing")
        return ", ".join(parts)


def format_time(value: time) -> str:
    hour = value.hour % 12 or 12
    suffix = "AM" if value.hour < 12 else "PM"
    return f"{hour}:{value.minute:02d} {suffix}"


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _dose(facts: dict) -> str | None:
    value, unit = facts.get("dose_value"), _text(facts.get("dose_unit"))
    if value is None or not unit:
        return None
    try:
        number = f"{float(value):g}"
    except (TypeError, ValueError):
        return None
    return f"{number} {unit}"


def _review(problem: str, facts: dict) -> DoseSchedule:
    return DoseSchedule(kind="NEEDS_REVIEW", dose=_dose(facts), with_food=facts.get("with_food"), problem=problem)


def _count_per_day(frequency: str) -> int | None:
    """Doses per day from "twice daily", "3 times a day", "BID". Explicit
    counts first: "daily" alone means once, but "twice daily" must never be
    read as once just because it also contains "daily"."""
    match = _COUNT_RE.search(frequency)
    if match is not None:
        word = match.group(1).lower()
        return int(word) if word.isdigit() else _COUNT_WORDS.get(word)
    lowered = frequency.lower().replace(".", "")
    for abbrev, count in _ABBREV.items():
        if re.search(rf"\b{abbrev}\b", lowered):
            return count
    return None


# Every word the rules understand. Anything else in frequency/timing means
# the order says something these rules cannot read, so: no reminders.
_KNOWN_WORDS = (
    set(SLOT_TIMES) | set(_COUNT_WORDS) | set(_ABBREV)
    | {
        "a", "an", "and", "at", "after", "before", "day", "days", "each", "every", "per", "the", "in", "on",
        "time", "times", "hour", "hours", "hr", "hrs", "h", "q", "with", "food", "meal", "meals", "water",
        "of", "glass", "empty", "stomach", "take", "then", "also", "by", "mouth", "orally", "dose", "doses",
    }
)


def _unknown_words(text: str) -> list[str]:
    words = re.findall(r"[a-z]+", text.lower())
    return [w for w in words if w not in _KNOWN_WORDS]


def _parse_duration(duration: str) -> tuple[bool, int | None]:
    """(understood, days). (True, None) means ongoing / no end date."""
    if not duration:
        return True, None
    if _ONGOING_RE.search(duration):
        return True, None
    match = _DURATION_RE.match(duration.strip().rstrip("."))
    if match is None:
        return False, None
    raw, unit = match.group(1).lower(), match.group(2).lower()
    number = int(raw) if raw.isdigit() else _NUMBER_WORDS[raw]
    days = number * 7 if unit.startswith("week") else number
    if not 1 <= days <= _MAX_COURSE_DAYS:
        return False, None
    return True, days


def derive_schedule(facts: dict, raw_text: str | None = None) -> DoseSchedule:
    """facts: a MEDICATION extraction's normalized_facts. raw_text: the
    clinician's own words, read only to catch "as needed" the model dropped
    (same reason as medication_verification._order_is_prn)."""
    frequency = _text(facts.get("frequency"))
    timing = _text(facts.get("timing"))
    duration = _text(facts.get("duration"))
    with_food = facts.get("with_food")
    combined = f"{frequency} {timing}"

    if _PRN_RE.search(f"{combined} {raw_text or ''}"):
        return DoseSchedule(kind="AS_NEEDED", dose=_dose(facts), with_food=with_food)
    if not frequency and not timing:
        return _review("How often to take it is not stated.", facts)
    if _UNSUPPORTED_RE.search(combined):
        return _review(f'"{frequency or timing}" is not a daily pattern SafeHaven can turn into reminders.', facts)

    unknown = _unknown_words(combined)
    if unknown:
        return _review(f'"{combined.strip()}" has wording SafeHaven cannot turn into exact dose times.', facts)

    understood, days = _parse_duration(duration)
    if not understood:
        return _review(f'The course length "{duration}" is not clear enough to know when reminders should stop.', facts)

    slots = sorted({SLOT_TIMES[m.lower()] for m in _SLOT_RE.findall(combined)})
    interval = _INTERVAL_RE.search(combined)
    count = _count_per_day(frequency) if frequency else None

    if interval:
        hours = int(interval.group(1) or interval.group(2))
        if hours not in _INTERVAL_ANCHOR:
            return _review(f'"Every {hours} hours" is not an interval SafeHaven schedules.', facts)
        if slots:
            return _review("The order gives both an hourly interval and times of day.", facts)
        anchor = _INTERVAL_ANCHOR[hours]
        times = sorted(time((anchor.hour + hours * i) % 24, 0) for i in range(24 // hours))
    elif slots:
        if count is not None and count != len(slots):
            return _review(
                f'"{frequency}" does not match the {len(slots)} time(s) of day given ("{timing or frequency}").', facts
            )
        times = slots
    elif count is not None and count in TIMES_PER_DAY:
        times = TIMES_PER_DAY[count]
    else:
        return _review(f'"{frequency or timing}" is not a frequency SafeHaven can turn into reminders.', facts)

    return DoseSchedule(kind="SCHEDULED", times=times, dose=_dose(facts), with_food=with_food, duration_days=days)
