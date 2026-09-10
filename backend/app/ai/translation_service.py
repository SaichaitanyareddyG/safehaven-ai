"""The one place a provider's raw translated text becomes a candidate the rest of
the application may consider — never something inherently trusted as safe. Only
validation/translation_preservation.py ever decides that.
"""

from dataclasses import dataclass

from app.ai.prompts import TRANSLATION_PROMPT_VERSION
from app.ai.provider import ExtractionProviderError, LLMProvider, ProviderMetadata
from app.patients.models import Language


@dataclass(frozen=True)
class TranslationAttempt:
    succeeded: bool
    translated_text: str | None
    metadata: ProviderMetadata | None
    prompt_version: str
    failure_reason: str | None


def run_translation(
    provider: LLMProvider, text: str, target_language: Language, structured_facts: dict
) -> TranslationAttempt:
    try:
        raw = provider.translate_patient_text(text, target_language, structured_facts)
    except ExtractionProviderError as exc:
        return TranslationAttempt(
            succeeded=False,
            translated_text=None,
            metadata=None,
            prompt_version=TRANSLATION_PROMPT_VERSION,
            failure_reason=str(exc),
        )

    if not raw.translated_text or not raw.translated_text.strip():
        return TranslationAttempt(
            succeeded=False,
            translated_text=None,
            metadata=raw.metadata,
            prompt_version=TRANSLATION_PROMPT_VERSION,
            failure_reason="Provider returned empty translation",
        )

    return TranslationAttempt(
        succeeded=True,
        translated_text=raw.translated_text.strip(),
        metadata=raw.metadata,
        prompt_version=TRANSLATION_PROMPT_VERSION,
        failure_reason=None,
    )
