"""Settings' own guardrail against booting with a placeholder JWT secret —
see app/core/config.py's _reject_placeholder_jwt_secret validator."""

import pytest

from app.core.config import Settings


def test_placeholder_jwt_secret_is_rejected():
    with pytest.raises(Exception):
        Settings(jwt_secret_key="dev-secret-change-me")


def test_alternate_placeholder_wording_is_also_rejected():
    with pytest.raises(Exception):
        Settings(jwt_secret_key="change-me-in-real-env-min-32-chars-please")


def test_real_random_secret_is_accepted():
    settings = Settings(jwt_secret_key="9f2c8e1a7b6d4f3e2c1a0b9d8e7f6c5b4a3d2e1f0c9b8a7d6e5f4c3b2a1d0e9f")
    assert settings.jwt_secret_key.startswith("9f2c8e1a")
