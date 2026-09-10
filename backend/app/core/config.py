from functools import lru_cache
from typing import Annotated

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

# Substrings that only ever appear in a placeholder secret, never a real
# generated one (e.g. `openssl rand -hex 32`) — checked case-insensitively.
# Catches both this class's own default and the placeholder text a prior
# .env carried ("change-me-in-real-env-min-32-chars-please"), which passed a
# naive length check but was still never rotated to a real secret.
_JWT_SECRET_PLACEHOLDER_MARKERS = ("change-me", "change_me", "changeme")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    environment: str = "development"

    database_url: str = "postgresql+psycopg2://safehaven:safehaven@localhost:5432/safehaven"
    test_database_url: str = "postgresql+psycopg2://safehaven:safehaven@localhost:5432/safehaven_test"
    # "disable" is fine for a local Postgres on localhost (no network to
    # intercept); set to "require" or "verify-full" the moment the database
    # isn't on the same host as the app anymore. See app/core/db.py.
    database_ssl_mode: str = "disable"

    # "dev" is the only implemented provider in Phase 1. A CognitoAuthProvider can be
    # added later behind the same AuthProvider protocol without touching route code.
    auth_provider: str = "dev"
    jwt_secret_key: str = "dev-secret-change-me"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 8

    # "mock" | "openai" | "anthropic" | "ollama" — see app/ai/provider.py's get_llm_provider().
    llm_provider: str = "mock"
    openai_api_key: str | None = None
    openai_model: str = "gpt-4o-mini"
    # Only the medication-label image-identification step (Module 2's
    # barcode-failure fallback, see app/ai/openai_provider.py's
    # identify_medication_from_image) reads this — every other OpenAI call
    # (extraction/generation/translation/chat) always uses openai_model.
    # Defaults to openai_model when unset, so leaving this blank is a no-op,
    # not a silent behavior change.
    openai_vision_model: str | None = None
    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-sonnet-5"
    # Local inference via Ollama — never falls back to a cloud provider if
    # unreachable/misconfigured (see ollama_provider.py); that failure flows
    # through the same ExtractionProviderError -> NEEDS_REVIEW path as any
    # other provider failure, by design (Phase 1 has no automatic fallback).
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "qwen3.5:9b"
    ollama_temperature: float = 0.0
    # Clinical text sent to/from the LLM may contain PHI — never persisted by default.
    store_raw_llm_data: bool = False

    cors_origins: Annotated[list[str], NoDecode] = ["http://localhost:5173"]

    # Patient care-access token lifetime. Also the cap on a clinician-requested
    # shorter expiry (see patient_access/schemas.py's CareAccessTokenCreate) —
    # there is no way to mint a longer-lived or permanent token.
    care_token_ttl_hours: int = 24
    # CARE_PLAN_VIEWED is deduplicated per-token within this window so a patient
    # re-opening/refreshing their care link doesn't spam the audit trail.
    care_plan_view_dedup_minutes: int = 5

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_cors_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @model_validator(mode="after")
    def _reject_placeholder_jwt_secret(self) -> "Settings":
        lowered = self.jwt_secret_key.lower()
        if any(marker in lowered for marker in _JWT_SECRET_PLACEHOLDER_MARKERS):
            raise ValueError(
                "JWT_SECRET_KEY is still a placeholder value. Generate a real secret "
                "(e.g. `openssl rand -hex 32`) and set it in .env before starting the app."
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
