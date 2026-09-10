"""Deterministic fact-preservation validation — the actual safety gate between
"the AI wrote something" and "a clinician may approve this for the patient."

Precision matters here: the COMPARISON is deterministic (never "LLM, was your
own output safe?") — but the inputs to that comparison are not. Re-extracting
the generated text (Layer B) is itself an LLM call, just like the generation
or translation it's checking; that step is probabilistic, same as everywhere
else an LLM is involved. What makes this safe isn't "no LLM is involved" — an
LLM is involved at every step — it's that nothing an LLM outputs is ever
trusted directly: everything is normalized into structured facts, and a
plain, deterministic comparator (drug == drug, dose == dose, route == route,
frequency == frequency, timing == timing, warnings == warnings) decides
CHANGED/MISSING/ADDED from that structured diff, never from re-reading prose.
An uncertain or failed re-extraction is treated as unsafe by construction
(see below), so the failure mode of the probabilistic steps is "block and
ask a clinician to review," not "let something wrong through."

Three layers:

  Layer A — direct textual checks on the generated text itself, independent of
    any re-extraction accuracy: the exact source dose number must still appear
    as a number, and every explicit source warning must still appear (see
    scan_for_preserved_warnings — number-anchored, not verbatim-text-anchored,
    for warnings that contain a number).
  Layer B — re-extract the generated text through the same extraction pipeline
    used on clinical instructions, normalize both fact sets the same way, then
    deterministically diff them field by field (CHANGED / MISSING).
  Layer C — the same diff also surfaces facts present in the generated output
    but absent from the source (ADDED) — an unsupported fact the AI introduced,
    even if every original fact is technically still there too.

If the generated text can't even be re-extracted (malformed/failed), that is
itself treated as unsafe — never as "no differences found."
"""

import re
from collections import Counter
from dataclasses import dataclass, field

from app.instructions.models import InstructionType

# "warnings" / "warning_signs" are deliberately excluded here — Layer A
# (scan_for_preserved_warnings) already checks them via direct, exact-text
# matching against the generated text, which is both more appropriate for
# free-text safety statements and more reliable than depending on structured
# re-extraction to notice free text it was never asked to parse out precisely.
# Including them here too would risk a false FAILED on a genuinely faithful
# generation whenever re-extraction under-reports warnings it can't parse.
# "reason" is deliberately excluded here, the same way "warnings" is (see
# above): the generation prompt now explicitly tells the model NOT to restate
# it in the flowing patient_text (it's shown separately, in its own labeled
# "why" section on the patient care page — see patient_access/service.py) —
# so a genuinely correct generation is EXPECTED to omit it, and comparing it
# here would flag that expected omission as a false "missing fact" on every
# case where the clinician stated a reason.
FIELDS_BY_TYPE: dict[InstructionType, list[str]] = {
    InstructionType.MEDICATION: [
        "medication_name",
        "dose_value",
        "dose_unit",
        "route",
        "frequency",
        "timing",
        "duration",
        "with_food",
    ],
    InstructionType.MOBILITY: ["activity", "timing", "duration", "assistance_required", "restrictions"],
    InstructionType.DIET: ["allowed_intake", "restricted_intake", "timing", "special_restrictions"],
    InstructionType.WOUND_CARE: ["body_site", "action", "frequency", "supplies"],
    InstructionType.FOLLOW_UP: ["provider_or_specialty", "timeframe", "purpose"],
    InstructionType.GENERAL: ["summary", "details"],
}

_MISSING_SENTINELS = (None, "", [], {})


@dataclass(frozen=True)
class FactDifference:
    field: str
    source: object
    generated: object
    type: str  # CHANGED | MISSING | ADDED | AMBIGUOUS


@dataclass(frozen=True)
class FactPreservationResult:
    passed: bool
    differences: list[FactDifference] = field(default_factory=list)
    messages: list[str] = field(default_factory=list)


def _is_missing(value: object) -> bool:
    return value in _MISSING_SENTINELS


def _token_counts(text: str) -> Counter:
    return Counter(re.findall(r"[a-z0-9]+", text.lower()))


