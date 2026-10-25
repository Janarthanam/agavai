#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CONF="$HOME/.config/agavai/config.toml"
MODE="${1:---edit}"
case "$MODE" in
  --edit)
    if [[ ! -t 0 ]]; then
      echo "Configuration needs a terminal. Edit $CONF, then use --configured." >&2
      exit 2
    fi
    mkdir -p "$(dirname "$CONF")"
    if [[ ! -f "$CONF" ]]; then
      if [[ -f "$HOME/.config/oma-voice/config.toml" ]]; then
        cp "$HOME/.config/oma-voice/config.toml" "$CONF"
      else
        cp "$ROOT/share/config.example.toml" "$CONF"
      fi
    fi
    echo "Configure Agavai: $CONF"
    echo "Set [llm] llama_bin to your llama-server; review model, voice and file roots."
    read -r -a EDITOR_COMMAND <<< "${VISUAL:-${EDITOR:-nano}}"
    "${EDITOR_COMMAND[@]}" "$CONF"
    ;;
  --check|--ready) ;;
  *) echo "Usage: configure.sh [--edit|--check|--ready]" >&2; exit 2 ;;
esac

PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}" python3 - "$CONF" "$MODE" <<'PY'
import os
import sys
from pathlib import Path
from agavai.config import load_config

path = Path(sys.argv[1])
if not path.is_file():
    sys.exit(f"Configuration missing: {path}")
# The user service reads its saved config, without this terminal's overrides.
os.environ.pop("AGAVAI_LLAMA_SERVER", None)
os.environ.pop("AGAVAI_MODEL", None)
cfg = load_config(path)
model = cfg.llama_for_role()
if model is not None:
    if not model.llama_bin.is_file() or not os.access(model.llama_bin, os.X_OK):
        sys.exit(f"Set llama_bin to an executable llama-server: {model.llama_bin}")
    if sys.argv[2] == "--ready" and not model.model_path.is_file():
        sys.exit(f"LLM model missing: {model.model_path}. Download it before installing the service.")
print(f"Configuration validated: {path}")
PY
