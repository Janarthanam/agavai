#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BIN="$HOME/.local/bin"
UNIT_DIR="$HOME/.config/systemd/user"
CONF_DIR="$HOME/.config/agavai"
DATA_DIR="$HOME/.local/share/agavai"

# Migrate the old oma-voice names if this machine still has them.
if [[ -d "$HOME/.config/oma-voice" && ! -e "$CONF_DIR" ]]; then
  mv "$HOME/.config/oma-voice" "$CONF_DIR"
fi
if [[ -d "$HOME/.local/share/oma-voice" && ! -e "$DATA_DIR" ]]; then
  mv "$HOME/.local/share/oma-voice" "$DATA_DIR"
fi
if [[ -f "$CONF_DIR/config.toml" ]]; then
  sed -i 's#oma-voice#agavai#g' "$CONF_DIR/config.toml"
fi
systemctl --user disable --now oma-voice-llm.service >/dev/null 2>&1 || true
rm -f "$UNIT_DIR/oma-voice-llm.service"
rm -f "$BIN/oma-voice" "$BIN/oma-voice-llm"
rm -rf "$HOME/.config/omarchy/plugins/janar.oma-voice"

mkdir -p "$BIN" "$UNIT_DIR" "$CONF_DIR/a2a" "$DATA_DIR/models"
ln -sfn "$ROOT/scripts/agavai" "$BIN/agavai"
ln -sfn "$ROOT/scripts/agavai-llm" "$BIN/agavai-llm"
chmod +x "$ROOT/scripts/agavai" "$ROOT/scripts/agavai-llm" \
  "$ROOT/scripts/download-model.sh" "$ROOT/scripts/download-tts.sh" "$ROOT/scripts/kokoro_synth.py"
if [[ ! -f "$CONF_DIR/config.toml" ]]; then
  cp "$ROOT/share/config.example.toml" "$CONF_DIR/config.toml"
fi
cp "$ROOT/share/a2a-card.json" "$CONF_DIR/a2a/agavai.json"
install -m 644 "$ROOT/systemd/agavai-llm.service" "$UNIT_DIR/agavai-llm.service"
systemctl --user daemon-reload
systemctl --user enable agavai-llm.service >/dev/null
systemctl --user restart agavai-llm.service >/dev/null || true

PLUGIN_DST="$HOME/.config/omarchy/plugins/janar.agavai"
mkdir -p "$PLUGIN_DST"
cp -f "$ROOT/plugin/manifest.json" "$ROOT/plugin/Chat.qml" \
  "$ROOT/plugin/NativeButton.qml" "$ROOT/plugin/ResultBrowser.qml" \
  "$ROOT/plugin/BarWidget.qml" "$ROOT/plugin/agavai.png" "$PLUGIN_DST/"
omarchy plugin validate "$PLUGIN_DST"
omarchy-shell shell rescanPlugins >/dev/null 2>&1 || true
omarchy plugin enable janar.agavai >/dev/null 2>&1 || true
omarchy bar put janar.agavai --section right --after janar.microphone >/dev/null 2>&1 \
  || omarchy bar put janar.agavai --section right >/dev/null 2>&1 || true

HICOLOR="$HOME/.local/share/icons/hicolor"
for s in 16 22 24 32 48 64 128 256; do
  mkdir -p "$HICOLOR/${s}x${s}/apps"
  install -m 644 "$ROOT/share/icons/agavai-${s}.png" "$HICOLOR/${s}x${s}/apps/agavai.png"
done
gtk-update-icon-cache -f "$HICOLOR" >/dev/null 2>&1 || true

APPS="$HOME/.local/share/applications"
mkdir -p "$APPS"
install -m 644 "$ROOT/share/agavai.desktop" "$APPS/agavai.desktop"
rm -f "$APPS/oma-voice.desktop"
update-desktop-database "$APPS" >/dev/null 2>&1 || true

echo "Installed agavai and agavai-llm to $BIN"
echo "App launcher: Agavai  (agavai app)"
echo "Chat overlay plugin: janar.agavai (bottom-centered voice orb; live tool calls)"
echo "Active model: agavai model   (list/set in ~/.config/agavai/config.toml)"
echo "Download LLM: $ROOT/scripts/download-model.sh [model-id]"
echo "Download Kokoro TTS (CPU): $ROOT/scripts/download-tts.sh"
echo "Then: systemctl --user enable --now agavai-llm"
echo "Typed test: agavai ask 'open the browser'"
echo "Architecture: $ROOT/docs/architecture.md"
