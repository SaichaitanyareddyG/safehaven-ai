"""Module 3 — "Talk to SafeHaven": the wearable band's voice assistant.

The patient presses the band's side button and speaks; the band sends the
recording here and plays back the answer, then listens for a follow-up. A
conversation keeps its last few exchanges IN MEMORY ONLY (never stored),
forgotten after CONVERSATION_TTL_S or when the band starts a new one, so
"and when do I take it?" can follow "what is my metoprolol for?".

    recording ─► speech to text ─► FIXED RULES ─► model ─► voice ─► band
                 (whisper.cpp)      urgent?        (Ollama)  (Piper)
                                    medicine change?
                                    practical request?

Safety, in order:
1. Fixed rules run first, on the transcript. Urgent words ("I fell", "I'm
   dizzy", "chest pain") raise a TALK_URGENT alert and get a fixed reply; the
   model is not asked. Medicine-change questions get a fixed redirect. An
   alert therefore never depends on the model getting it right (the model
   comparison showed a small model treating "dizzy" as non-urgent).
2. The model answers only from the patient's approved care plan, and may tag
   its reply [NURSE] or [REQUEST]; the server raises the alert, not the model.
3. Any service failing fails safe: a fixed "I can't answer right now", and an
   alert the fixed rules already decided on is raised regardless.

Privacy: the three services are LOCAL (core/config.py, band_talk_*); nothing
the patient says leaves the hospital. Neither the recording nor the transcript
is stored, and the logs carry only timings and the outcome, never the words.
"""

from __future__ import annotations

import base64
import io
import logging
import math
import re
import threading
import time
import uuid
import wave
from dataclasses import dataclass, field

import httpx
from sqlalchemy.orm import Session

from app.ai.prompts import BAND_TALK_SYSTEM_PROMPT
from app.core.config import get_settings
from app.patient_chat.service import (
    _EMERGENCY_PATTERNS,
    _TREATMENT_CHANGE_PATTERNS,
    _build_care_plan_summary,
)
from app.wearables import service
from app.wearables.models import DeviceAssignment, SensorEventType, WearableDevice
from app.wearables.schemas import SensorEventSubmit

logger = logging.getLogger(__name__)


class NotAssignedError(Exception):
    """The band is not monitoring anyone: there is no care plan to talk about
    and no patient an alert could reach."""


# ── Fixed rules ──────────────────────────────────────────────────────────────
# On top of patient chat's emergency phrases: what a patient on a ward is
# likely to say when they need a nurse now.
_BAND_URGENT_PATTERNS = [
    re.compile(p, re.IGNORECASE)
    for p in [
        r"\bdizz",
        r"\bfaint",
        r"\b(i|i've|i have|just)\s+(fell|fallen)\b",
        r"\bfell\s+(over|down|out)\b",
        r"\bon the floor\b",
        r"\bcan.?t get up\b",
        r"\bheart\s+(is\s+)?(racing|pounding)\b",
        r"\bpalpitation",
        r"\bbleed",
        r"\bshort of breath\b",
        r"\bcan.?t breathe\b",
        r"\bconfused\b",
        r"\bvery\s+(ill|unwell|sick)\b",
        r"\bhelp me\b",
    ]
]

_REQUEST_PATTERNS = [
    re.compile(p, re.IGNORECASE)
    for p in [
        r"\b(water|drink|thirsty)\b",
        r"\b(toilet|bathroom|loo|bedpan|commode)\b",
        r"\b(blanket|i.?m cold)\b",
        r"\b(hungry|something to eat|food)\b",
        r"\bcall my\s+\w+",
        r"\b(nurse|someone)\s+(to\s+)?come\b",
    ]
]

URGENT_REPLY = "I'm calling your nurse now. Please stay where you are."
REQUEST_REPLY = "I'll let your nurse know."
TREATMENT_REPLY = "Only your nurse or doctor can decide that. Please ask them."
UNAVAILABLE_REPLY = "Sorry, I can't answer right now. Hold the front button if you need a nurse."
NOT_HEARD_REPLY = "Sorry, I didn't catch that. Press the side button and try again."

MAX_REPLY_WORDS = 45  # the prompt asks for 30; a hard cap for a tiny screen

# Conversation memory: per band, in this process only, never in the database.
CONVERSATION_TTL_S = 180
MAX_REMEMBERED_TURNS = 6  # three questions and their answers
_conversations: dict[uuid.UUID, tuple[float, list[dict[str, str]]]] = {}
_conversations_lock = threading.Lock()


def _history(device_id: uuid.UUID, new_conversation: bool) -> list[dict[str, str]]:
    now = time.monotonic()
    with _conversations_lock:
        for key in [k for k, (t, _) in _conversations.items() if now - t > CONVERSATION_TTL_S]:
            del _conversations[key]  # forget anything idle, whoever it belonged to
        if new_conversation:
            _conversations.pop(device_id, None)
            return []
        return list(_conversations.get(device_id, (now, []))[1])


