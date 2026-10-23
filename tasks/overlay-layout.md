# Overlay layout, start chime, and visual answers

## Surface

- [x] P1 voice Play one short chime when a listening session starts, alongside the orb
- [x] P0 ui Make the overlay corner configurable; the expanded view grows from the minimized orb, which stays put
- [x] P0 ui Show answers that need visual structure (lists, steps) on the expanded canvas

Status: complete. Commits `edbe6f0`, `a4d172c`, `fed791a`, `853100a`. Deployed 2026-10-23 with user approval.

### Acceptance

- A new session plays one short rising chime. Reopening the microphone between turns stays silent (`tasks/silent-listening.md`). Re-invoking an active session starts no new session and plays nothing.
- `[overlay] placement` in `config.toml` selects `bottom-right` (default), `bottom-left`, `top-right`, or `top-left`. An unknown value fails config loading with the allowed list.
- In every placement the orb occupies the same screen rectangle whether compact or expanded. The sheet grows from it toward the middle of the monitor and stays inside the monitor with the 28 px inset.
- A question whose answer is a list or steps puts a titled Markdown answer on the canvas, which opens the expanded view, and speaks a one-sentence summary. Ordinary answers stay spoken only. No extra model round is spent after the canvas is published.
- Full Behave suite passes (`--tags=-asr_model`); native Quickshell check passes.

### Log

- 2026-10-21T19:23:43+05:30 — Claude Code session overlay-layout — in progress. User request: "redesign the agavai layout", add an audio cue when the app starts listening, make placement configurable with the expanded view in the same position as the minimized view, and show visual answers such as lists in the expanded view. Starting commit `9a9a668`; untracked `:memory:.ses` is not mine and is left alone.
  - Findings: the installed `~/.config/omarchy/plugins/janar.agavai/Chat.qml` predates `23f3d37`/`2c40365`. It still centers the expanded sheet and never auto-expands for new results, so the user is seeing the old layout. `siri-surface.md` still waits for install approval. In the repo copy the sheet is in the corner, but the orb moves from the corner to the middle of the sheet when expanded.
  - The listen cue was made silent in `9566b01` because it played on every microphone reopen. The new chime plays only for a fresh session.
  - Plain questions route to the `chat` head, which has no tools, and the system prompt forbids lists. `canvas.display_for` already renders Markdown answer blocks, but no tool produces one. `ChatUi.display()` is unused outside tests.
  - Decisions: placement lives in `~/.config/agavai/config.toml` and reaches the overlay in the snapshot. Omarchy passes per-entry settings to bar widgets, not to overlays. "Redesign" is read as the orb-anchored layout above, not a restyle. Visual answers use a local `show_answer` tool offered on interactive turns, finished in the same round like `request_confirmation`.
  - Planned files: `src/agavai/{tts,__main__,config,ui,canvas,orchestrator}.py`, `plugin/Chat.qml`, `share/config.example.toml`, `features/{tts,config,native_ui,orchestrator}.feature` and steps, `features/support/compact-ui.qml`, `scripts/check-compact-ui.py`, `docs/{flow,ui-design,architecture}.md`, `README.md`, this task. Installing the plugin outside the repo needs approval.
