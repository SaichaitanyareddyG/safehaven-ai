#!/usr/bin/env python3
"""Generate the band's spoken prompts as 8-bit PCM arrays (src/VoiceClips.h).

The generated header is committed; the firmware build needs none of this.

VOICE AND LICENCE. The shipped voice is Piper TTS with the "ljspeech" voice:
the voice model is MIT-licensed and was trained only on the LJ Speech
dataset, which is public domain (rhasspy/piper-voices, MODEL_CARD). The
Piper engine (piper1-gpl) is GPL-3.0, but it only runs here, on a developer
machine, to produce audio; no Piper code goes into the firmware.

    python3 -m venv piper-venv && piper-venv/bin/pip install piper-tts
    # voice: en_US-ljspeech-high.onnx + .onnx.json from
    #   https://huggingface.co/rhasspy/piper-voices/tree/main/en/en_US/ljspeech/high
    python3 tools/make_voice.py --piper-python piper-venv/bin/python \
        --model en_US-ljspeech-high.onnx [--espeak-data DIR]

--espeak-data works around a piper-tts 1.8 macOS wheel that looks for its
pronunciation data at its build machine's path: pass a copy of the
package's espeak-ng-data folder that also contains a symlink to itself
named espeak-ng-data.

`--engine say` uses the macOS system voice instead: quick drafts only — Apple's
voices are not licensed for distribution, and the header says so.

Each clip is pre-emphasised and compressed for the band's tiny speaker, then
stored as unsigned 8-bit mono at 16 kHz (~16 KB per second of speech).
"""
import argparse
import array
import math
import os
import subprocess
import sys
import tempfile
import wave

SAY_VOICE = "Samantha"
SAY_RATE_WPM = 165
SAMPLE_RATE = 16000
PRE_EMPHASIS = 0.9   # first-order high-pass: lifts 1-4 kHz relative to the bass
DRIVE = 4.0          # soft-clip drive

# Short, calm, plain words. No diagnosis: the band says what it saw.
CLIPS = {
    "FALL": "Fall detected. Calling the nurse.",
    "CHECK": "Are you OK? Press the button if you are OK.",
    "CHECK_OK": "Thank you. No alert sent.",
    "NO_ANSWER": "No answer. Calling the nurse.",
    "HELP": "Help requested. Calling the nurse.",
    "NURSE_TOLD": "The nurse has been told.",
    "NURSE_COMING": "Don't worry. A nurse is coming.",
}


PIPER_SCRIPT = """
import sys, wave
from piper import PiperVoice, SynthesisConfig
voice = PiperVoice.load(sys.argv[1])
with wave.open(sys.argv[2], "wb") as w:
    voice.synthesize_wav(sys.argv[3], w, syn_config=SynthesisConfig(length_scale=float(sys.argv[4])))
"""


def read_wav(path: str) -> tuple[array.array, int]:
    with wave.open(path) as w:
        if w.getsampwidth() != 2 or w.getnchannels() != 1:
            raise SystemExit(f"{path}: expected 16-bit mono")
        return array.array("h", w.readframes(w.getnframes())), w.getframerate()


def resample(pcm: array.array, rate: int) -> list[float]:
    """Linear resampling to SAMPLE_RATE (speech above 8 kHz carries little)."""
    if rate == SAMPLE_RATE:
        return [float(v) for v in pcm]
    n = int(len(pcm) * SAMPLE_RATE / rate)
    out = []
    for i in range(n):
        pos = i * rate / SAMPLE_RATE
        j = int(pos)
        f = pos - j
        a = pcm[j]
        b = pcm[j + 1] if j + 1 < len(pcm) else a
        out.append(a + (b - a) * f)
    return out


