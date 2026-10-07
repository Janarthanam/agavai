#!/usr/bin/env bash
# Download the cache-aware Parakeet-Realtime-EOU-120M ONNX used by the assistant.
# Dynamic cache-aware encoder and full-precision decoder; INT8 loses speech tokens.
set -euo pipefail

BASE="https://huggingface.co/altunenes/parakeet-rs/resolve/4d2a8bc71f5c896ec40faa59732e6716295edaf2/realtime_eou_120m-v1-onnx"
DEST_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/agavai/models/parakeet-realtime-eou-120m"
mkdir -p "$DEST_DIR"

fetch() {
  local name="$1" bytes="$2" sha="$3" url="$4"
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
  curl -C - -fL --retry 5 -o "$partial" "$url"
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

fetch encoder.onnx 459341289 d472887cc38a784a5bfc21c2dbe247639edc3b3f9992388d8ceceaec07256b5b "$BASE/encoder.onnx"
fetch decoder_joint.onnx 21347639 9d2553ac043c2fc5f69e970769b0fb8ab9103fbfdeb7d26a1ea9729d4bd2dddd "$BASE/decoder_joint.onnx"
fetch vocab.txt 6233 77c3f876cddac2d9ad82efceea38fd6acd16575e0ab54ab3396aa4621fa8ff02 \
  "https://huggingface.co/AIsley/parakeet-realtime-eou-120m-streaming-fp16/resolve/fcf8a3b/vocab.txt"