- 2026-10-21 — Claude Code session overlay-layout — start chime committed as `edbe6f0`. `tts.cue_start` writes `start-chime.wav` (587 Hz then 880 Hz) once into the runtime dir and plays it without waiting. `listen_session` calls it once, after `open_stream` succeeds. A recognizer that fails to start plays nothing. Files: `src/agavai/{tts,__main__}.py`, `features/{tts,invocation}.feature`, `features/steps/{tts,invocation,voice_control,asr_meter}_steps.py`, `docs/{flow,ui-design}.md`. Every listen harness now patches `cue_start`, so the suite never plays audio.
- 2026-10-21 — Claude Code session overlay-layout — configurable corner committed as `a4d172c`. Acceptance corrected to `[overlay]` with four corners. Center placements were dropped because a centered orb has no corner for the sheet to grow from. `OverlayConfig.placement` is validated in `load_config`, and `ChatUi` publishes it as snapshot `placement`. `Chat.qml` has one orb pinned to the corner. The sheet grows from it, and its rows reorder and mirror by corner. The header ×, `orbBox`, and `compactOrb` are gone. Files: `src/agavai/{config,ui}.py`, `plugin/Chat.qml`, `share/config.example.toml`, `features/{config,native_ui}.feature` and steps, `features/support/compact-ui.qml`, `scripts/check-compact-ui.py`, `README.md`, `docs/{architecture,flow,ui-design}.md`. `scripts/check-compact-ui.py` checks all four corners compact and expanded. A mutation that centered the orb failed it with "Expanding must not move the orb".
- 2026-10-21 — Claude Code session overlay-layout — theme colors committed as `fed791a`. In Qt 6.12 a bare `Color` resolves to QtQuick's `QQuickColor`, so the theme colors were undefined. The live shell log showed this at `Chat.qml[39:5]` and the text drew black. All plugin files now import `qs.Commons as Commons` and use `Commons.Color`, as the built-in plugins do. Files: `plugin/{Chat,NativeButton,ResultBrowser}.qml`.
- 2026-10-23 — Claude Code session overlay-layout — user approved deploying. Backed up `~/.config/omarchy/plugins/janar.agavai/` to `/tmp/agavai-plugin-pre-overlay-layout`. Copied the committed `plugin/` files there (`manifest.json`, `Chat.qml`, `VoiceOrb.qml`, `NativeButton.qml`, `ResultBrowser.qml`, `BarWidget.qml`, `agavai.png`), the same set `scripts/install.sh` copies; all seven match `plugin/` at `fed791a`. `omarchy plugin validate` exit 0, `rescanPlugins` exit 0. `ping` answers "Target not found" while the overlay is closed, because the IPC handler lives in the overlay. The Python side needs no install: `~/.local/bin/agavai` runs `src/` from this checkout.
  - `show_answer`: the code and five orchestrator scenarios are written but uncommitted. With the real model (Qwen3-4B, temperature 0.2), the full `SYSTEM` prompt gives 0/10 tool calls on list prompts, and so do a final extra system line and a chat-only prompt. "You are a voice assistant. Use show_answer for any list." gives 5/5 list calls. Adding "Answer anything else in one or two short spoken sentences." keeps 5/5 list calls with 0/4 on spoken prompts. Probe scripts are in `/tmp/agavai-probe`.
- 2026-10-23T16:54:50+05:30 — Claude Code session overlay-layout — complete. Visual answers committed as `853100a`. Turns with a ChatUi and no desktop tools offer only `show_answer` and get a new `CHAT_SYSTEM` prompt. `SYSTEM` is back to its committed text for desktop turns. A missing-head retry swaps `messages[0]` to the desktop prompt. Files: `src/agavai/{canvas,orchestrator}.py`, `features/orchestrator.feature`, `features/steps/orchestrator_steps.py`, `docs/{flow,ui-design,architecture}.md`.
  - Prompt evidence (Qwen3-4B, temperature 0.2, `/tmp/agavai-probe`):

    | Prompt | List answers shown | Spoken questions shown |
    |---|---|---|
    | Full prompt, rule first | 1/5 and 2/5 | — |
    | Short prompt, rule after the short-answer rule | 3/5 | — |
    | Rule first, no desktop lines | 5/5 | 0/4 |
    | Shipped `CHAT_SYSTEM` | 5/5 | 0/7 |

    With the shipped prompt, "open the browser" was declined honestly, "say hello" was said, and the time was right. A real `run_turn` with a ChatUi and the keyword router put planets and tea steps on the canvas with new display ids and kept France and arithmetic spoken. "open the browser" still went to `launch`, which was stubbed.
  - Validation:
    - Full Behave suite `--tags=-asr_model`: 23 features, 245 scenarios passed, 3 skipped.
    - `scripts/check-compact-ui.py` passed.
    - `git diff --check` clean.
    - Mutation check: dropping the retry prompt swap fails only the new retry scenario.
  - Deploy: the 16:31 plugin copy did not take effect. Omarchy's hot reload kept the startup copy of plugins outside the config folder: the same `Chat.qml[39:5]`/`[41:5]` QColor warnings came back at 16:31:22, and a new canvas did not auto-expand. `omarchy restart shell` at 16:52 loaded the new files with no QColor warnings. A live check confirmed the fix. It opened the overlay with a test snapshot, published an answer canvas, captured the corner with `grim`, then closed the overlay and restored the user's `ui.json`. The orb stayed in the bottom-right corner both compact and expanded, the sheet expanded on the new canvas, and the theme colors rendered.
  - Not done, reported to the user:
    - The 0.94 sheet background from `8c2ad7b` lets bright windows show through the expanded text.
    - Center placements are not supported.
    - The chime has no off switch.
    - The prototype was not updated.
    - The model once said "Nine十六" for twelve times eight (2026-10-21).
    - `_play_tones` leaves a temp WAV per call.
