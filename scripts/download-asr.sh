#!/usr/bin/env bash
# Download the cache-aware Parakeet-Realtime-EOU-120M ONNX used by the assistant.
# Encoder: AIsley cache-aware FP16 export. Decoder and vocab: the matching INT8 joint net.
set -euo pipefail

BASE="https://huggingface.co/AIsley/parakeet-realtime-eou-120m-streaming-fp16/resolve/main"
DEST_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/agavai/models/parakeet-realtime-eou-120m"
mkdir -p "$DEST_DIR"

fetch() {
  local name="$1" bytes="$2" sha="$3"
  local dest="$DEST_DIR/$name" partial="$DEST_DIR/$name.partial"
  if [ -f "$dest" ]; then
    local got
    got=$(stat -c '%s' "$dest")
    if [ "$got" = "$bytes" ] && echo "$sha  $dest" | sha256sum -c --status 2>/dev/null; then
      echo "already present: $dest"
      return
    fi
    echo "existing file mismatch; redownloading $name" >&2
  fi
  echo "downloading $name"
  curl -C - -fL --retry 5 -o "$partial" "$BASE/$name"
  local got
  got=$(stat -c '%s' "$partial")
  if [ "$got" != "$bytes" ]; then
    echo "unexpected size for $name: $got (expected $bytes)" >&2
    exit 1
  fi
  if ! echo "$sha  $partial" | sha256sum -c --status; then
    echo "sha256 mismatch for $name" >&2
    rm -f "$partial"
    exit 1
  fi
  mv "$partial" "$dest"
  echo "installed: $dest"
}

fetch streaming_encoder.fp16.onnx 231847327 9f9bb8f2e11fd8f66763d94042b9b9de721b4dcfba9ca9bb1071272ac3ff0ddb
fetch decoder_joint-model.int8.onnx 5368692 5464333fa933bf2c60952c08f01f5b5dd3fe3176e1c70d3eeddb48412514a0f9
fetch vocab.txt 6233 77c3f876cddac2d9ad82efceea38fd6acd16575e0ab54ab3396aa4621fa8ff02