def _timing_preserved(source: str, generated: str) -> bool:
    """'timing' is a free-form descriptive phrase, not a closed-vocabulary
    value like route/frequency — real generation runs showed the model
    routinely adds clarifying scaffolding around it (e.g. "one dose ... the
    other dose ..." around "1 hour after breakfast and 1 hour after dinner")
    without changing what it means. Exact string matching flagged that as a
    changed fact. This allows the generated phrase to ADD words, but every
    word/number from the source must still appear at least as many times in
    the generated phrase — a plain (non-counting) set check would wrongly
    accept "1 hour ... 1 hour" -> "2 hours ... 1 hour" (the surviving second
    "1" masks the dropped first one); counting catches that. Deliberately
    scoped to timing only; every other field keeps exact (post-normalization,
    case-folded) matching in _equal()."""
    source_counts = _token_counts(source)
    generated_counts = _token_counts(generated)
    return all(generated_counts[token] >= count for token, count in source_counts.items())


def _equal(a: object, b: object) -> bool:
    if isinstance(a, bool) or isinstance(b, bool):
        return a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(float(a) - float(b)) < 1e-9
    if isinstance(a, str) and isinstance(b, str):
        # Case/whitespace never carry clinical meaning for these free-text
        # fields (medication name, activity, timeframe, ...) — a real Step 10
        # evaluation run showed re-extraction of generated/back-translated text
        # regularly differs only in casing (e.g. "Metoprolol" vs "metoprolol",
        # a proper noun re-cased mid-sentence), which a strict a == b flagged
        # as a changed fact. This does not loosen numeric or boolean
        # comparison, and a genuinely different word still fails.
        return a.strip().casefold() == b.strip().casefold()
    return a == b


def _compare_list_field(field_name: str, source_list: list, generated_list: list) -> list[FactDifference]:
    source_set = {str(v).strip().lower() for v in source_list}
    generated_set = {str(v).strip().lower() for v in generated_list}
    differences = []
    for item in sorted(source_set - generated_set):
        differences.append(FactDifference(field_name, item, None, "MISSING"))
    for item in sorted(generated_set - source_set):
        differences.append(FactDifference(field_name, None, item, "ADDED"))
    return differences


def compare_facts(
    instruction_type: InstructionType, original_facts: dict, generated_facts: dict
) -> list[FactDifference]:
    """Layers B + C: a field-by-field diff between two already-normalized fact
    sets. Both inputs must already be normalized the same way (see
    validation/normalization.py) — this function does plain equality, not
    abbreviation-aware comparison, by design: normalization is where "PO" and
    "oral" become the same value; this is where "the same value" is checked."""
    fields = FIELDS_BY_TYPE.get(instruction_type, sorted(set(original_facts) | set(generated_facts)))
    differences: list[FactDifference] = []

    for field_name in fields:
        source_value = original_facts.get(field_name)
        generated_value = generated_facts.get(field_name)

        if isinstance(source_value, list) or isinstance(generated_value, list):
            differences.extend(_compare_list_field(field_name, source_value or [], generated_value or []))
            continue

        source_missing = _is_missing(source_value)
        generated_missing = _is_missing(generated_value)

        if source_missing and generated_missing:
            continue
        if source_missing and not generated_missing:
            differences.append(FactDifference(field_name, source_value, generated_value, "ADDED"))
        elif not source_missing and generated_missing:
            differences.append(FactDifference(field_name, source_value, generated_value, "MISSING"))
        elif not _equal(source_value, generated_value):
            if (
                field_name == "timing"
                and isinstance(source_value, str)
                and isinstance(generated_value, str)
                and _timing_preserved(source_value, generated_value)
            ):
                continue
            differences.append(FactDifference(field_name, source_value, generated_value, "CHANGED"))

    return differences


def scan_for_preserved_dose(original_facts: dict, generated_text: str) -> bool:
    """Layer A (numbers): does the exact source dose number still appear as a
    number in the generated text? Independent of re-extraction accuracy — a
    fast, hard-to-fool sanity check on the single highest-stakes value type."""
    dose_value = original_facts.get("dose_value")
    if dose_value is None:
        return True
    found = {float(m) for m in re.findall(r"\d+(?:\.\d+)?", generated_text)}
    return any(abs(n - float(dose_value)) < 1e-9 for n in found)


