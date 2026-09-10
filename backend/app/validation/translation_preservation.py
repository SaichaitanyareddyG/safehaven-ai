"""Deterministic translation-safety validation — the same "AI proposes,
validation decides" principle as validation/fact_preservation.py, applied to
translated text. An approved English patient output is never assumed to
translate safely just because it was itself already validated.

Two layers (a language-appropriate variant of fact_preservation.py's three —
Layer A's verbatim-warning scan doesn't transfer across languages, since a
translated warning won't literally contain the English source string):

  Layer A — a direct, language-agnostic check on the translated text itself:
    the exact source dose number must still appear as a number (translators
    are instructed to keep dose numbers in Arabic numerals specifically so
    this check works regardless of target language).
  Layer B (secondary, per spec — never the sole mechanism) — back-translate
    the translated text to English, re-extract it through the same pipeline
    used on clinical instructions, and deterministically diff the two
    normalized fact sets using the exact same comparator as English
    fact-preservation (compare_facts), so CHANGED/MISSING/ADDED all apply
    identically here.
"""

from app.instructions.models import InstructionType
from app.validation.fact_preservation import (
    FactDifference,
    FactPreservationResult,
    compare_facts,
    scan_for_preserved_dose,
)


def validate_translation_preservation(
    instruction_type: InstructionType,
    original_normalized_facts: dict,
    translated_text: str,
    back_translated_instruction_type: InstructionType | None,
    back_translated_facts: dict | None,
    back_translated_ambiguities: list[str] | None,
) -> FactPreservationResult:
    differences: list[FactDifference] = []
    messages: list[str] = []

    if instruction_type == InstructionType.MEDICATION and not scan_for_preserved_dose(
        original_normalized_facts, translated_text
    ):
        differences.append(
            FactDifference("dose_value", original_normalized_facts.get("dose_value"), None, "MISSING")
        )
        messages.append("The medication dose number could not be found in the translated text.")

    if back_translated_facts is None:
        differences.append(FactDifference("_translated_text", None, None, "AMBIGUOUS"))
        messages.append(
            "The translation could not be verified via back-translation and re-analysis."
        )
    elif back_translated_instruction_type != instruction_type:
        differences.append(
            FactDifference(
                "instruction_type",
                instruction_type.value,
                back_translated_instruction_type.value if back_translated_instruction_type else None,
                "CHANGED",
            )
        )
        messages.append(
            "Back-translation appears to describe a different type of instruction than the original."
        )
    else:
        field_differences = compare_facts(instruction_type, original_normalized_facts, back_translated_facts)
        differences.extend(field_differences)
        for diff in field_differences:
            messages.append(_message_for_difference(diff))

        for ambiguous_field in back_translated_ambiguities or []:
            differences.append(FactDifference(ambiguous_field, None, None, "AMBIGUOUS"))
            messages.append(
                f"{ambiguous_field} is ambiguous after back-translation and could not be verified as safe."
            )

    return FactPreservationResult(passed=len(differences) == 0, differences=differences, messages=messages)


def _message_for_difference(diff: FactDifference) -> str:
    if diff.type == "CHANGED":
        return f"{diff.field} changed from {diff.source!r} to {diff.generated!r} after back-translation."
    if diff.type == "MISSING":
        return f"{diff.field} was present in the original but is missing after back-translation."
    if diff.type == "ADDED":
        return f"{diff.field} was not in the original but appears after back-translation."
    return f"{diff.field} is ambiguous and could not be verified."
