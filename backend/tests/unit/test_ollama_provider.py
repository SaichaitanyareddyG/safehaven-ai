"""Unit tests for OllamaProvider — mocks the HTTP layer entirely (no real
Ollama server needed), covering the safe-failure paths a local provider must
have: unreachable server, malformed structured output, empty response. No
special trust for local models — the same ExtractionProviderError contract as
openai_provider.py/anthropic_provider.py."""

import json
from unittest.mock import MagicMock, Mock

import httpx
import pytest

from app.ai.ollama_provider import OllamaProvider
from app.ai.provider import ExtractionProviderError
from app.instructions.models import InstructionType
from app.patients.models import Language


def _provider() -> OllamaProvider:
    return OllamaProvider(base_url="http://localhost:11434", model="qwen3.5:9b", temperature=0.0)


def _mock_response(content: str, prompt_tokens: int = 10, completion_tokens: int = 5) -> Mock:
    response = Mock()
    response.raise_for_status = Mock()
    response.json.return_value = {
        "message": {"content": content},
        "prompt_eval_count": prompt_tokens,
        "eval_count": completion_tokens,
    }
    return response


def test_generation_params_reflects_configuration():
    provider = OllamaProvider(base_url="http://localhost:11434", model="gemma3:12b", temperature=0.2)

    params = provider.generation_params()

    assert params == {"model": "gemma3:12b", "temperature": 0.2, "reasoning_effort": None}


def test_extract_instruction_parses_structured_json():
    provider = _provider()
    payload = {
        "instruction_type": "MEDICATION",
        "facts": {"medication_name": "Metoprolol", "dose_value": 25.0, "dose_unit": "mg"},
        "ambiguities": [],
    }
    provider._client.post = Mock(return_value=_mock_response(json.dumps(payload)))

    result = provider.extract_instruction("Take Metoprolol 25 mg orally twice daily.")

    assert result.payload == payload
    assert result.metadata.provider == "ollama"
    assert result.metadata.model == "qwen3.5:9b"
    assert result.metadata.token_usage == {"prompt_tokens": 10, "completion_tokens": 5}


def test_extract_instruction_sends_json_schema_format():
    """Structured output is requested via the schema, not left to prose parsing."""
    provider = _provider()
    provider._client.post = Mock(
        return_value=_mock_response(json.dumps({"instruction_type": "GENERAL", "facts": {}, "ambiguities": []}))
    )

    provider.extract_instruction("Some instruction.")

    call_kwargs = provider._client.post.call_args.kwargs
    assert "format" in call_kwargs["json"]
    assert call_kwargs["json"]["format"]["type"] == "object"


def test_connection_error_raises_provider_error_no_fallback():
    """If Ollama is unreachable, this must fail safely (ExtractionProviderError,
    which flows into NEEDS_REVIEW) — never silently fall back to a cloud
    provider."""
    provider = _provider()
    provider._client.post = Mock(side_effect=httpx.ConnectError("connection refused"))

    with pytest.raises(ExtractionProviderError, match="Could not reach Ollama"):
        provider.extract_instruction("Take Metoprolol 25 mg orally twice daily.")


def test_malformed_json_content_raises_provider_error():
    provider = _provider()
    provider._client.post = Mock(return_value=_mock_response("this is not valid json {"))

    with pytest.raises(ExtractionProviderError, match="not valid JSON"):
        provider.extract_instruction("Take Metoprolol 25 mg orally twice daily.")


def test_empty_content_raises_provider_error():
    provider = _provider()
    response = Mock()
    response.raise_for_status = Mock()
    response.json.return_value = {"message": {"content": ""}}
    provider._client.post = Mock(return_value=response)

    with pytest.raises(ExtractionProviderError, match="did not include message content"):
        provider.extract_instruction("Take Metoprolol 25 mg orally twice daily.")


def test_http_error_status_raises_provider_error():
    """E.g. model not pulled — Ollama returns a 404/500, never a fallback."""
    provider = _provider()
    response = Mock()
    response.raise_for_status = Mock(side_effect=httpx.HTTPStatusError("not found", request=MagicMock(), response=MagicMock(status_code=404)))
    provider._client.post = Mock(return_value=response)

    with pytest.raises(ExtractionProviderError):
        provider.extract_instruction("Take Metoprolol 25 mg orally twice daily.")


def test_generate_patient_friendly_returns_plain_text():
    provider = _provider()
    provider._client.post = Mock(return_value=_mock_response("Take Metoprolol 25 mg by mouth twice daily."))

    result = provider.generate_patient_friendly(
        "Take Metoprolol 25 mg orally twice daily.",
        {"medication_name": "Metoprolol", "dose_value": 25.0, "dose_unit": "mg"},
        InstructionType.MEDICATION,
    )

    assert result.patient_text == "Take Metoprolol 25 mg by mouth twice daily."
    assert result.metadata.provider == "ollama"

    # Generation/translation are plain text — no format constraint should be sent.
    call_kwargs = provider._client.post.call_args.kwargs
    assert "format" not in call_kwargs["json"]


def test_translate_patient_text_returns_plain_text():
    provider = _provider()
    provider._client.post = Mock(return_value=_mock_response("మెటోప్రోలాల్ 25 mg రోజుకు రెండుసార్లు తీసుకోండి."))

    result = provider.translate_patient_text(
        "Take Metoprolol 25 mg by mouth twice daily.",
        Language.TELUGU,
        {"medication_name": "Metoprolol", "dose_value": 25.0, "dose_unit": "mg"},
    )

    assert "25" in result.translated_text
    assert result.metadata.provider == "ollama"
