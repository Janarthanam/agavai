# Agavai

Local voice assistant for [Omarchy](https://omarchy.org/). CLI package name: `agavai`.

An in-process voice-agent harness for Omarchy. Speech and reasoning models are replaceable local services; optional Jev head routing can use OpenRouter.

Harness design: [docs/voice-agent-harness.md](docs/voice-agent-harness.md). End-to-end voice loop: [`docs/flow.md`](docs/flow.md). Audio stages: [`docs/audio.md`](docs/audio.md). Process split: [`docs/architecture.md`](docs/architecture.md). Model roles and GGUF selection: [`docs/engines.md`](docs/engines.md#small-brain-then-larger-brain).

One native overlay starts as an orb in a corner of the screen (bottom right unless `[overlay] placement` in `~/.config/agavai/config.toml` says otherwise), without taking keyboard focus or showing text. Click it to expand the transcript and result browser around it; the orb stays put. Click it again or use − to minimize without stopping listening, or click the orb’s × button to close directly. Right-clicking the orb also cancels. In the expanded view: the orb follows the microphone level, and the same surface shows the current request, formatted answers, selectable file/folder rows, image previews, and video controls. Results stay open until dismissed. Use arrows to browse and Enter or Open to open a supported item. The [UI design](docs/ui-design.md) and [interactive prototype](docs/ui-prototype/index.html) document the interaction. Words appear in the expanded view while you are still talking. New canvas results open the expanded view in place. Microphone updates and ordinary replies respect manual minimization. Clicking another window minimizes the expanded view and keeps listening.

```
voice / typed request → Agavai harness → context + decisions → model services → validated tools / grounded answer
```

F9 dictation stays Voxtype. **Super+M** invokes Agavai: the line sends when streaming ASR hears the end of the utterance. In the expanded view, Enter sends the current line and Escape dismisses. Super+Ctrl+M invokes `agavai record` to toggle recording. Saying "take notes" or "record this" also starts one. The audio, a timed transcript, and corrections are kept in `~/Documents/Agavai/Recordings` ([docs/recording.md](docs/recording.md)). `agavai invoke`, the launcher, and the bar always use automatic listening. The recognizer weights come from `scripts/download-asr.sh`. `[asr] device` defaults to CPU, and selects an NVIDIA GPU only when that device is set to `gpu` and one is present.

Open **Agavai** from the app launcher (or `agavai app` / `agavai invoke`). The launcher, shortcut, and bar share **one overlay**, which starts listening automatically. Left-click the bar icon to speak; right-click cancels. In the expanded view, Escape or × dismisses the overlay. “Type instead” provides a text entry on the same surface. Reinvoking while a request is active raises the widget without submitting or restarting the command.

The harness owns task history, confirmations, corrected recording sources, bounded prompt projection and cancellation. Language questions and self-corrections select a language-capable tier; Needle proposes supported actions. Personal memory/preferences are deferred. Local deployment status is recorded in [tasks/harness-deployment.md](tasks/harness-deployment.md).

`Harness.run_turn()` returns a typed [TurnResult](docs/voice-agent-harness.md#structured-turn-result)
with status, optional speech/content, execution outcomes and trace identity.
The event stream supplies progress and embeds that same result at completion.

Sessions now retain committed text, ordered events, full tool outcomes and context
in `$XDG_DATA_HOME/agavai/sessions.sqlite3` (normally `~/.local/share/agavai`).
Accepted spoken turns save audio by default under `sessions/<id>/audio/`; typed
turns have no audio. The expanded widget shows session identity and opens saved
history. Use `agavai session list`, `agavai session show ID`, and
`agavai session export ID ./export` to inspect what happened. Resume never replays
an interrupted action. `[sessions]` controls storage, audio opt-out and explicit
retention/quota settings; see [session persistence](docs/session-persistence.md).

Default brain: **Qwen3-4B-Instruct-2507 Q4_K_M (~2.5 GB)**. Switch it without editing the systemd unit:

```bash
agavai model list
agavai model set qwen3-4b-instruct    # restarts agavai-llm with the new model
```

Add another GGUF under `[llm.models.<id>]` in `~/.config/agavai/config.toml`. See the architecture doc.

The 1.5B on `:18765` is only the Voxtype sanitizer. Do not reuse it as the agent.

## Install

```bash
~/Projects/agavai/scripts/download-model.sh
~/Projects/agavai/scripts/install.sh    # installs and syncs the model services
agavai ask "open the browser"
```

Change models any time with `agavai setup`: it explains each choice, downloads what is missing, updates `config.toml` and the services, and shows how a request will flow. `agavai explain` repeats that walkthrough for the current configuration.

`agavai-llm` runs only when a brain role uses llama-server, and follows `config.toml` changes on its own; `agavai services` shows its state. See [engine configuration](docs/engines.md#services-follow-the-configuration).

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

No generic shell. No Grok. Pixel click / YOLO is not in v1. The recording tools are not offered over MCP.

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

Speech, routing, agent and local fallback can be selected independently. See [engine configuration](docs/engines.md), [Needle router + Qwen agent](share/config.needle-router.toml), or [Needle as router and agent + local Qwen fallback](share/config.needle.toml). Cloud support is deferred; full-tool Needle is an opt-in experiment because native probes found incorrect selections.
