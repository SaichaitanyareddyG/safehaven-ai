"""Module 3 — "Talk to SafeHaven": the band's voice assistant.

The three local services (speech to text, model, voice) are replaced with
stand-ins; what is tested is the safety logic around them: fixed rules before
the model, alerts through the normal path, failing safe, storing nothing.
"""

import io
import time
import wave

import pytest

from app.patient_chat.models import PatientChatMessage
from app.wearables import talk as band_talk


def _login(client, email="clinician@example.com", password="supersecret123"):
    client.post("/auth/register", json={"email": email, "password": password, "full_name": "Test Clinician"})
    token = client.post("/auth/login", json={"email": email, "password": password}).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _band(client, assign=True):
    headers = _login(client)
    patient = client.post(
        "/patients",
        json={"first_name": "Elena", "last_name": "Ruiz", "date_of_birth": "1948-03-02",
              "preferred_language": "ENGLISH", "room_number": "212"},
        headers=headers,
    ).json()
    reg = client.post("/wearable-devices", json={"device_code": "SH-WEAR-001"}, headers=headers).json()
    secret = client.post(
        "/device-api/enroll", json={"enrollment_code": reg["enrollment_code"], "hardware_id": "HW-1"}
    ).json()["device_secret"]
    if assign:
        client.post(
            f"/patients/{patient['id']}/wearable-assignment",
            json={"device_id": reg["device"]["id"], "monitoring_profile": "STANDARD"},
            headers=headers,
        )
    return headers, {"Authorization": f"Bearer {secret}"}


