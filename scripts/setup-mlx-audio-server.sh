#!/bin/bash
# setup-mlx-audio-server.sh — bootstrap mlx-audio server for TTS/STT sidecar serving
#
# mlx-audio's published extras don't declare all their runtime deps correctly.
# This script papers over the gaps so `mlx_audio.server` actually starts and
# can load all supported TTS backends (including Kokoro, which needs misaki →
# spacy → thinc → torch, with version constraints that the extras don't pin).
#
# Usage:
#   ./scripts/setup-mlx-audio-server.sh          # install only
#   ./scripts/setup-mlx-audio-server.sh --start   # install then start on port 9001
#   ./scripts/setup-mlx-audio-server.sh --start --port 8000
#
# After install, start the server manually with:
#   mlx_audio.server --host 0.0.0.0 --port 9001 --workers 1
#
# Then load models via the API:
#   curl -X POST "http://localhost:9001/v1/models?model_name=mlx-community/Voxtral-4B-TTS-2603-mlx-6bit"
#   curl -X POST "http://localhost:9001/v1/models?model_name=mlx-community/Kokoro-82M-bf16"

set -euo pipefail

PORT=9001
START=false

while [[ $# -gt 0 ]]; do
  case $1 in
    --start) START=true; shift ;;
    --port)  PORT="$2"; shift 2 ;;
    *)       echo "Unknown option: $1" >&2; exit 1 ;;
  esac
done

echo "==> Installing mlx-audio[server,stt] as uv tool..."
uv tool install --force "mlx-audio[server,stt]" --prerelease=allow \
    --with webrtcvad \
    --with "setuptools<75"

VENV_PYTHON="$(uv tool dir)/mlx-audio/bin/python"

if ! "$VENV_PYTHON" -c "from misaki import en, espeak" 2>/dev/null; then
    echo "==> Installing Kokoro deps (misaki + spacy + torch pinning)..."
    # misaki[en] pulls spacy; spacy needs typer (0.15.x, not 0.21+ which is
    # namespace-only); thinc needs torch <2.7 (2.11+ drops SymInt).
    uv pip install --python "$VENV_PYTHON" \
        "misaki[en]" \
        num2words \
        "typer==0.15.3" \
        "torch>=2.5,<2.7"
fi

# Kokoro's G2P pipeline (misaki -> spacy) needs the en_core_web_sm model at
# runtime. spacy.load('en_core_web_sm') will fail with OSError E050 without it,
# and the server returns a streaming 200 with 0 bytes instead of an error.
if ! "$VENV_PYTHON" -c "import spacy; spacy.load('en_core_web_sm')" 2>/dev/null; then
    echo "==> Installing spacy en_core_web_sm language model..."
    uv pip install --python "$VENV_PYTHON" \
        "https://github.com/explosion/spacy-models/releases/download/en_core_web_sm-3.8.0/en_core_web_sm-3.8.0-py3-none-any.whl"
fi

echo "==> Verifying imports..."
"$VENV_PYTHON" -c "
from misaki import en, espeak
import spacy; spacy.load('en_core_web_sm')
import mlx_audio.server
print('All imports OK')
"

echo "==> mlx-audio server ready."
echo "   Binary: mlx_audio.server"
echo "   Note: the command is mlx_audio.server (dots), not mlx-audio-server (dashes)."

if $START; then
    echo "==> Starting on 0.0.0.0:${PORT}..."
    exec mlx_audio.server --host 0.0.0.0 --port "$PORT" --workers 1
fi
