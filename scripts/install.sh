#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BIN="$HOME/.local/bin"
UNIT_DIR="$HOME/.config/systemd/user"
CONF_DIR="$HOME/.config/oma-voice"

mkdir -p "$BIN" "$UNIT_DIR" "$CONF_DIR/a2a"
ln -sfn "$ROOT/scripts/oma-voice" "$BIN/oma-voice"
ln -sfn "$ROOT/scripts/oma-voice-llm" "$BIN/oma-voice-llm"
chmod +x "$ROOT/scripts/oma-voice" "$ROOT/scripts/oma-voice-llm" "$ROOT/scripts/download-model.sh"
if [[ ! -f "$CONF_DIR/config.toml" ]]; then
  cp "$ROOT/share/config.example.toml" "$CONF_DIR/config.toml"
fi
cp "$ROOT/share/a2a-card.json" "$CONF_DIR/a2a/oma-voice.json"
install -m 644 "$ROOT/systemd/oma-voice-llm.service" "$UNIT_DIR/oma-voice-llm.service"
systemctl --user daemon-reload

PLUGIN_DST="$HOME/.config/omarchy/plugins/janar.oma-voice"
mkdir -p "$PLUGIN_DST"
cp -f "$ROOT/plugin/manifest.json" "$ROOT/plugin/Chat.qml" "$PLUGIN_DST/"
omarchy plugin validate "$PLUGIN_DST"
omarchy plugin enable janar.oma-voice >/dev/null 2>&1 || true

APPS="$HOME/.local/share/applications"
mkdir -p "$APPS"
install -m 644 "$ROOT/share/oma-voice.desktop" "$APPS/agavai.desktop"
rm -f "$APPS/oma-voice.desktop"
update-desktop-database "$APPS" >/dev/null 2>&1 || true

echo "Installed oma-voice and oma-voice-llm to $BIN"
echo "App launcher: Agavai  (oma-voice app)"
echo "Chat overlay plugin: janar.oma-voice (top of screen; live tool calls)"
echo "Active model: oma-voice model   (list/set in ~/.config/oma-voice/config.toml)"
echo "Download weights: $ROOT/scripts/download-model.sh [model-id]"
echo "Then: systemctl --user enable --now oma-voice-llm"
echo "Typed test: oma-voice ask 'open the browser'"
echo "Architecture: $ROOT/docs/architecture.md"