def _wav(seconds=0.2, rate=22050):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"".join((1000 if (i // 20) % 2 else -1000).to_bytes(2, "little", signed=True)
                               for i in range(int(seconds * rate))))
    return buf.getvalue()


@pytest.fixture
def services(monkeypatch):
    """Stand-ins for whisper / Ollama / Piper, recording how they were called."""
    calls = {"model": [], "stt": 0, "tts": []}
    state = {"model_reply": "Your band watches for falls.", "model_error": None, "tts_error": None,
             "stt_text": "What does this band do?", "stt_error": None}

    def transcribe(wav):
        calls["stt"] += 1
        if state["stt_error"]:
            raise state["stt_error"]
        return state["stt_text"]

    def ask_model(care_plan, question):
        calls["model"].append(question)
        if state["model_error"]:
            raise state["model_error"]
        return state["model_reply"]

    def synthesize(text):
        calls["tts"].append(text)
        if state["tts_error"]:
            raise state["tts_error"]
        return _wav()

    monkeypatch.setattr(band_talk, "transcribe", transcribe)
    monkeypatch.setattr(band_talk, "ask_model", ask_model)
    monkeypatch.setattr(band_talk, "synthesize", synthesize)
    return calls, state


def _say(client, device, text):
    return client.post("/device-api/talk", json={"text": text}, headers=device)


def _alerts(client, headers):
    return client.get("/safety-alerts", headers=headers).json()["results"]


def test_ordinary_question_is_answered_by_the_model_with_voice_and_no_alert(client, services):
    calls, _ = services
    headers, device = _band(client)
    r = _say(client, device, "What does this band do?")
    assert r.status_code == 200
    body = r.json()
    assert body["reply"] == "Your band watches for falls."
    assert body["action"] == "none"
    assert body["audio_b64"] and body["audio_format"] == "pcm-u8-16000-mono"
    assert calls["model"] == ["What does this band do?"]
    assert _alerts(client, headers) == []


def test_urgent_words_alert_the_nurse_without_asking_the_model(client, services):
    calls, _ = services
    headers, device = _band(client)
    body = _say(client, device, "I fell in the bathroom").json()
    assert body["action"] == "urgent"
    assert body["reply"] == band_talk.URGENT_REPLY
    assert calls["model"] == []  # fixed rule: the model is never asked
    alerts = _alerts(client, headers)
    assert [(a["alert_type"], a["priority"]) for a in alerts] == [("TALK_URGENT", "HIGH")]


@pytest.mark.parametrize("words", ["I feel dizzy", "My heart is racing", "I have chest pain", "I can't get up"])
def test_every_fixed_urgent_phrase_alerts(client, services, words):
    headers, device = _band(client)
    assert _say(client, device, words).json()["action"] == "urgent"
    assert _alerts(client, headers)[0]["alert_type"] == "TALK_URGENT"


def test_model_tag_nurse_raises_an_urgent_alert(client, services):
    _, state = services
    headers, device = _band(client)
    state["model_reply"] = "[NURSE] I am calling your nurse now, please stay where you are."
    body = _say(client, device, "Something feels very wrong").json()
    assert body["action"] == "urgent"
    assert body["reply"].startswith("I am calling your nurse now")  # tag stripped
    assert _alerts(client, headers)[0]["alert_type"] == "TALK_URGENT"


def test_practical_request_alerts_at_medium_even_when_the_model_misses_it(client, services):
    _, state = services
    headers, device = _band(client)
    state["model_reply"] = "Water is good for you."  # no tag, no nurse
    body = _say(client, device, "Can I get some water please?").json()
    assert body["action"] == "request"
    assert body["reply"] == band_talk.REQUEST_REPLY
    assert [(a["alert_type"], a["priority"]) for a in _alerts(client, headers)] == [("TALK_REQUEST", "MEDIUM")]


def test_medicine_change_gets_the_fixed_redirect_and_no_model(client, services):
    calls, _ = services
    headers, device = _band(client)
    body = _say(client, device, "Can I stop taking my tablets?").json()
    assert body["reply"] == band_talk.TREATMENT_REPLY
    assert body["action"] == "none"
    assert calls["model"] == []
    assert _alerts(client, headers) == []


def test_model_down_fails_safe(client, services):
    _, state = services
    headers, device = _band(client)
    state["model_error"] = RuntimeError("ollama down")
    body = _say(client, device, "What is my tablet for?").json()
    assert body["action"] == "unavailable"
    assert body["reply"] == band_talk.UNAVAILABLE_REPLY
    assert _alerts(client, headers) == []


def test_model_down_still_passes_a_request_to_the_nurse(client, services):
    _, state = services
    headers, device = _band(client)
    state["model_error"] = RuntimeError("ollama down")
    body = _say(client, device, "I need the toilet").json()
    assert body["action"] == "request"
    assert _alerts(client, headers)[0]["alert_type"] == "TALK_REQUEST"


def test_voice_down_still_answers_in_text(client, services):
    _, state = services
    _, device = _band(client)
    state["tts_error"] = RuntimeError("piper down")
    body = _say(client, device, "What does this band do?").json()
    assert body["audio_b64"] is None
    assert body["reply"] == "Your band watches for falls."


def test_recording_is_transcribed_then_answered(client, services):
    calls, state = services
    _, device = _band(client)
    state["stt_text"] = " What does this band do?\n"
    r = client.post("/device-api/talk", content=_wav(rate=16000),
                    headers={**device, "Content-Type": "audio/wav"})
    assert r.status_code == 200
    assert calls["stt"] == 1
    assert r.json()["transcript"] == "What does this band do?"


def test_silence_is_not_sent_to_the_model(client, services):
    calls, state = services
    _, device = _band(client)
    state["stt_text"] = "[BLANK_AUDIO]"
    r = client.post("/device-api/talk", content=_wav(rate=16000),
                    headers={**device, "Content-Type": "audio/wav"})
    assert r.json()["reply"] == band_talk.NOT_HEARD_REPLY
    assert calls["model"] == []


def test_speech_to_text_down_fails_safe(client, services):
    _, state = services
    _, device = _band(client)
    state["stt_error"] = RuntimeError("whisper down")
    r = client.post("/device-api/talk", content=_wav(rate=16000),
                    headers={**device, "Content-Type": "audio/wav"})
    assert r.json()["action"] == "unavailable"


def test_unassigned_band_is_refused(client, services):
    _, device = _band(client, assign=False)
    assert _say(client, device, "Hello").status_code == 409


def test_other_content_is_refused(client, services):
    _, device = _band(client)
    r = client.post("/device-api/talk", content=b"hi", headers={**device, "Content-Type": "text/plain"})
    assert r.status_code == 415


def test_needs_a_device_credential(client, services):
    assert client.post("/device-api/talk", json={"text": "Hello"}).status_code == 401


def test_nothing_the_patient_says_is_stored(client, services, db_session):
    _, device = _band(client)
    _say(client, device, "What does this band do?")
    _say(client, device, "I fell")
    assert db_session.query(PatientChatMessage).count() == 0


def test_parse_reply_strips_tags_markdown_and_caps_length():
    tag, text = band_talk.parse_reply("[REQUEST] **I will** let your nurse know.")
    assert (tag, text) == ("REQUEST", "I will let your nurse know.")
    long = "This sentence is fine. " + "word " * 80
    _, capped = band_talk.parse_reply(long)
    assert capped == "This sentence is fine."


def test_band_audio_is_16k_unsigned_8bit():
    audio = band_talk.to_band_audio(_wav(seconds=1.0, rate=22050))
    assert abs(len(audio) - 16000) <= 2
    assert min(audio) >= 0 and max(audio) <= 255
