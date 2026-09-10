from dataclasses import dataclass, field

from app.instructions.models import CompletenessStatus


@dataclass(frozen=True)
class FieldRule:
    """One field's role in deciding whether an instruction can proceed without
    clinician input.

    tier="critical": missing => always blocks (a structurally required fact, e.g.
        medication name/dose — without it there's nothing safe to act on).
    tier="clarification": missing => blocks, but only because *this* field in
        particular is missing (e.g. assistance_required for a mobility instruction).
    tier="optional": missing => noted in missing_fields, but never blocks by itself.
    """

    field: str
    tier: str
    message: str


@dataclass(frozen=True)
class CompletenessResult:
    completeness_status: CompletenessStatus
    missing_fields: list[str] = field(default_factory=list)
    ambiguous_fields: list[str] = field(default_factory=list)
    clarification_required_fields: list[str] = field(default_factory=list)
    validation_messages: list[str] = field(default_factory=list)
