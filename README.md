# Agavai

Local voice assistant for [Omarchy](https://omarchy.org/). CLI package name: `agavai`.

Local Siri-style loop for Omarchy. **v1 talks to no remote model.**

Architecture, process split, tool loop, and **how the on-device GGUF is selected**: [`docs/architecture.md`](docs/architecture.md).

```
hotkey → Voxtype (--file) → on-device GGUF on llama-server :18766 → allowlisted tools → speak
```

F9 dictation stays Voxtype. Super+Ctrl+M is push-to-toggle listen.

Open **Agavai** from the app launcher (or `agavai app`) for a window that shows the transcript and every tool call. Use Listen / Send / Ask there if the overlay is not responding.

Default brain: **Qwen3-4B-Instruct-2507 Q4_K_M (~2.5 GB)**. Switch it without editing the systemd unit:

```bash
agavai model list
agavai model set qwen3-4b-instruct
systemctl --user restart agavai-llm
```

Add another GGUF under `[llm.models.<id>]` in `~/.config/agavai/config.toml`. See the architecture doc.

The 1.5B on `:18765` is only the Voxtype sanitizer. Do not reuse it as the agent.

## Install

```bash
~/Projects/agavai/scripts/download-model.sh
~/Projects/agavai/scripts/install.sh
systemctl --user enable --now agavai-llm
agavai ask "open the browser"
```

Optional spoken TTS: `omarchy pkg add espeak-ng`. Without it, replies still go to a notification.

## Tools (MCP)

`agavai mcp` is a stdio MCP server. The voice loop calls the same functions in-process.

Allowlisted: list/focus windows, workspace, launch (browser/terminal/files/editor/about), themes, night light, reminders, fd file search, https URLs, screen OCR of the focused window, list local agents/units.

No generic shell. No Grok. Pixel click / YOLO is not in v1.

## Tests

BDD only, via [behave](https://behave.readthedocs.io/). See `AGENTS.md`.

```bash
cd ~/Projects/agavai
pip install -e '.[dev]'   # or: pip install behave
PYTHONPATH=src behave
```
