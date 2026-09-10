"""Anthropic implementation of LLMProvider. Only this module (and openai_provider,
mock_provider) may import a provider SDK — see ai/provider.py.
"""

import json
import time

import anthropic

from app.ai.prompts import (
    EXTRACTION_TOOL_NAME,
    EXTRACTION_TOOL_SCHEMA,
    GENERATION_SYSTEM_PROMPT,
    PATIENT_CHAT_SYSTEM_PROMPT,
    SYSTEM_PROMPT,
    TRANSLATION_LANGUAGE_NAMES,
    build_translation_system_prompt,
)
from app.ai.provider import (
    ChatTurn,
    ExtractionProviderError,
    ProviderMetadata,
    RawChatResponse,
    RawExtractionResponse,
    RawGenerationResponse,
    RawImageIdentificationResponse,
    RawTranslationResponse,
)
from app.instructions.models import InstructionType
from app.patients.models import Language


class AnthropicProvider:
    def __init__(self, api_key: str | None, model: str):
        if not api_key:
            raise ExtractionProviderError("ANTHROPIC_API_KEY is not configured")
        self._client = anthropic.Anthropic(api_key=api_key)
        self._model = model
        # Low, conservative, low-variability setting for structured extraction/
        # simplification/translation — not assumed to make output fully
        # deterministic (Anthropic's own docs note temperature=0 is not a
        # determinism guarantee), just the least-variable supported setting.
        self._temperature = 0.0

    def generation_params(self) -> dict:
        """What was actually configured — recorded by the evaluation harness for
        reproducibility, never inferred or guessed after the fact."""
        return {"model": self._model, "temperature": self._temperature, "reasoning_effort": None}

    def extract_instruction(self, text: str, context: dict | None = None) -> RawExtractionResponse:
        started = time.monotonic()
        try:
            response = self._client.messages.create(
                model=self._model,
                max_tokens=1024,
                temperature=self._temperature,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": text}],
                tools=[
                    {
                        "name": EXTRACTION_TOOL_NAME,
                        "description": "Record the structured extraction result.",
                        "input_schema": EXTRACTION_TOOL_SCHEMA,
                    }
                ],
                tool_choice={"type": "tool", "name": EXTRACTION_TOOL_NAME},
            )
        except Exception as exc:  # SDK/API/network errors — never leaked raw to callers
            raise ExtractionProviderError(f"Anthropic request failed: {exc}") from exc

        latency_ms = int((time.monotonic() - started) * 1000)

        # Only the tool call's structured input is ever retained — any reasoning or
        # prose the model returned alongside it is discarded, never stored/exposed.
        tool_use_block = next((block for block in response.content if block.type == "tool_use"), None)
        if tool_use_block is None:
            raise ExtractionProviderError("Anthropic response did not include a tool_use block")

        return RawExtractionResponse(
            payload=tool_use_block.input,
            metadata=ProviderMetadata(
                provider="anthropic",
                model=self._model,
                request_id=response.id,
                latency_ms=latency_ms,
                token_usage={
                    "input_tokens": response.usage.input_tokens,
                    "output_tokens": response.usage.output_tokens,
                },
            ),
        )

    def generate_patient_friendly(
        self, original_text: str, structured_facts: dict, instruction_type: InstructionType
    ) -> RawGenerationResponse:
        user_message = (
            f"Instruction type: {instruction_type.value}\n"
            f"Verified facts (JSON): {json.dumps(structured_facts)}\n\n"
            "Write the patient-facing explanation now, following all the rules above."
        )
        started = time.monotonic()
        try:
            response = self._client.messages.create(
                model=self._model,
                max_tokens=512,
                temperature=self._temperature,
                system=GENERATION_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_message}],
            )
        except Exception as exc:  # SDK/API/network errors — never leaked raw to callers
            raise ExtractionProviderError(f"Anthropic request failed: {exc}") from exc

        latency_ms = int((time.monotonic() - started) * 1000)

        # Only the response's text content is ever retained — no reasoning blocks
        # or other content types are inspected or stored.
        text_block = next((block for block in response.content if block.type == "text"), None)
        if text_block is None:
            raise ExtractionProviderError("Anthropic response did not include a text block")

        return RawGenerationResponse(
            patient_text=text_block.text,
            metadata=ProviderMetadata(
                provider="anthropic",
                model=self._model,
                request_id=response.id,
                latency_ms=latency_ms,
                token_usage={
                    "input_tokens": response.usage.input_tokens,
                    "output_tokens": response.usage.output_tokens,
                },
            ),
        )

    def translate_patient_text(
        self, text: str, target_language: Language, structured_facts: dict
    ) -> RawTranslationResponse:
        language_name = TRANSLATION_LANGUAGE_NAMES[target_language.value]
        user_message = (
            f"Reference facts (JSON, for your own double-checking only — translate the text below, "
            f"not this JSON): {json.dumps(structured_facts)}\n\n"
            f"Text to translate into {language_name}:\n{text}"
        )
        started = time.monotonic()
        try:
            response = self._client.messages.create(
                model=self._model,
                max_tokens=512,
                temperature=self._temperature,
                system=build_translation_system_prompt(language_name),
                messages=[{"role": "user", "content": user_message}],
            )
        except Exception as exc:  # SDK/API/network errors — never leaked raw to callers
            raise ExtractionProviderError(f"Anthropic request failed: {exc}") from exc

        latency_ms = int((time.monotonic() - started) * 1000)

        text_block = next((block for block in response.content if block.type == "text"), None)
        if text_block is None:
            raise ExtractionProviderError("Anthropic response did not include a text block")

        return RawTranslationResponse(
            translated_text=text_block.text,
            metadata=ProviderMetadata(
                provider="anthropic",
                model=self._model,
                request_id=response.id,
                latency_ms=latency_ms,
                token_usage={
                    "input_tokens": response.usage.input_tokens,
                    "output_tokens": response.usage.output_tokens,
                },
            ),
        )

    def chat_with_patient(self, care_plan_summary: str, history: list[ChatTurn]) -> RawChatResponse:
        """No web search tool on this provider — grounded-only (care plan +
        curated facts), same as v2. PATIENT_CHAT_SYSTEM_PROMPT is written so
        this is correct behavior, not a missing feature: it only mentions
        using web search "if a web search tool is available to you," which it
        isn't here."""
        system_content = f"{PATIENT_CHAT_SYSTEM_PROMPT}\n\nPatient's current approved care plan:\n{care_plan_summary}"
        messages = [{"role": turn.role, "content": turn.text} for turn in history]

        started = time.monotonic()
        try:
            response = self._client.messages.create(
                model=self._model,
                max_tokens=400,
                temperature=self._temperature,
                system=system_content,
                messages=messages,
            )
        except Exception as exc:  # SDK/API/network errors — never leaked raw to callers
            raise ExtractionProviderError(f"Anthropic request failed: {exc}") from exc

        latency_ms = int((time.monotonic() - started) * 1000)

        text_block = next((block for block in response.content if block.type == "text"), None)
        if text_block is None:
            raise ExtractionProviderError("Anthropic response did not include a text block")

        return RawChatResponse(
            reply_text=text_block.text.strip(),
            metadata=ProviderMetadata(
                provider="anthropic",
                model=self._model,
                request_id=response.id,
                latency_ms=latency_ms,
                token_usage={
                    "input_tokens": response.usage.input_tokens,
                    "output_tokens": response.usage.output_tokens,
                },
            ),
        )

    def identify_medication_from_image(self, image_bytes: bytes, mime_type: str) -> RawImageIdentificationResponse:
        """Not implemented on this provider — Module 2's image fallback is
        only wired up for OpenAI today (matching chat_with_patient's web
        search: scoped to the one provider actually used in this prototype,
        not built out across all four for a feature nothing exercises via
        Anthropic). Claude models are multimodal and could support this
        later without an architectural change — just not built now."""
        raise ExtractionProviderError("Medication image identification is not implemented for the Anthropic provider")
