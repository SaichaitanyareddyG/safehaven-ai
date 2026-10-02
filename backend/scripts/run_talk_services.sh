#!/usr/bin/env bash
# Start the three LOCAL services behind "Talk to SafeHaven" (app/wearables/talk.py)
# on a development Mac. Nothing the patient says leaves this machine.
#
#   speech to text   whisper.cpp whisper-server   127.0.0.1:8178
#   the answer       Ollama + qwen3.5:4b          localhost:11434
#   the voice        Piper HTTP server            127.0.0.1:5005
#
# One-time setup (models live outside the repo, in ~/.safehaven-ai-models):
#   brew install whisper-cpp ollama
#   curl -L -o ~/.safehaven-ai-models/ggml-small.en.bin \
#     https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-small.en.bin
#   ollama pull qwen3.5:4b
#   python3 -m venv ~/.safehaven-ai-models/piper-venv
#   ~/.safehaven-ai-models/piper-venv/bin/pip install "piper-tts[http]"
#   # voice: en_US-ljspeech-high.onnx + .onnx.json from
#   #   https://huggingface.co/rhasspy/piper-voices/tree/main/en/en_US/ljspeech/high
#   # (MIT model, trained on the public-domain LJ Speech dataset)
#   # piper-tts 1.8's macOS wheel looks for its pronunciation data at its build
#   # machine's path; give it a copy that contains a link to itself:
#   cp -R <piper-venv>/lib/python3*/site-packages/piper/espeak-ng-data ~/.safehaven-ai-models/espeak
#   ln -s ~/.safehaven-ai-models/espeak ~/.safehaven-ai-models/espeak/espeak-ng-data
#
# Then: backend/scripts/run_talk_services.sh   (Ctrl-C stops all three)
set -euo pipefail
M="$HOME/.safehaven-ai-models"

trap 'kill 0' EXIT
whisper-server -m "$M/ggml-small.en.bin" --host 127.0.0.1 --port 8178 >/dev/null 2>&1 &
curl -s -m 2 http://localhost:11434/api/version >/dev/null || (ollama serve >/dev/null 2>&1 &)
ESPEAK_DATA_PATH="$M/espeak" "$M/piper-venv/bin/python" -m piper.http_server \
  -m "$M/en_US-ljspeech-high.onnx" --host 127.0.0.1 --port 5005 >/dev/null 2>&1 &

echo "Talk services starting: whisper :8178, ollama :11434, piper :5005 (Ctrl-C to stop)"
wait