def _remember(device_id: uuid.UUID, question: str, reply: str) -> None:
    with _conversations_lock:
        turns = _conversations.get(device_id, (0.0, []))[1]
        turns = (turns + [{"role": "user", "content": question}, {"role": "assistant", "content": reply}])
        _conversations[device_id] = (time.monotonic(), turns[-MAX_REMEMBERED_TURNS:])


def forget_conversation(device_id: uuid.UUID) -> None:
    with _conversations_lock:
        _conversations.pop(device_id, None)


def fixed_rule(transcript: str) -> str | None:
    """'urgent' | 'treatment' | 'request' | None — checked before any model."""
    if any(p.search(transcript) for p in _EMERGENCY_PATTERNS + _BAND_URGENT_PATTERNS):
        return "urgent"
    if any(p.search(transcript) for p in _TREATMENT_CHANGE_PATTERNS):
        return "treatment"
    if any(p.search(transcript) for p in _REQUEST_PATTERNS):
        return "request"
    return None


def parse_reply(raw: str) -> tuple[str, str]:
    """The model's [NURSE]/[REQUEST] tag, and the reply cleaned for speech:
    no markdown, one line, capped at a sentence boundary."""
    text = raw.strip()
    tag = ""
    m = re.match(r"\s*\[(NURSE|REQUEST)\]\s*", text)
    if m:
        tag, text = m.group(1), text[m.end():]
    text = re.sub(r"\[(NURSE|REQUEST)\]", "", text)
    text = re.sub(r"[*_#`>]+", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    words = text.split()
    if len(words) > MAX_REPLY_WORDS:
        text = " ".join(words[:MAX_REPLY_WORDS])
        cut = max(text.rfind(". "), text.rfind("? "), text.rfind("! "))
        text = text[: cut + 1] if cut > 0 else text.rstrip(",;:") + "."
    return tag, text


# ── The three local services (module-level so tests can replace them) ──────
def transcribe(wav: bytes) -> str:
    r = httpx.post(
        f"{get_settings().band_talk_stt_url}/inference",
        files={"file": ("speech.wav", wav, "audio/wav")},
        data={"response_format": "json", "temperature": "0"},
        timeout=30,
    )
    r.raise_for_status()
    return str(r.json().get("text", "")).strip()


def ask_model(care_plan: str, question: str, history: list[dict[str, str]] | None = None) -> str:
    settings = get_settings()
    r = httpx.post(
        f"{settings.band_talk_llm_url}/api/chat",
        json={
            "model": settings.band_talk_llm_model,
            "messages": [
                {"role": "system", "content": f"{BAND_TALK_SYSTEM_PROMPT}\n\nPatient's approved care plan:\n{care_plan}"},
                *(history or []),
                {"role": "user", "content": question},
            ],
            "options": {"temperature": 0},
            "think": False,
            "stream": False,
        },
        timeout=30,
    )
    r.raise_for_status()
    return str(r.json()["message"]["content"])


def synthesize(text: str) -> bytes:
    r = httpx.post(
        f"{get_settings().band_talk_tts_url}/synthesize",
        json={"text": text, "length_scale": 1.1},
        timeout=30,
    )
    r.raise_for_status()
    return r.content


# ── Audio for the band ──────────────────────────────────────────────────────
BAND_SAMPLE_RATE = 16000


def to_band_audio(wav_bytes: bytes) -> bytes:
    """WAV → unsigned 8-bit mono at 16 kHz, shaped for the band's tiny speaker
    exactly like firmware/tools/make_voice.py does for the built-in prompts:
    pre-emphasis lifts speech into the 1-4 kHz the speaker can play, then a
    soft clip raises the average level."""
    with wave.open(io.BytesIO(wav_bytes)) as w:
        if w.getsampwidth() != 2:
            raise ValueError("expected 16-bit audio")
        channels, rate = w.getnchannels(), w.getframerate()
        frames = w.readframes(w.getnframes())
    samples = memoryview(frames).cast("h").tolist()
    if channels > 1:
        samples = samples[::channels]
    if not samples:
        return b""
    if rate != BAND_SAMPLE_RATE:  # linear resampling; speech above 8 kHz carries little
        n = int(len(samples) * BAND_SAMPLE_RATE / rate)
        resampled = []
        for i in range(n):
            pos = i * rate / BAND_SAMPLE_RATE
            j = int(pos)
            a = samples[j]
            b = samples[j + 1] if j + 1 < len(samples) else a
            resampled.append(a + (b - a) * (pos - j))
        samples = resampled
    emph = [samples[0]] + [samples[i] - 0.9 * samples[i - 1] for i in range(1, len(samples))]
    peak = max(1.0, max(abs(v) for v in emph))
    drive = 4.0
    norm = math.tanh(drive)
    return bytes(max(0, min(255, int(round(128 + 127 * math.tanh(drive * v / peak) / norm)))) for v in emph)


# ── The pipeline ────────────────────────────────────────────────────────────
@dataclass
class TalkResult:
    transcript: str
    reply: str
    action: str  # "none" | "urgent" | "request" | "unavailable"
    audio_b64: str | None
    timings_ms: dict[str, int] = field(default_factory=dict)


def _raise_alert(db: Session, device: WearableDevice, assignment: DeviceAssignment, event_type: SensorEventType) -> None:
    """Through the same path as a band-submitted event: audit, rules, dedupe."""
    outcome, _ = service.ingest_event(
        db,
        device,
        SensorEventSubmit(
            device_event_id=f"talk-{uuid.uuid4().hex[:24]}",
            event_type=event_type,
            occurred_at_ms=int(time.time() * 1000),
            assignment_id=assignment.id,
        ),
    )
    if outcome != "CREATED":
        raise RuntimeError(f"talk alert not stored: {outcome}")


def talk(
    db: Session,
    device: WearableDevice,
    *,
    audio: bytes | None = None,
    text: str | None = None,
    new_conversation: bool = True,
) -> TalkResult:
    assignment = service.active_assignment_for_device(db, device.id)
    if assignment is None:
        forget_conversation(device.id)
        raise NotAssignedError()
    history = _history(device.id, new_conversation)

    timings: dict[str, int] = {}
    started = time.monotonic()

    # 1. What did the patient say?
    if text is not None:
        transcript = text.strip()
    else:
        try:
            transcript = transcribe(audio or b"")
        except Exception as exc:  # no transcript: nothing can be decided, say so
            logger.warning("talk: speech to text failed (%s)", type(exc).__name__)
            return TalkResult("", UNAVAILABLE_REPLY, "unavailable", _voice(UNAVAILABLE_REPLY, timings), timings)
        timings["stt"] = int((time.monotonic() - started) * 1000)
    # whisper marks silence and noise like "[BLANK_AUDIO]" or "(wind)"
    spoken = re.sub(r"\[[^\]]*\]|\([^)]*\)", "", transcript).strip()
    if len(spoken) < 2:
        return TalkResult(transcript, NOT_HEARD_REPLY, "none", _voice(NOT_HEARD_REPLY, timings), timings)
    transcript = spoken

    # 2. Fixed rules first.
    rule = fixed_rule(transcript)
    action = "none"
    if rule == "urgent":
        action, reply = "urgent", URGENT_REPLY
    elif rule == "treatment":
        reply = TREATMENT_REPLY
    else:
        # 3. The model, grounded in the approved care plan.
        t0 = time.monotonic()
        try:
            tag, reply = parse_reply(
                ask_model(_build_care_plan_summary(db, assignment.patient_id), transcript, history)
            )
            action = {"NURSE": "urgent", "REQUEST": "request"}.get(tag, "none")
        except Exception as exc:
            logger.warning("talk: model failed (%s)", type(exc).__name__)
            tag, reply = "", UNAVAILABLE_REPLY
            action = "unavailable"
        timings["llm"] = int((time.monotonic() - t0) * 1000)
        if rule == "request" and action in ("none", "unavailable"):
            # The fixed rule heard a practical need the model missed (or the
            # model is down): the nurse is still told.
            action, reply = "request", reply if action == "none" and "nurse" in reply.lower() else REQUEST_REPLY
        if not reply:
            reply = UNAVAILABLE_REPLY
        if action == "urgent" and "nurse" not in reply.lower():
            reply = URGENT_REPLY

    # 4. Tell the nurse — before the voice, so a slow voice never delays help.
    if action == "urgent":
        _raise_alert(db, device, assignment, SensorEventType.TALK_URGENT)
    elif action == "request":
        _raise_alert(db, device, assignment, SensorEventType.TALK_REQUEST)

    _remember(device.id, transcript, reply)
    audio_b64 = _voice(reply, timings)
    timings["total"] = int((time.monotonic() - started) * 1000)
    logger.info(
        "talk from %s: rule=%s action=%s timings=%s", device.device_code, rule or "-", action, timings
    )  # never the words
    return TalkResult(transcript, reply, action, audio_b64, timings)


def _voice(reply: str, timings: dict[str, int]) -> str | None:
    """The reply as band audio, or None: the band then shows the text only."""
    t0 = time.monotonic()
    try:
        audio = base64.b64encode(to_band_audio(synthesize(reply))).decode("ascii")
    except Exception as exc:
        logger.warning("talk: voice failed (%s)", type(exc).__name__)
        audio = None
    timings["tts"] = int((time.monotonic() - t0) * 1000)
    return audio
