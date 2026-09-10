"""Text-to-speech for the patient care page. Audio is an accessibility aid,
not a source of truth — the approved text itself remains canonical regardless
of whether synthesis succeeds; see patient_access/router.py's audio endpoint,
which never blocks the patient from reading the text if this fails.

Uses edge-tts (Microsoft Edge's neural voices) rather than a native browser
voice: patient devices vary wildly in which Telugu/Hindi voices (if any) they
have installed, so browser-side speechSynthesis was inconsistent. This is
free and requires no API key, but is an unofficial/reverse-engineered client
of Microsoft's service, not a contracted API — acceptable for a prototype.
"""

import edge_tts

from app.patients.models import Language

MAX_TEXT_LENGTH = 2000  # generous for a single instruction's patient-facing text; guards against misuse of a free upstream service

VOICE_BY_LANGUAGE: dict[Language, str] = {
    Language.ENGLISH: "en-US-AriaNeural",
    Language.TELUGU: "te-IN-ShrutiNeural",
    Language.HINDI: "hi-IN-SwaraNeural",
}


class TextTooLongError(Exception):
    pass


async def synthesize_speech(text: str, language: Language) -> bytes:
    if len(text) > MAX_TEXT_LENGTH:
        raise TextTooLongError(f"Text exceeds {MAX_TEXT_LENGTH} characters")

    voice = VOICE_BY_LANGUAGE[language]
    communicate = edge_tts.Communicate(text, voice)

    audio_chunks: list[bytes] = []
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            audio_chunks.append(chunk["data"])

    return b"".join(audio_chunks)
