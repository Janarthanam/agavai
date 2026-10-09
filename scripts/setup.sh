#!/usr/bin/env bash
# Install the app with an explicit choice of model downloads.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
MODE=""
CONFIGURED=false

usage() {
  cat <<'EOF'
Usage: bash scripts/setup.sh [--models all|llm|voice|none] [--configured]

  all    Qwen (~2.5 GB), Parakeet (~481 MB), Kokoro (~192 MB) + speech runtime
  llm    Qwen only; typed requests, with existing speech or eSpeak fallback
  voice  Parakeet and Kokoro + speech runtime; use an existing local LLM
  none   Install app only; reuse existing models and runtime

Without --models, ask interactively. Downloads need internet; existing valid
model files are reused by the download scripts. Python dependencies add space.
Requires Omarchy, Python >=3.11, curl; voice setup also needs uv and espeak-ng.
Setup opens your editor before downloading or installing the service.
Use --configured to explicitly accept an existing config (still validated).
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --configured) CONFIGURED=true; shift ;;
    --models)
      if [[ $# -lt 2 ]]; then usage >&2; exit 2; fi
      MODE="$2"
      shift 2
      ;;
    --help|-h) usage; exit 0 ;;
    *) usage >&2; exit 2 ;;
  esac
done

if [[ -z "$MODE" ]]; then
  if [[ ! -t 0 ]]; then
    echo "Specify --models all|llm|voice|none for noninteractive setup." >&2
    exit 2
  fi
  usage
  read -r -p "Download choice [all/llm/voice/none]: " MODE
fi
case "$MODE" in
  all|llm|voice|none) ;;
  *) echo "Unknown model choice: $MODE" >&2; exit 2 ;;
esac

for command in python3 omarchy systemctl; do
  command -v "$command" >/dev/null || { echo "Missing dependency: $command" >&2; exit 1; }
done
if [[ "$MODE" != none ]]; then
  command -v curl >/dev/null || { echo "Missing dependency: curl" >&2; exit 1; }
fi
if [[ "$MODE" == all || "$MODE" == voice ]]; then
  command -v uv >/dev/null || { echo "Missing dependency: uv" >&2; exit 1; }
fi

export AGAVAI_CONFIG="$HOME/.config/agavai/config.toml"
unset AGAVAI_MODEL AGAVAI_LLAMA_SERVER
if "$CONFIGURED"; then
  bash "$ROOT/scripts/configure.sh" --check
else
  bash "$ROOT/scripts/configure.sh"
fi

if [[ "$MODE" == all || "$MODE" == llm ]]; then
  bash "$ROOT/scripts/download-model.sh"
fi
if [[ "$MODE" == all || "$MODE" == voice ]]; then
  bash "$ROOT/scripts/download-asr.sh"
  bash "$ROOT/scripts/download-tts.sh"
fi
bash "$ROOT/scripts/install.sh" --configured
echo "Setup complete ($MODE). Check: agavai status"
