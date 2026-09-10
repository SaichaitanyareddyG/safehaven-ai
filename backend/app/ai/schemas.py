"""Strict, Pydantic-validated shapes for LLM extraction output.

No provider's response is trusted as-is: extraction_result_adapter.validate_python()
is the single choke point every provider's raw JSON must pass through. Malformed
output (wrong shape, unknown instruction_type, wrong field types) fails validation
here rather than being guessed at or coerced — see ai/extraction_service.py.
"""

from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field, TypeAdapter

from app.instructions.models import InstructionType


class MedicationFacts(BaseModel):
    medication_name: str | None = None
    dose_value: float | None = None
    dose_unit: str | None = None
    route: str | None = None
    frequency: str | None = None
    timing: str | None = None
    duration: str | None = None
    with_food: bool | None = None
    warnings: list[str] = []
    # Why this medication was prescribed — extracted ONLY if the clinician's
    # own instruction text states it (e.g. "for your blood pressure"), same
    # "never invent, null if absent" rule as every other field. This is the
    # sole source of a patient-specific "why" — see app/reference/ for the
    # separate, non-patient-specific general-purpose fallback used when this
    # is null.
    reason: str | None = None


class MobilityFacts(BaseModel):
    activity: str | None = None
    timing: str | None = None
    duration: str | None = None
    assistance_required: bool | None = None
    restrictions: list[str] = []
    reason: str | None = None


class DietFacts(BaseModel):
    allowed_intake: list[str] = []
    restricted_intake: list[str] = []
    timing: str | None = None
    special_restrictions: list[str] = []
    reason: str | None = None


class WoundCareFacts(BaseModel):
    body_site: str | None = None
    action: str | None = None
    frequency: str | None = None
    supplies: list[str] = []
    warning_signs: list[str] = []
    reason: str | None = None


class FollowUpFacts(BaseModel):
    provider_or_specialty: str | None = None
    timeframe: str | None = None
    purpose: str | None = None


class GeneralFacts(BaseModel):
    """Fallback shape for content that doesn't fit a specific supported type."""

    summary: str | None = None
    details: list[str] = []


class MedicationExtraction(BaseModel):
    instruction_type: Literal[InstructionType.MEDICATION] = InstructionType.MEDICATION
    facts: MedicationFacts
    ambiguities: list[str] = []


class MobilityExtraction(BaseModel):
    instruction_type: Literal[InstructionType.MOBILITY] = InstructionType.MOBILITY
    facts: MobilityFacts
    ambiguities: list[str] = []


class DietExtraction(BaseModel):
    instruction_type: Literal[InstructionType.DIET] = InstructionType.DIET
    facts: DietFacts
    ambiguities: list[str] = []


class WoundCareExtraction(BaseModel):
    instruction_type: Literal[InstructionType.WOUND_CARE] = InstructionType.WOUND_CARE
    facts: WoundCareFacts
    ambiguities: list[str] = []


class FollowUpExtraction(BaseModel):
    instruction_type: Literal[InstructionType.FOLLOW_UP] = InstructionType.FOLLOW_UP
    facts: FollowUpFacts
    ambiguities: list[str] = []


class GeneralExtraction(BaseModel):
    instruction_type: Literal[InstructionType.GENERAL] = InstructionType.GENERAL
    facts: GeneralFacts
    ambiguities: list[str] = []


ExtractionResult = Annotated[
    Union[
        MedicationExtraction,
        MobilityExtraction,
        DietExtraction,
        WoundCareExtraction,
        FollowUpExtraction,
        GeneralExtraction,
    ],
    Field(discriminator="instruction_type"),
]

extraction_result_adapter: TypeAdapter[ExtractionResult] = TypeAdapter(ExtractionResult)
