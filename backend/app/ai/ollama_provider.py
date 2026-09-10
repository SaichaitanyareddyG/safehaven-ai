"""Local-inference implementation of LLMProvider, via Ollama's REST API. Only
this module (and openai_provider, anthropic_provider, mock_provider) may
import an HTTP client for provider calls — see ai/provider.py.

No fallback: if OLLAMA_BASE_URL is unreachable, the model is missing, or the
response can't be parsed, this raises ExtractionProviderError exactly like the
other providers — which flows through the same safe-failure path (NEEDS_REVIEW
for extraction/generation, a failed translation row for translation). Phase 1
never silently falls back to a cloud provider.
"""

import json
import time

import httpx

from app.ai.prompts import (
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


class OllamaProvider:
    def __init__(self, base_url: str, model: str, temperature: float = 0.0):
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._temperature = temperature
        # Local inference is slower than a cloud API and has no queueing/retry
        # infrastructure behind it — a generous timeout avoids a slow-but-fine
        # local model being misclassified as a provider failure.
        self._client = httpx.Client(timeout=180.0)

    def generation_params(self) -> dict:
        """What was actually configured — recorded by the evaluation harness for
        reproducibility, never inferred or guessed after the fact."""
        return {"model": self._model, "temperature": self._temperature, "reasoning_effort": None}

    def _chat(self, system: str, user: str, response_format: dict | None) -> tuple[str, dict, int]:
        return self._chat_messages(
            [{"role": "system", "content": system}, {"role": "user", "content": user}], response_format
        )

    def _chat_messages(self, messages: list[dict], response_format: dict | None) -> tuple[str, dict, int]:
        started = time.monotonic()
        payload: dict = {
            "model": self._model,
            "messages": messages,
            "options": {"temperature": self._temperature},
            "stream": False,
        }
        if response_format is not None:
            payload["format"] = response_format

        try:
            response = self._client.post(f"{self._base_url}/api/chat", json=payload)
            response.raise_for_status()
        except httpx.ConnectError as exc:
            raise ExtractionProviderError(
                f"Could not reach Ollama at {self._base_url} — is `ollama serve` running?"
            ) from exc
        except Exception as exc:  # HTTP/network/model-not-found errors — never leaked raw to callers
            raise ExtractionProviderError(f"Ollama request failed: {exc}") from exc

        latency_ms = int((time.monotonic() - started) * 1000)

        try:
            data = response.json()
        except json.JSONDecodeError as exc:
            raise ExtractionProviderError(f"Ollama response was not valid JSON: {exc}") from exc

        content = data.get("message", {}).get("content")
        if not content or not content.strip():
            raise ExtractionProviderError("Ollama response did not include message content")

        token_usage = None
        if data.get("prompt_eval_count") is not None or data.get("eval_count") is not None:
            token_usage = {
                "prompt_tokens": data.get("prompt_eval_count", 0),
                "completion_tokens": data.get("eval_count", 0),
            }

        return content, token_usage, latency_ms

    def extract_instruction(self, text: str, context: dict | None = None) -> RawExtractionResponse:
        # Constrained structured output: Ollama enforces the response matches
        # this JSON schema (the SAME schema OpenAI/Anthropic's tool calls use —
        # see prompts.py) rather than us parsing free-form prose.
        content, token_usage, latency_ms = self._chat(SYSTEM_PROMPT, text, EXTRACTION_TOOL_SCHEMA)

        try:
            payload = json.loads(content)
        except json.JSONDecodeError as exc:
            raise ExtractionProviderError(f"Ollama structured output was not valid JSON: {exc}") from exc

        return RawExtractionResponse(
            payload=payload,
            metadata=ProviderMetadata(
                provider="ollama", model=self._model, request_id=None, latency_ms=latency_ms, token_usage=token_usage
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
        content, token_usage, latency_ms = self._chat(GENERATION_SYSTEM_PROMPT, user_message, response_format=None)

        return RawGenerationResponse(
            patient_text=content.strip(),
            metadata=ProviderMetadata(
                provider="ollama", model=self._model, request_id=None, latency_ms=latency_ms, token_usage=token_usage
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
        content, token_usage, latency_ms = self._chat(
            build_translation_system_prompt(language_name), user_message, response_format=None
        )

        return RawTranslationResponse(
            translated_text=content.strip(),
            metadata=ProviderMetadata(
                provider="ollama", model=self._model, request_id=None, latency_ms=latency_ms, token_usage=token_usage
            ),
        )

    def chat_with_patient(self, care_plan_summary: str, history: list[ChatTurn]) -> RawChatResponse:
        """No web search tool on this provider — grounded-only (care plan +
        curated facts), same as v2. PATIENT_CHAT_SYSTEM_PROMPT is written so
        this is correct behavior, not a missing feature: it only mentions
        using web search "if a web search tool is available to you," which it
        isn't here."""
        system_content = f"{PATIENT_CHAT_SYSTEM_PROMPT}\n\nPatient's current approved care plan:\n{care_plan_summary}"
        messages = [{"role": "system", "content": system_content}]
        messages.extend({"role": turn.role, "content": turn.text} for turn in history)
        content, token_usage, latency_ms = self._chat_messages(messages, response_format=None)

        return RawChatResponse(
            reply_text=content.strip(),
            metadata=ProviderMetadata(
                provider="ollama", model=self._model, request_id=None, latency_ms=latency_ms, token_usage=token_usage
            ),
        )

    def identify_medication_from_image(self, image_bytes: bytes, mime_type: str) -> RawImageIdentificationResponse:
        """Not implemented on this provider — see AnthropicProvider's
        identical method docstring for why (Module 2's image fallback is
        OpenAI-only in this build)."""
        raise ExtractionProviderError("Medication image identification is not implemented for the Ollama provider")
