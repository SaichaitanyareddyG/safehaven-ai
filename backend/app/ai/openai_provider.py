"""OpenAI implementation of LLMProvider. Only this module (and anthropic_provider,
mock_provider) may import a provider SDK — see ai/provider.py.
"""

import base64
import json
import time

import openai

from app.ai.prompts import (
    EXTRACTION_TOOL_NAME,
    EXTRACTION_TOOL_SCHEMA,
    GENERATION_SYSTEM_PROMPT,
    IMAGE_IDENTIFICATION_SYSTEM_PROMPT,
    IMAGE_IDENTIFICATION_TOOL_NAME,
    IMAGE_IDENTIFICATION_TOOL_SCHEMA,
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

# Trusted medical reference sites only — a deliberate safety choice, not the
# open web. allowed_domains implicitly covers subdomains (e.g. nih.gov also
# covers ncbi.nlm.nih.gov / pubmed).
_TRUSTED_MEDICAL_DOMAINS = ["medlineplus.gov", "mayoclinic.org", "cdc.gov", "nih.gov"]


def _is_reasoning_model(model: str) -> bool:
    """GPT-5/o-series models are reasoning models that, by default, spend a
    (billed, latency-costly) hidden reasoning-token budget even on a small
    structured-extraction task that doesn't need it. Passing a low
    reasoning_effort (via extra_body — this SDK version predates it as a typed
    chat.completions.create() parameter, but the API accepts it) cuts that
    overhead to near zero for a task like ours: structured extraction,
    simplification, and translation, not open-ended reasoning."""
    return model.startswith(("gpt-5", "o1", "o3", "o4"))


class OpenAIProvider:
    def __init__(self, api_key: str | None, model: str, vision_model: str | None = None):
        if not api_key:
            raise ExtractionProviderError("OPENAI_API_KEY is not configured")
        self._client = openai.OpenAI(api_key=api_key)
        self._model = model
        self._is_reasoning_model = _is_reasoning_model(model)
        self._extra_body = {"reasoning_effort": "minimal"} if self._is_reasoning_model else None

        # A separate, independently-configurable model for
        # identify_medication_from_image (Module 2's barcode-failure
        # fallback) — the one call where photo-reading precision matters
        # most and volume is lowest, unlike the high-volume extraction/
        # generation/translation calls above tuned for cost/speed via
        # reasoning_effort="minimal". Defaults to the same model when unset,
        # so this is a no-op unless OPENAI_VISION_MODEL is explicitly set.
        self._vision_model = vision_model or model
        self._vision_is_reasoning_model = _is_reasoning_model(self._vision_model)
        self._vision_extra_body = {"reasoning_effort": "low"} if self._vision_is_reasoning_model else None
        self._vision_temperature = None if self._vision_is_reasoning_model else 0.2
        # Reasoning models (gpt-5/o-series) reject any non-default temperature —
        # the API 400s with "Only the default (1) value is supported" — so
        # reasoning_effort is the only conservative-settings lever available for
        # them. Non-reasoning models get an explicit low, low-variability value
        # rather than an unstated default, per Step 10's requirement to record
        # and control generation parameters for structured clinical output.
        self._temperature = None if self._is_reasoning_model else 0.2

    def generation_params(self) -> dict:
        """What was actually configured — recorded by the evaluation harness for
        reproducibility, never inferred or guessed after the fact."""
        return {
            "model": self._model,
            "temperature": self._temperature if self._temperature is not None else "default (reasoning model; custom temperature unsupported)",
            "reasoning_effort": self._extra_body.get("reasoning_effort") if self._extra_body else None,
        }

    def _call_kwargs(self) -> dict:
        kwargs: dict = {}
        if self._extra_body is not None:
            kwargs["extra_body"] = self._extra_body
        if self._temperature is not None:
            kwargs["temperature"] = self._temperature
        return kwargs

    def _vision_call_kwargs(self) -> dict:
        kwargs: dict = {}
        if self._vision_extra_body is not None:
            kwargs["extra_body"] = self._vision_extra_body
        if self._vision_temperature is not None:
            kwargs["temperature"] = self._vision_temperature
        return kwargs

    def extract_instruction(self, text: str, context: dict | None = None) -> RawExtractionResponse:
        started = time.monotonic()
        try:
            response = self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": text},
                ],
                tools=[
                    {
                        "type": "function",
                        "function": {
                            "name": EXTRACTION_TOOL_NAME,
                            "description": "Record the structured extraction result.",
                            "parameters": EXTRACTION_TOOL_SCHEMA,
                            "strict": True,
                        },
                    }
                ],
                tool_choice={"type": "function", "function": {"name": EXTRACTION_TOOL_NAME}},
                **self._call_kwargs(),
            )
        except Exception as exc:  # SDK/API/network errors — never leaked raw to callers
            raise ExtractionProviderError(f"OpenAI request failed: {exc}") from exc

        latency_ms = int((time.monotonic() - started) * 1000)

        # Only the tool call's structured arguments are ever retained — any prose
        # content the model returned alongside it is discarded, never stored/exposed.
        message = response.choices[0].message
        tool_calls = message.tool_calls or []
        if not tool_calls:
            raise ExtractionProviderError("OpenAI response did not include a tool call")

        try:
            payload = json.loads(tool_calls[0].function.arguments)
        except json.JSONDecodeError as exc:
            raise ExtractionProviderError(f"OpenAI tool arguments were not valid JSON: {exc}") from exc

        token_usage = (
            {"prompt_tokens": response.usage.prompt_tokens, "completion_tokens": response.usage.completion_tokens}
            if response.usage
            else None
        )

        return RawExtractionResponse(
            payload=payload,
            metadata=ProviderMetadata(
                provider="openai",
                model=self._model,
                request_id=response.id,
                latency_ms=latency_ms,
                token_usage=token_usage,
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
            response = self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": GENERATION_SYSTEM_PROMPT},
                    {"role": "user", "content": user_message},
                ],
                **self._call_kwargs(),
            )
        except Exception as exc:  # SDK/API/network errors — never leaked raw to callers
            raise ExtractionProviderError(f"OpenAI request failed: {exc}") from exc

        latency_ms = int((time.monotonic() - started) * 1000)

        # Only the message's text content is ever retained.
        content = response.choices[0].message.content
        if not content:
            raise ExtractionProviderError("OpenAI response did not include message content")

        token_usage = (
            {"prompt_tokens": response.usage.prompt_tokens, "completion_tokens": response.usage.completion_tokens}
            if response.usage
            else None
        )

        return RawGenerationResponse(
            patient_text=content,
            metadata=ProviderMetadata(
                provider="openai",
                model=self._model,
                request_id=response.id,
                latency_ms=latency_ms,
                token_usage=token_usage,
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
            response = self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": build_translation_system_prompt(language_name)},
                    {"role": "user", "content": user_message},
                ],
                **self._call_kwargs(),
            )
        except Exception as exc:  # SDK/API/network errors — never leaked raw to callers
            raise ExtractionProviderError(f"OpenAI request failed: {exc}") from exc

        latency_ms = int((time.monotonic() - started) * 1000)

        content = response.choices[0].message.content
        if not content:
            raise ExtractionProviderError("OpenAI response did not include message content")

        token_usage = (
            {"prompt_tokens": response.usage.prompt_tokens, "completion_tokens": response.usage.completion_tokens}
            if response.usage
            else None
        )

        return RawTranslationResponse(
            translated_text=content,
            metadata=ProviderMetadata(
                provider="openai",
                model=self._model,
                request_id=response.id,
                latency_ms=latency_ms,
                token_usage=token_usage,
            ),
        )

    def chat_with_patient(self, care_plan_summary: str, history: list[ChatTurn]) -> RawChatResponse:
        """Uses the Responses API (not Chat Completions, used elsewhere in this
        file) — only the Responses API supports the web_search tool with
        domain filtering, which is what restricts this to trusted medical
        sites only rather than the open web (see _TRUSTED_MEDICAL_DOMAINS)."""
        system_content = f"{PATIENT_CHAT_SYSTEM_PROMPT}\n\nPatient's current approved care plan:\n{care_plan_summary}"
        input_items = [{"role": turn.role, "content": turn.text} for turn in history]

        kwargs: dict = {}
        if self._is_reasoning_model:
            # The API rejects the web_search tool at reasoning.effort="minimal"
            # (used elsewhere in this file for extraction/generation, which
            # don't need real reasoning) — "low" is the minimum effort the API
            # accepts alongside a tool.
            kwargs["reasoning"] = {"effort": "low"}
        if self._temperature is not None:
            kwargs["temperature"] = self._temperature

        started = time.monotonic()
        try:
            response = self._client.responses.create(
                model=self._model,
                instructions=system_content,
                input=input_items,
                tools=[{"type": "web_search", "filters": {"allowed_domains": _TRUSTED_MEDICAL_DOMAINS}}],
                tool_choice="auto",
                include=["web_search_call.action.sources"],
                **kwargs,
            )
        except Exception as exc:  # SDK/API/network errors — never leaked raw to callers
            raise ExtractionProviderError(f"OpenAI request failed: {exc}") from exc

        latency_ms = int((time.monotonic() - started) * 1000)

        content = response.output_text
        if not content:
            raise ExtractionProviderError("OpenAI response did not include message content")

        web_search_used = any(getattr(item, "type", None) == "web_search_call" for item in response.output)

        token_usage = (
            {"input_tokens": response.usage.input_tokens, "output_tokens": response.usage.output_tokens}
            if response.usage
            else None
        )

        return RawChatResponse(
            reply_text=content.strip(),
            metadata=ProviderMetadata(
                provider="openai",
                model=self._model,
                request_id=response.id,
                latency_ms=latency_ms,
                token_usage=token_usage,
            ),
            web_search_used=web_search_used,
        )

    def identify_medication_from_image(self, image_bytes: bytes, mime_type: str) -> RawImageIdentificationResponse:
        """Vision-as-text-extraction only — see IMAGE_IDENTIFICATION_SYSTEM_PROMPT
        and RawImageIdentificationResponse's docstrings for why this can never
        be the safety decision itself. Uses Chat Completions (not the
        Responses API used by chat_with_patient) — vision input via
        image_url content parts is supported here and needs no additional
        tool beyond the same tool-calling pattern extract_instruction uses."""
        image_data_url = f"data:{mime_type};base64,{base64.b64encode(image_bytes).decode('ascii')}"
        started = time.monotonic()
        try:
            response = self._client.chat.completions.create(
                model=self._vision_model,
                messages=[
                    {"role": "system", "content": IMAGE_IDENTIFICATION_SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": "Identify the medication visible in this label photo."},
                            {"type": "image_url", "image_url": {"url": image_data_url}},
                        ],
                    },
                ],
                tools=[
                    {
                        "type": "function",
                        "function": {
                            "name": IMAGE_IDENTIFICATION_TOOL_NAME,
                            "description": "Record what is legible on the medication label.",
                            "parameters": IMAGE_IDENTIFICATION_TOOL_SCHEMA,
                            "strict": True,
                        },
                    }
                ],
                tool_choice={"type": "function", "function": {"name": IMAGE_IDENTIFICATION_TOOL_NAME}},
                **self._vision_call_kwargs(),
            )
        except Exception as exc:  # SDK/API/network errors — never leaked raw to callers
            raise ExtractionProviderError(f"OpenAI request failed: {exc}") from exc

        latency_ms = int((time.monotonic() - started) * 1000)

        message = response.choices[0].message
        tool_calls = message.tool_calls or []
        if not tool_calls:
            raise ExtractionProviderError("OpenAI response did not include a tool call")

        try:
            payload = json.loads(tool_calls[0].function.arguments)
        except json.JSONDecodeError as exc:
            raise ExtractionProviderError(f"OpenAI tool arguments were not valid JSON: {exc}") from exc

        token_usage = (
            {"prompt_tokens": response.usage.prompt_tokens, "completion_tokens": response.usage.completion_tokens}
            if response.usage
            else None
        )

        return RawImageIdentificationResponse(
            medication_name=payload.get("medication_name"),
            strength_value=payload.get("strength_value"),
            strength_unit=payload.get("strength_unit"),
            formulation=payload.get("formulation"),
            route=payload.get("route"),
            confidence=payload.get("confidence", "low"),
            metadata=ProviderMetadata(
                provider="openai",
                model=self._vision_model,
                request_id=response.id,
                latency_ms=latency_ms,
                token_usage=token_usage,
            ),
        )
