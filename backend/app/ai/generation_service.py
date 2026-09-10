"""The one place a provider's raw generated text becomes a candidate the rest of
the application may consider — never something inherently trusted as safe. Only
validation/fact_preservation.py ever decides that, by independently re-checking
the text against the original facts.
"""

from dataclasses import dataclass

from app.ai.prompts import GENERATION_PROMPT_VERSION
from app.ai.provider import ExtractionProviderError, LLMProvider, ProviderMetadata
from app.instructions.models import InstructionType


@dataclass(frozen=True)
class GenerationAttempt:
    succeeded: bool
    patient_text: str | None
    metadata: ProviderMetadata | None
    prompt_version: str
    failure_reason: str | None


def run_generation(
    provider: LLMProvider, original_text: str, structured_facts: dict, instruction_type: InstructionType
) -> GenerationAttempt:
    try:
        raw = provider.generate_patient_friendly(original_text, structured_facts, instruction_type)
    except ExtractionProviderError as exc:
        return GenerationAttempt(
            succeeded=False,
            patient_text=None,
            metadata=None,
            prompt_version=GENERATION_PROMPT_VERSION,
            failure_reason=str(exc),
        )

    if not raw.patient_text or not raw.patient_text.strip():
        return GenerationAttempt(
            succeeded=False,
            patient_text=None,
            metadata=raw.metadata,
            prompt_version=GENERATION_PROMPT_VERSION,
            failure_reason="Provider returned empty patient text",
        )

    return GenerationAttempt(
        succeeded=True,
        patient_text=raw.patient_text.strip(),
        metadata=raw.metadata,
        prompt_version=GENERATION_PROMPT_VERSION,
        failure_reason=None,
    )