def render(text: str, tmp: str, args) -> list[float]:
    wav = os.path.join(tmp, "v.wav")
    if args.engine == "say":
        aiff = os.path.join(tmp, "v.aiff")
        subprocess.run(["say", "-v", SAY_VOICE, "-r", str(SAY_RATE_WPM), "-o", aiff, text], check=True)
        subprocess.run(["afconvert", "-f", "WAVE", "-d", f"LEI16@{SAMPLE_RATE}", "-c", "1", aiff, wav], check=True)
    else:
        env = dict(os.environ)
        if args.espeak_data:
            env["ESPEAK_DATA_PATH"] = args.espeak_data
        subprocess.run([args.piper_python, "-c", PIPER_SCRIPT, args.model, wav, text, str(args.length_scale)],
                       check=True, env=env)
    pcm, rate = read_wav(wav)
    if len(pcm) == 0:
        raise SystemExit(f"no audio for {text!r} (see --espeak-data in the docstring)")
    return resample(pcm, rate)


def to_u8(pcm: list[float]) -> bytes:
    # Trim leading/trailing near-silence.
    floor = 300
    start = next((i for i, v in enumerate(pcm) if abs(v) > floor), 0)
    end = len(pcm) - next((i for i, v in enumerate(reversed(pcm)) if abs(v) > floor), 0)
    pcm = pcm[max(0, start - 400):min(len(pcm), end + 800)]
    # The band's speaker is a tiny cavity: loud at 2-3 kHz (where the alarm
    # tone sits), weak below ~800 Hz, where most speech energy is. Pre-emphasis
    # moves the energy up to where the speaker can play it, then hard soft-
    # clipping raises the average level. Bench: the first version (no
    # pre-emphasis, mild compression) was much quieter than the beeps.
    emph = [pcm[0]] + [pcm[i] - PRE_EMPHASIS * pcm[i - 1] for i in range(1, len(pcm))]
    peak = max(1.0, max(abs(v) for v in emph))
    out = bytearray()
    for v in emph:
        x = v / peak                                   # normalise to +-1
        x = math.tanh(DRIVE * x) / math.tanh(DRIVE)    # compress: louder on average
        out.append(max(0, min(255, int(round(128 + 127 * x)))))
    return bytes(out)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--engine", choices=["piper", "say"], default="piper")
    ap.add_argument("--piper-python", help="python of a venv with piper-tts installed")
    ap.add_argument("--model", help="Piper voice .onnx (its .onnx.json beside it)")
    ap.add_argument("--espeak-data", help="espeak-ng data folder (macOS wheel workaround)")
    ap.add_argument("--length-scale", type=float, default=1.1, help="> 1 speaks more slowly")
    args = ap.parse_args()
    if args.engine == "piper" and not (args.piper_python and args.model):
        ap.error("--engine piper needs --piper-python and --model")
    if args.engine == "piper":
        source = f"Piper TTS, voice {os.path.basename(args.model)} (MIT; trained on LJ Speech, public domain)"
    else:
        source = f"macOS '{SAY_VOICE}' — DRAFT ONLY, not licensed for distribution"
    here = os.path.dirname(os.path.abspath(__file__))
    target = os.path.join(here, "..", "src", "VoiceClips.h")
    lines = [
        "// GENERATED by tools/make_voice.py — do not edit by hand.",
        f"// Voice: {source}.",
        f"// Unsigned 8-bit mono, {SAMPLE_RATE} Hz.",
        "#pragma once",
        "#include <stddef.h>",
        "#include <stdint.h>",
        "",
        "namespace voice {",
        f"static constexpr uint32_t kSampleRate = {SAMPLE_RATE};",
        "",
    ]
    total = 0
    with tempfile.TemporaryDirectory() as tmp:
        for name, text in CLIPS.items():
            data = to_u8(render(text, tmp, args))
            total += len(data)
            lines.append(f"// \"{text}\" ({len(data) / SAMPLE_RATE:.1f} s)")
            lines.append(f"static const uint8_t k{name}[{len(data)}] = {{")
            for i in range(0, len(data), 24):
                lines.append("  " + ",".join(str(b) for b in data[i:i + 24]) + ",")
            lines.append("};")
            lines.append("")
            print(f"{name:13s} {len(data) / SAMPLE_RATE:4.1f} s  {len(data) // 1024:3d} KB  {text}")
    lines.append("}  // namespace voice")
    lines.append("")
    with open(target, "w") as f:
        f.write("\n".join(lines))
    print(f"total {total // 1024} KB -> {os.path.normpath(target)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
