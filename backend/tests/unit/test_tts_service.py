import asyncio

import pytest

from app.patients.models import Language
from app.tts.service import MAX_TEXT_LENGTH, TextTooLongError, synthesize_speech


def test_text_too_long_raises_before_any_network_call():
    """The length guard must run before contacting the TTS service at all —
    this test has no network access and must still pass."""
    with pytest.raises(TextTooLongError):
        asyncio.run(synthesize_speech("x" * (MAX_TEXT_LENGTH + 1), Language.ENGLISH))


def test_text_at_exact_limit_does_not_raise_length_error():
    """Boundary check: exactly MAX_TEXT_LENGTH must not trip the guard (only
    checking that TextTooLongError specifically isn't raised here — this
    still reaches the network and is skipped in offline/CI environments)."""
    try:
        asyncio.run(synthesize_speech("x" * MAX_TEXT_LENGTH, Language.ENGLISH))
    except TextTooLongError:
        pytest.fail("MAX_TEXT_LENGTH itself should not trigger TextTooLongError")
    except Exception:
        pytest.skip("No network access to the TTS service in this environment")
