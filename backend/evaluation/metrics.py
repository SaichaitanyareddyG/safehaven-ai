"""Comparison, classification, and aggregation logic for the Step 10 evaluation
harness. Pure functions only — no network calls, no provider SDKs — so this
module can be unit-tested and reused by both runner.py (during a live run) and
report.py (when regenerating a report from an already-saved raw results file).

Ground truth for what a field SHOULD contain comes entirely from
evaluation/cases.json, authored by hand — never from the LLM under test. The
deterministic "should this need clarification" verdict is computed by
importing and calling the SAME app.validation.completeness.evaluate_completeness
the real application uses, applied to the case's ground-truth facts, so the
case file doesn't have to hand-duplicate that logic and can't drift from it.
"""

from __future__ import annotations

import enum
import re
import statistics
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.ai.schemas import (  # noqa: E402
    DietFacts,
    FollowUpFacts,
    GeneralFacts,
    MedicationFacts,
    MobilityFacts,
    WoundCareFacts,
)
from app.instructions.models import InstructionType  # noqa: E402
from app.validation.rules import RULES_BY_TYPE  # noqa: E402

FACT_MODEL_BY_CATEGORY = {
    "MEDICATION": MedicationFacts,
    "MOBILITY": MobilityFacts,
    "DIET": DietFacts,
    "WOUND_CARE": WoundCareFacts,
    "FOLLOW_UP": FollowUpFacts,
    "GENERAL": GeneralFacts,
}


class FailureType(str, enum.Enum):
    EXTRACTION_ERROR = "EXTRACTION_ERROR"
    INVENTED_FACT = "INVENTED_FACT"
    MISSED_FACT = "MISSED_FACT"
    CLASSIFICATION_ERROR = "CLASSIFICATION_ERROR"
    COMPLETENESS_ERROR = "COMPLETENESS_ERROR"
    GENERATION_CHANGED_FACT = "GENERATION_CHANGED_FACT"
    GENERATION_ADDED_FACT = "GENERATION_ADDED_FACT"
    TRANSLATION_CHANGED_FACT = "TRANSLATION_CHANGED_FACT"
    PROVIDER_FAILURE = "PROVIDER_FAILURE"
    VALIDATOR_FALSE_POSITIVE = "VALIDATOR_FALSE_POSITIVE"
    VALIDATOR_FALSE_NEGATIVE = "VALIDATOR_FALSE_NEGATIVE"


def fields_for_category(category: str) -> list[str]:
    return list(FACT_MODEL_BY_CATEGORY[category].model_fields.keys())


def critical_fields_for_category(category: str) -> set[str]:
    instruction_type = InstructionType(category)
    return {rule.field for rule in RULES_BY_TYPE.get(instruction_type, []) if rule.tier == "critical"}


_MISSING_SENTINELS = (None, "", [], {})


def _is_missing(value: object) -> bool:
    return value is None or value in _MISSING_SENTINELS


def _stem(word: str) -> str:
    """Crude suffix stripping ONLY for evaluation grading leniency (e.g. "walk"
    vs "walking", "clean" vs "cleaning") — never used by the application itself.
    Real Step 10 runs showed real models freely switch verb form between the
    original extraction and a re-extraction of generated/translated text
    without changing clinical meaning; a strict token match was flagging that
    as an extraction error it isn't."""
    for suffix in ("ing", "ed"):
        if len(word) > len(suffix) + 2 and word.endswith(suffix):
            return word[: -len(suffix)]
    return word


def _tokenize(text: str) -> set[str]:
    return {_stem(w) for w in re.findall(r"[a-z0-9]+", text.lower())}


def _fuzzy_text_match(a: str, b: str) -> bool:
    ta, tb = _tokenize(a), _tokenize(b)
    if not ta or not tb:
        return False
    overlap = ta & tb
    return len(overlap) / max(len(ta), len(tb)) >= 0.4


# Verdict vocabulary, most to least severe for reporting purposes.
VERDICT_INVENTED = "INVENTED_WHEN_ABSENT"
VERDICT_INCORRECT = "INCORRECT_VALUE"
VERDICT_MISSING = "MISSING_WHEN_EXPECTED"
VERDICT_MATCH = "MATCH"
VERDICT_MATCH_FUZZY = "MATCH_FUZZY"
VERDICT_MATCH_NULL = "MATCH_NULL"
VERDICT_MATCH_EMPTY_LIST = "MATCH_EMPTY_LIST"
VERDICT_MATCH_NONEMPTY_LIST = "MATCH_NONEMPTY_LIST_UNVERIFIED"  # both non-empty; exact overlap not graded automatically


def compare_field(expected_value: object, actual_value: object) -> str:
    """One field's verdict. List-valued fields (warnings, supplies, ...) are
    graded on presence/absence only — free-text list *content* isn't compared
    for exact wording, since clinically-equivalent phrasing varies too much for
    a simple string match; those cases are still visible in the per-case report
    for a human to spot-check."""
    if isinstance(expected_value, list) or isinstance(actual_value, list):
        expected_list = expected_value or []
        actual_list = actual_value or []
        if not expected_list and not actual_list:
            return VERDICT_MATCH_EMPTY_LIST
        if not expected_list and actual_list:
            return VERDICT_INVENTED
        if expected_list and not actual_list:
            return VERDICT_MISSING
        return VERDICT_MATCH_NONEMPTY_LIST

    if _is_missing(expected_value) and _is_missing(actual_value):
        return VERDICT_MATCH_NULL
    if _is_missing(expected_value) and not _is_missing(actual_value):
        return VERDICT_INVENTED
    if not _is_missing(expected_value) and _is_missing(actual_value):
        return VERDICT_MISSING

    if isinstance(expected_value, bool) or isinstance(actual_value, bool):
        return VERDICT_MATCH if expected_value == actual_value else VERDICT_INCORRECT
    if isinstance(expected_value, (int, float)) and isinstance(actual_value, (int, float)):
        return VERDICT_MATCH if abs(float(expected_value) - float(actual_value)) < 1e-9 else VERDICT_INCORRECT
    if isinstance(expected_value, str) and isinstance(actual_value, str):
        if expected_value.strip().lower() == actual_value.strip().lower():
            return VERDICT_MATCH
        return VERDICT_MATCH_FUZZY if _fuzzy_text_match(expected_value, actual_value) else VERDICT_INCORRECT
    return VERDICT_MATCH if expected_value == actual_value else VERDICT_INCORRECT


def compare_case_facts(category: str, expected_facts: dict, actual_facts: dict) -> dict[str, str]:
    return {
        field_name: compare_field(expected_facts.get(field_name), actual_facts.get(field_name))
        for field_name in fields_for_category(category)
    }


def latency_stats(latencies_ms: list[int]) -> dict[str, float | int | None]:
    if not latencies_ms:
        return {"count": 0, "mean": None, "median": None, "p95": None, "max": None}
    ordered = sorted(latencies_ms)
    p95_index = min(len(ordered) - 1, int(round(0.95 * (len(ordered) - 1))))
    return {
        "count": len(ordered),
        "mean": round(statistics.mean(ordered), 1),
        "median": round(statistics.median(ordered), 1),
        "p95": ordered[p95_index],
        "max": ordered[-1],
    }
