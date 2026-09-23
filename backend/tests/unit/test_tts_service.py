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


def test_every_language_has_a_tts_voice():
    """A language offered in the UI but missing here would raise a KeyError at
    synthesis time — the "half-added language" failure this guards against."""
    from app.patients.models import Language
    from app.tts.service import VOICE_BY_LANGUAGE

    missing = [language.value for language in Language if language not in VOICE_BY_LANGUAGE]
    assert missing == [], f"languages with no TTS voice: {missing}"


def test_every_language_has_a_translation_prompt_name():
    from app.ai.prompts import TRANSLATION_LANGUAGE_NAMES
    from app.patients.models import Language

    missing = [language.value for language in Language if language.value not in TRANSLATION_LANGUAGE_NAMES]
    assert missing == [], f"languages with no translation prompt name: {missing}"


def test_every_tts_voice_name_exists_upstream():
    """The mapping test above only proves a voice is *assigned*. This proves
    the name is real — a typo'd voice would otherwise surface as a broken
    Listen button for whichever language got it, and only for patients who
    speak it. Hits the network; skipped if edge-tts is unreachable rather than
    failing the suite on someone's offline machine."""
    import asyncio

    import pytest

    import edge_tts

    from app.tts.service import VOICE_BY_LANGUAGE

    try:
        available = {voice["ShortName"] for voice in asyncio.run(edge_tts.list_voices())}
    except Exception as exc:  # noqa: BLE001 — offline/unreachable is not a test failure
        pytest.skip(f"edge-tts voice list unavailable: {exc}")

    invalid = {language.value: voice for language, voice in VOICE_BY_LANGUAGE.items() if voice not in available}
    assert invalid == {}, f"TTS voices that do not exist upstream: {invalid}"
