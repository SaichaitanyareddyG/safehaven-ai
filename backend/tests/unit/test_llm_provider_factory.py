"""get_llm_provider() factory selection — each LLM_PROVIDER value must resolve
to the correct concrete provider class, with no silent fallback between them."""

from unittest.mock import patch

import pytest

from app.ai.mock_provider import MockLLMProvider
from app.ai.provider import get_llm_provider
from app.core.config import Settings


def _settings(**overrides) -> Settings:
    return Settings(**overrides)


def test_mock_provider_selected_by_default():
    with patch("app.ai.provider.get_settings", return_value=_settings(llm_provider="mock")):
        provider = get_llm_provider()
    assert isinstance(provider, MockLLMProvider)


def test_ollama_provider_selected_and_configured():
    from app.ai.ollama_provider import OllamaProvider

    settings = _settings(
        llm_provider="ollama",
        ollama_base_url="http://localhost:11434",
        ollama_model="qwen3.5:9b",
        ollama_temperature=0.0,
    )
    with patch("app.ai.provider.get_settings", return_value=settings):
        provider = get_llm_provider()

    assert isinstance(provider, OllamaProvider)
    assert provider.generation_params()["model"] == "qwen3.5:9b"


def test_openai_provider_requires_api_key():
    from app.ai.provider import ExtractionProviderError

    settings = _settings(llm_provider="openai", openai_api_key=None)
    with patch("app.ai.provider.get_settings", return_value=settings):
        with pytest.raises(ExtractionProviderError):
            get_llm_provider()


def test_unknown_provider_raises():
    settings = _settings(llm_provider="not-a-real-provider")
    with patch("app.ai.provider.get_settings", return_value=settings):
        with pytest.raises(NotImplementedError):
            get_llm_provider()
