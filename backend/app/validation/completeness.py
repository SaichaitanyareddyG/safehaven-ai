"""Deterministic completeness/ambiguity evaluation — "our application rules"
deciding whether an AI-proposed extraction is safe to proceed with, or needs a
clinician. The LLM never makes this call; it only supplies facts and, optionally,
flags fields it found genuinely ambiguous (as opposed to simply absent).
"""

from app.instructions.models import CompletenessStatus, InstructionType
from app.validation.rules import RULES_BY_TYPE
from app.validation.schemas import CompletenessResult

_MISSING_SENTINELS = (None, "", [], {})


def _is_missing(value: object) -> bool:
    return value in _MISSING_SENTINELS


def evaluate_completeness(
    instruction_type: InstructionType, facts: dict, ambiguities: list[str]
) -> CompletenessResult:
    rules = RULES_BY_TYPE.get(instruction_type, [])

    missing_fields: list[str] = []
    clarification_required_fields: list[str] = []
    validation_messages: list[str] = []

    for rule in rules:
        if not _is_missing(facts.get(rule.field)):
            continue
        missing_fields.append(rule.field)
        if rule.tier in ("critical", "clarification"):
            clarification_required_fields.append(rule.field)
            validation_messages.append(rule.message)

    # Ambiguous is a distinct concept from missing: the LLM found a value but
    # flagged it as unreliable/conflicting, not absent. Always requires clarification.
    ambiguous_fields = list(dict.fromkeys(ambiguities))
    for field_name in ambiguous_fields:
        if field_name not in clarification_required_fields:
            clarification_required_fields.append(field_name)
    if ambiguous_fields:
        validation_messages.append(
            "The following fields are ambiguous and need clinician confirmation: "
            + ", ".join(ambiguous_fields)
            + "."
        )

    # GENERAL means the AI couldn't confidently classify the instruction into a
    # specific supported type — a type-level signal, not a missing-field one, so it
    # always routes to clarification regardless of what RULES_BY_TYPE says.
    if instruction_type == InstructionType.GENERAL:
        if "instruction_type" not in clarification_required_fields:
            clarification_required_fields.append("instruction_type")
        validation_messages.append(
            "This instruction could not be classified into a specific supported type and needs clinician review."
        )

    status = (
        CompletenessStatus.NEEDS_CLARIFICATION if clarification_required_fields else CompletenessStatus.PASSED
    )

    return CompletenessResult(
        completeness_status=status,
        missing_fields=missing_fields,
        ambiguous_fields=ambiguous_fields,
        clarification_required_fields=clarification_required_fields,
        validation_messages=validation_messages,
    )
