"""The one place a provider's raw output is turned into something the rest of the
application is allowed to trust. This is deliberately the full extent of what "AI
proposes" means in this codebase — run_extraction() never decides completeness or
whether clarification is needed; that's validation/completeness.py's job.
"""

from dataclasses import dataclass

from pydantic import ValidationError

from app.ai.prompts import PROMPT_VERSION
from app.ai.provider import ExtractionProviderError, LLMProvider, ProviderMetadata
from app.ai.schemas import ExtractionResult, extraction_result_adapter


@dataclass(frozen=True)
class ExtractionAttempt:
    """The full outcome of one extraction attempt. On failure, result is always
    None — never a partially-trusted or best-effort guess."""

    succeeded: bool
    result: ExtractionResult | None
    metadata: ProviderMetadata | None
    prompt_version: str
    failure_reason: str | None


def run_extraction(provider: LLMProvider, text: str) -> ExtractionAttempt:
    try:
        raw = provider.extract_instruction(text)
    except ExtractionProviderError as exc:
        return ExtractionAttempt(
            succeeded=False, result=None, metadata=None, prompt_version=PROMPT_VERSION, failure_reason=str(exc)
        )

    try:
        result = extraction_result_adapter.validate_python(raw.payload)
    except ValidationError as exc:
        return ExtractionAttempt(
            succeeded=False,
            result=None,
            metadata=raw.metadata,
            prompt_version=PROMPT_VERSION,
            failure_reason=f"Malformed extraction output: {exc}",
        )

    return ExtractionAttempt(
        succeeded=True, result=result, metadata=raw.metadata, prompt_version=PROMPT_VERSION, failure_reason=None
    )
