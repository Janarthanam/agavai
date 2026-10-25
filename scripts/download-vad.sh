#!/usr/bin/env bash
# Download the pinned Silero VAD v5.1.2 ONNX model (opt-in [vad] backend = "silero").
# Same resumable verified-download pattern as download-model.sh / download-tts.sh.
set -euo pipefail

URL="https://raw.githubusercontent.com/snakers4/silero-vad/v5.1.2/src/silero_vad/data/silero_vad.onnx"
EXPECT_BYTES=2327524
EXPECT_SHA256="2623a2953f6ff3d2c1e61740c6cdb7168133479b267dfef114a4a3cc5bdd788f"
DEST_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/agavai/vad"
DEST="$DEST_DIR/silero_vad-v5.1.2.onnx"
PARTIAL="$DEST.partial"

mkdir -p "$DEST_DIR"

if [ -f "$DEST" ]; then
  bytes=$(stat -c '%s' "$DEST")
  if [ "$bytes" = "$EXPECT_BYTES" ] && echo "$EXPECT_SHA256  $DEST" | sha256sum -c --status 2>/dev/null; then
    echo "already present: $DEST"
    exit 0
  fi
  echo "existing file mismatch; redownloading" >&2
fi

echo "downloading $URL"
curl -C - -fL --retry 5 -o "$PARTIAL" "$URL"

bytes=$(stat -c '%s' "$PARTIAL")
if [ "$bytes" != "$EXPECT_BYTES" ]; then
  echo "unexpected size: $bytes (expected $EXPECT_BYTES)" >&2
  exit 1
fi
if ! echo "$EXPECT_SHA256  $PARTIAL" | sha256sum -c --status; then
  echo "sha256 mismatch" >&2
  rm -f "$PARTIAL"
  exit 1
fi

mv "$PARTIAL" "$DEST"
echo "installed: $DEST"
