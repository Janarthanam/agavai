#!/usr/bin/env bash
# Download the GGUF for a configured model id (default: the active [llm] model).
set -euo pipefail
ROOT="$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)"
export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
ID="${1:-}"

readarray -t META < <(python3 - "$ID" <<'PY'
import sys
from agavai.config import load_config
cfg = load_config()
mid = sys.argv[1] or cfg.llm.model_id
spec = cfg.llm.models.get(mid)
if spec is None:
    print(f"unknown model {mid!r}", file=sys.stderr)
    sys.exit(2)
if not spec.download_url or not spec.expected_bytes:
    print(f"no download metadata for {mid!r}; set path yourself", file=sys.stderr)
    sys.exit(2)
print(mid)
print(spec.path)
print(spec.download_url)
print(spec.expected_bytes)
PY
)
ID="${META[0]}"
DEST="${META[1]}"
URL="${META[2]}"
EXPECT="${META[3]}"

mkdir -p "$(dirname "$DEST")"
if [[ -f "$DEST" ]]; then
  sz=$(stat -c%s "$DEST")
  if [[ "$sz" -eq "$EXPECT" ]]; then
    echo "already present: $ID -> $DEST ($sz bytes)"
    exit 0
  fi
fi
echo "downloading $ID (~$((EXPECT / 1000000)) MB) to $DEST"
curl -L --fail --retry 5 --retry-delay 2 -C - -o "$DEST.partial" "$URL"
sz=$(stat -c%s "$DEST.partial")
if [[ "$sz" -ne "$EXPECT" ]]; then
  echo "size mismatch: got $sz expected $EXPECT" >&2
  exit 1
fi
mv "$DEST.partial" "$DEST"
echo "ok $ID -> $DEST"
