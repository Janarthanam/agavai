# Agavai

Local voice assistant for [Omarchy](https://omarchy.org/). CLI package name: `agavai`.

Local Siri-style loop for Omarchy. **v1 talks to no remote model.**

End-to-end voice loop (the design spec): [`docs/flow.md`](docs/flow.md). Decision record: [`docs/v2.md`](docs/v2.md). Audio stages: [`docs/audio.md`](docs/audio.md). Process split and **how the on-device GGUF is selected**: [`docs/architecture.md`](docs/architecture.md).

One native overlay starts as an orb at the bottom right, without taking keyboard focus or showing text. Click it to expand the transcript and result browser at the same bottom-right corner; use − to minimize without stopping listening, or click the orb’s × button to close directly. Right-clicking the orb also cancels. In the expanded view: the orb follows the microphone level, and the same surface shows the current request, formatted answers, selectable file/folder rows, image previews, and video controls. Results stay open until dismissed. Use arrows to browse and Enter or Open to open a supported item. The [UI design](docs/ui-design.md) and [interactive prototype](docs/ui-prototype/index.html) document the interaction. Words appear in the expanded view while you are still talking. New canvas results open the expanded view at the bottom right. Microphone updates and ordinary replies respect manual minimization. Clicking another window minimizes the expanded view and keeps listening.

```
hotkey → streaming ASR → on-device GGUF on llama-server :18766 → allowlisted tools → speak
```

F9 dictation stays Voxtype. **Super+M** invokes Agavai: the line sends when streaming ASR hears the end of the utterance. In the expanded view, Enter sends the current line and Escape dismisses. Super+Ctrl+M remains an invocation alias. `agavai invoke`, the launcher, and the bar always use automatic listening. The recognizer weights come from `scripts/download-asr.sh`. `[asr] device` defaults to CPU, and selects an NVIDIA GPU only when that device is set to `gpu` and one is present.

Open **Agavai** from the app launcher (or `agavai app` / `agavai invoke`). The launcher, shortcut, and bar share **one overlay**, which starts listening automatically. Left-click the bar icon to speak; right-click cancels. In the expanded view, Escape or × dismisses the overlay. “Type instead” provides a text entry on the same surface. Reinvoking while a request is active raises the widget without submitting or restarting the command.

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

Spoken replies use **Kokoro-82M on CPU** (Apache-2.0). Whisper stays STT only.

```bash
omarchy pkg add espeak-ng          # G2P for Kokoro, not the audible voice
~/Projects/oma-voice/scripts/download-tts.sh
agavai ask "what time is it"       # you should hear the reply
```

If Kokoro is missing, Agavai falls back to eSpeak then a notification.

## Tools (MCP)

`agavai mcp` is a stdio MCP server. The voice loop calls the same functions in-process.

Tools are grouped into heads. **Jev** (OpenRouter Decisions API, `typesafe/jev-1.13`) picks a head; Qwen3-4B only sees those schemas. Set `OPENROUTER_API_KEY`. If the key is missing, a keyword fallback still routes. Wallpaper: `omarchy theme bg set/next/current`.

No generic shell. No Grok. Pixel click / YOLO is not in v1.

## Tests

BDD only, via [behave](https://behave.readthedocs.io/). See `AGENTS.md`.

```bash
cd ~/Projects/agavai
pip install -e '.[dev]'   # or: pip install behave
PYTHONPATH=src behave
```

## Eval

`evals/` scores Agavai as a personal assistant against the running local model: a simulated desktop and mailbox, a fixed clock, pinned sampling, and graders that look only at the world and the spoken reply. It is a measurement, not a test. Design and how to run it: [`docs/eval.md`](docs/eval.md).

```bash
PYTHONPATH=src .venv/bin/python -m evals run      # writes evals/results/<run>/report.json and report.html
```