def _warning_preserved(warning: str, generated_text: str) -> bool:
    """Real generation runs (and manual testing — "maximum 4,000 mg in 24
    hours" faithfully rendered as "Do not take more than 4,000 mg in 24
    hours") showed the model rewords max-dose warnings the way it rewords
    'timing' (see _timing_preserved) — but unlike timing, the wrapper words
    themselves change too ("maximum" -> "more than"), not just get added
    around unchanged words. A word-level containment check like timing's
    would then require the literal word "maximum" to survive, which a
    faithful rewording doesn't preserve.

    For a warning containing a number (the common case: dosage/frequency
    limits), this instead applies the same philosophy already used for the
    single highest-stakes field in the app, scan_for_preserved_dose: the
    number itself is what's safety-critical, not the exact phrase carrying
    it. Every number in the warning must still appear, with at least the same
    count, somewhere in the generated text — a changed or dropped number is
    still caught, since it shares no matching count with the generated text.

    For a warning with no number (a behavioral warning like "Do not drive"),
    there is no number to anchor on and no reliable cheap way to verify
    paraphrased meaning, so this keeps the original exact-substring check
    unchanged — no loosening there."""
    warning_numbers = Counter(re.findall(r"\d+", warning))
    if not warning_numbers:
        return warning.lower() in generated_text.lower()
    generated_numbers = Counter(re.findall(r"\d+", generated_text))
    return all(generated_numbers[n] >= count for n, count in warning_numbers.items())


def scan_for_preserved_warnings(original_facts: dict, generated_text: str) -> list[str]:
    """Layer A (warnings): every explicit source warning's words/numbers must
    still appear (see _warning_preserved) in the generated text. A direct
    textual check on safety-critical text, not dependent on structured
    re-extraction picking up free-text warnings correctly. Returns the
    warnings that went missing."""
    warnings = list(original_facts.get("warnings") or []) + list(original_facts.get("warning_signs") or [])
    return [w for w in warnings if not _warning_preserved(w, generated_text)]


def validate_fact_preservation(
    instruction_type: InstructionType,
    original_normalized_facts: dict,
    generated_text: str,
    regenerated_instruction_type: InstructionType | None,
    regenerated_facts: dict | None,
    regenerated_ambiguities: list[str] | None,
) -> FactPreservationResult:
    differences: list[FactDifference] = []
    messages: list[str] = []

    if instruction_type == InstructionType.MEDICATION and not scan_for_preserved_dose(
        original_normalized_facts, generated_text
    ):
        differences.append(FactDifference("dose_value", original_normalized_facts.get("dose_value"), None, "MISSING"))
        messages.append("The medication dose number could not be found in the generated text.")

    for warning in scan_for_preserved_warnings(original_normalized_facts, generated_text):
        differences.append(FactDifference("warnings", warning, None, "MISSING"))
        messages.append(f"Safety warning was not preserved in the generated text: {warning!r}.")

    if regenerated_facts is None:
        differences.append(FactDifference("_generated_text", None, None, "AMBIGUOUS"))
        messages.append(
            "The generated patient text could not be re-analyzed to confirm it preserved the original facts."
        )
    elif regenerated_instruction_type != instruction_type:
        differences.append(
            FactDifference(
                "instruction_type",
                instruction_type.value,
                regenerated_instruction_type.value if regenerated_instruction_type else None,
                "CHANGED",
            )
        )
        messages.append("The generated text appears to describe a different type of instruction than the original.")
    else:
        field_differences = compare_facts(instruction_type, original_normalized_facts, regenerated_facts)
        differences.extend(field_differences)
        for diff in field_differences:
            messages.append(_message_for_difference(diff))

        for ambiguous_field in regenerated_ambiguities or []:
            differences.append(FactDifference(ambiguous_field, None, None, "AMBIGUOUS"))
            messages.append(
                f"{ambiguous_field} is ambiguous in the generated text and could not be verified as safe."
            )

    return FactPreservationResult(passed=len(differences) == 0, differences=differences, messages=messages)


def _message_for_difference(diff: FactDifference) -> str:
    if diff.type == "CHANGED":
        return f"{diff.field} changed from {diff.source!r} to {diff.generated!r}."
    if diff.type == "MISSING":
        return f"{diff.field} was present in the original but is missing from the generated text."
    if diff.type == "ADDED":
        return f"{diff.field} was not in the original but appears in the generated text."
    return f"{diff.field} is ambiguous and could not be verified."
