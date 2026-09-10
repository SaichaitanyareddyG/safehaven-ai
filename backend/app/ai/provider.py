"""LLMProvider abstraction. Business logic (instructions/service.py,
ai/extraction_service.py, ai/generation_service.py) depends only on this module —
never on a concrete SDK. Concrete provider modules (mock/openai/anthropic) are the
only files allowed to import a provider SDK, and are only imported lazily, by
get_llm_provider(), based on configuration.
"""

from dataclasses import dataclass
from typing import Protocol

from app.core.config import get_settings
from app.instructions.models import InstructionType
from app.patients.models import Language


class ExtractionProviderError(Exception):
    """Any provider-level failure: network error, API error, timeout, missing
    credentials, or a response that doesn't even have the expected envelope shape.
    Used for both extraction and generation calls — callers treat either uniformly
    as a failed attempt, never a reason to fabricate or guess at a result."""


@dataclass(frozen=True)
class ProviderMetadata:
    provider: str
    model: str
    request_id: str | None
    latency_ms: int
    token_usage: dict | None


@dataclass(frozen=True)
class RawExtractionResponse:
    """What a provider hands back: parsed-but-not-yet-schema-validated JSON, plus
    metadata. Schema validation happens once, uniformly, in extraction_service.py —
    not duplicated per provider."""

    payload: dict
    metadata: ProviderMetadata


@dataclass(frozen=True)
class RawGenerationResponse:
    """What a provider hands back from generation: plain patient-facing text, plus
    metadata. Never assumed safe — see validation/fact_preservation.py, which
    always re-checks it independently before anything downstream trusts it."""

    patient_text: str
    metadata: ProviderMetadata


@dataclass(frozen=True)
class RawTranslationResponse:
    """What a provider hands back from translation: plain translated text, plus
    metadata. Never assumed safe — see validation/translation_preservation.py,
    which always re-checks it independently before anything downstream trusts it."""

    translated_text: str
    metadata: ProviderMetadata


@dataclass(frozen=True)
class ChatTurn:
    role: str  # "user" | "assistant" — prior turns only, never a flagged fixed-message turn (see patient_chat/service.py)
    text: str


@dataclass(frozen=True)
class RawChatResponse:
    """What a provider hands back from a patient chat turn. Bound by
    PATIENT_CHAT_SYSTEM_PROMPT to answer only from the approved context it is
    given (the patient's own care plan + curated medication reference facts)
    — plus, on providers that support it, a live web search restricted to a
    small allow-list of trusted medical sites — never open-ended general
    knowledge, and a fixed decline when none of that covers the question.
    Like every prompt-enforced rule, this is probabilistic, not deterministic;
    see app/patient_chat/service.py for the two hard, deterministic gates
    (emergency, treatment-change) that run before a message ever reaches this
    call at all.

    web_search_used records whether this specific reply was generated using
    the live web search tool (only OpenAI's provider currently supports it —
    every other provider always returns False here) — surfaced to the
    clinician-facing transcript so it's visible when an answer went beyond
    this app's own care plan and curated data."""

    reply_text: str
    metadata: ProviderMetadata
    web_search_used: bool = False


@dataclass(frozen=True)
class RawImageIdentificationResponse:
    """What a provider hands back from reading a medication label photo —
    Module 2's barcode-failure fallback (see
    app/medication_verification/service.py). A pure text-extraction aid,
    never a safety decision: every field is only what was legible, null
    otherwise, and this response is ALWAYS treated as an unconfirmed
    candidate — the nurse must review and confirm it before the confirmed
    fields ever enter the deterministic verification engine, and even then
    the result is permanently labeled as image-identified rather than
    barcode-verified. Not every provider implements this (see each
    provider's docstring on the method)."""

    medication_name: str | None
    strength_value: float | None
    strength_unit: str | None
    formulation: str | None
    route: str | None
    confidence: str  # "high" | "low"
    metadata: ProviderMetadata


class LLMProvider(Protocol):
    def extract_instruction(self, text: str, context: dict | None = None) -> RawExtractionResponse: ...

    def generate_patient_friendly(
        self, original_text: str, structured_facts: dict, instruction_type: InstructionType
    ) -> RawGenerationResponse: ...

    def translate_patient_text(
        self, text: str, target_language: Language, structured_facts: dict
    ) -> RawTranslationResponse: ...

    def chat_with_patient(self, care_plan_summary: str, history: list[ChatTurn]) -> RawChatResponse: ...

    def identify_medication_from_image(self, image_bytes: bytes, mime_type: str) -> RawImageIdentificationResponse: ...


def get_llm_provider() -> LLMProvider:
    settings = get_settings()

    if settings.llm_provider == "mock":
        from app.ai.mock_provider import MockLLMProvider

        return MockLLMProvider()

    if settings.llm_provider == "openai":
        from app.ai.openai_provider import OpenAIProvider

        return OpenAIProvider(
            api_key=settings.openai_api_key, model=settings.openai_model, vision_model=settings.openai_vision_model
        )

    if settings.llm_provider == "anthropic":
        from app.ai.anthropic_provider import AnthropicProvider

        return AnthropicProvider(api_key=settings.anthropic_api_key, model=settings.anthropic_model)

    if settings.llm_provider == "ollama":
        from app.ai.ollama_provider import OllamaProvider

        return OllamaProvider(
            base_url=settings.ollama_base_url, model=settings.ollama_model, temperature=settings.ollama_temperature
        )

    raise NotImplementedError(f"Unknown LLM_PROVIDER: {settings.llm_provider!r}")
