#!/usr/bin/env bash
# Download Kokoro-82M ONNX (fp16) + voices and create a CPU-only TTS venv.
set -euo pipefail
DATA="${XDG_DATA_HOME:-$HOME/.local/share}/agavai/tts"
VENV="${XDG_DATA_HOME:-$HOME/.local/share}/agavai/tts-venv"
MODEL_URL="https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.1/kokoro-v1.0.fp16.onnx"
VOICES_URL="https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.1/voices-v1.0.bin"
MODEL_BYTES=163527961
VOICES_BYTES=28214398

mkdir -p "$DATA"
fetch() {
  local url="$1" dest="$2" expect="$3"
  if [[ -f "$dest" ]]; then
    local sz
    sz=$(stat -c%s "$dest")
    if [[ "$sz" -eq "$expect" ]]; then
      echo "already present: $dest"
      return 0
    fi
  fi
  echo "downloading $(basename "$dest") (~$((expect / 1000000)) MB)"
  curl -L --fail --retry 5 --retry-delay 2 -C - -o "$dest.partial" "$url"
  local sz
  sz=$(stat -c%s "$dest.partial")
  if [[ "$sz" -ne "$expect" ]]; then
    echo "size mismatch for $dest: got $sz expected $expect" >&2
    exit 1
  fi
  mv "$dest.partial" "$dest"
}

fetch "$MODEL_URL" "$DATA/kokoro-v1.0.fp16.onnx" "$MODEL_BYTES"
fetch "$VOICES_URL" "$DATA/voices-v1.0.bin" "$VOICES_BYTES"

if [[ ! -x "$VENV/bin/python" ]]; then
  echo "creating CPU TTS venv at $VENV"
  uv venv "$VENV"
fi
uv pip install --python "$VENV/bin/python" kokoro-onnx soundfile "onnxruntime>=1.17"
echo "ok Kokoro-82M fp16 + voices in $DATA"
echo "venv: $VENV"
echo "G2P: install espeak-ng if synthesis fails with phontab errors (omarchy pkg add espeak-ng)"
