# Recordings: listen, keep the audio, transcript, notes, translation

Waiting for input. P0 is implemented and committed on branch `feature/recordings`, kept off `main` until it is tested. Not deployed. Design: [docs/recording.md](../docs/recording.md).

Decisions needed:

1. **How to deploy.** Since 2026-10-23 21:10, another session's deployment from the `t3/test-whistle-needle-engines` worktree has been live:
   - `~/.local/bin/agavai` and `agavai-llm` point to that worktree.
   - `~/.config/agavai/config.toml` uses the Whistle/Cactus recognizer.
   - The Qwen `agavai-llm` service is disabled.
   - Its `Chat.qml` is installed.

   That branch forked from `92dcd94`, so it lacks this work and the earlier overlay fixes. Deploying `main` means undoing that test deployment, using its `ROLLBACK.md` under `~/.local/share/agavai/deployments/`, or merging the two branches first.
2. **The Super+Ctrl+M binding.** The user approved it. It waits for the deploy, because the live `agavai` does not have `record`.

## Surface

- [~] P0 voice Record continuously to a recording folder with a live timestamped transcript; start by voice, shortcut, or CLI; stop never discards
- [~] P0 ui Recording state: red orb ring, timer chip in compact, bar indicator, start and stop chimes, Pause, Mark, and Stop
- [~] P0 ui Review sheet: player, click a line to seek, highlight during playback, in-place corrections, library list
- [ ] P1 voice Offline polish pass, title, Notes view, voice follow-ups and search over recordings
- [ ] P2 voice Computer audio as a second channel, translation, glossary from corrections

### Log

- 2026-10-23T19:48:55+05:30 — Claude Code session overlay-layout — waiting for input. User request: add "just listening and recording" that stores the audio "along with transcript and corrections so that I can listen to later", natively in the app, "in a completely intuitive way" for note taking, translation, transcription, and similar uses.
  - Findings:
    - **Capture.** `asr.StreamingRecognizer` starts `parec` per utterance and stops it at each end of utterance.
    - **Live recognizer.** `parakeet_worker.Stream` drops audio after an EOU until the parent resets it, and `MelStream` counts frames, so segment timing is available. Parakeet EOU is English only, with no punctuation.
    - **Offline model.** `parakeet-tdt-0.6b-v3` is present under Voxtype's model dir.
    - **Prior art.** `voxtype meeting` exists, unused ("No meetings found"). It is a separate daemon.
    - **Encoders.** ffmpeg has libopus and flac.
    - **LLM context.** `ctx_size = 8192`.
    - **Playback.** `ResultBrowser.qml` already uses QtMultimedia for video.
    - **Bar pattern.** Omarchy's screen recording uses a toggle key (Alt+Print) and a bar indicator that stops on click.
    - **Free shortcuts.** Super+Shift+M and Super+Shift+Alt+M are Music. Super+Alt+M is free.
  - Decisions proposed, all recorded in the design doc:
    - Record first, choose views later.
    - Speech is content while recording. Only isolated "Agavai stop/pause/resume/mark" act, and nothing is routed to OpenRouter.
    - Native in Agavai, not Voxtype meeting mode.
    - Two recognizer passes: live, then offline.
    - WAV while recording, Opus when done.
    - Corrections as a layer.
    - One `recording.json` source with Markdown exports.
  - Files: `docs/recording.md` (new), this task. No code changed.
- 2026-10-23T20:02:33+05:30 — Claude Code session overlay-layout — in progress. User decisions:
  1. "start with microphone for now. we will add computer audio in a bit."
  2. "translation can be done later."
  3. Folder approved: "store until deleted."
  4. Shortcut: "works. Super+M is fine." Read as Super+Ctrl+M becoming the record toggle, with Super+M unchanged.
  - Design doc updated with these decisions. Starting P0.
  - Findings: the Parakeet EOU worker reports ready in about 1.3 s, and its model is 685 MB with 48 GB free. A recording therefore runs its own continuous worker while the assistant's stays loaded.
- 2026-10-24T01:00:12+05:30 — Claude Code session overlay-layout — P0 implemented and committed; waiting for input on deployment.
  - **Commits.**
    - `74be7f7`: continuous worker mode. `--continuous` keeps decoding after an EOU and times each one (`start_ms`, `end_ms`).
    - `9add957`: recorder backend. `recording.py`, `agavai record [toggle|stop|pause|resume|mark]`, and `listen --record`. Requests go through `record.request` and SIGUSR1. Audio is a growing WAV, then a verified Opus file; `recording.json` and `transcript.md` follow. Also crash recovery, an empty recording leaving no folder, the "Agavai stop/pause/resume/mark" controls, pause with time conversion, record chimes, the `recording` state, and `[recordings] dir`.
    - `bf9505e`: the `recordings` head with `start_recording` (the same toggle, sent to this session) and `list_recordings` (canvas `recordings`). Both are excluded from MCP.
    - `065849b`: `agavai recording correct`, limited to the recordings folder.
    - `1c34509`: overlay. VoiceOrb recording and paused rings, the timer chip, `RecordingLive.qml`, `RecordingView.qml`, `Clock.js`, the bar indicator, install.sh, and the native recording scenario with a stub agavai.
    - `dbac5d2`: docs.
  - **Files.**
    - `src/agavai/{parakeet_worker,asr,recording,__main__,ui,state,tts,config,tools,heads,canvas,mcp_server}.py`
    - `plugin/{Chat,VoiceOrb,BarWidget,RecordingLive,RecordingView}.qml`, `plugin/Clock.js`
    - `scripts/{install.sh,check-compact-ui.py}`, `share/config.example.toml`
    - `features/{recording,config,heads,mcp,asr_worker}.feature` and their steps, `features/support/{asr_checks.py,compact-ui.qml}`
    - `docs/{recording,flow,ui-design,architecture}.md`, `README.md`
  - **Validation.**
    - Full Behave suite: 270 scenarios passed, 4 skipped. This ran with `AGAVAI_CONFIG` set to the pre-deployment config backup, because the live config's Cactus venv has no numpy and two `asr_worker` checks read the live config.
    - `asr_worker.feature` with the real model: 6/6, including the continuous replay. Two utterances keep their text and timing, and a 0 ms gap keeps every word.
    - Real pipeline: the real worker, pump, recorder, and ffmpeg, with the speech fixture in place of parec. Both lines came back at 0.02 s and 7.22 s, the duration was 14.665 s against 14.664 s expected, the Opus was verified and the WAV removed.
    - Mutation checks (pause gap, control matching, save on dismiss, MCP exclusion via a fake in DISPATCH) each fail one scenario.
    - Nothing was written to the real `~/Documents/Agavai`.
  - **Not validated.** The native overlay check could not finish. From about 23:00 the monitors were off (DPMS) and the session locked, so Hyprland rendered no frames: grim hung, ListView rows were never laid out, and no surface got focus on map. The committed plugin fails the same compact step 6 focus check, so this is environmental. Before that, recording scenario steps 0–4 passed: chip and time, live lines, the heading, the Pause and Mark commands reaching the stub, the paused state, and the review opening. Steps 5–8 (play from a line, correct, the list and back) still need a run with the screen on: `scripts/check-compact-ui.py recording`, then all scenarios.
  - **Observed, not changed.**
    - Native focus checks depend on the compositor rendering, and probably on the pointer position under `follow_mouse = 1`.
    - `features/asr_worker.feature` reads the live user config.
    - "record my screen" would route to the recordings head; the tool description says it is not for the screen.
- 2026-10-24T08:59:37+05:30 — Claude Code session overlay-layout — moved to a feature branch at the user's request: "main would probably merge more changes before this can be tested." Commits `02e93f4`..this one are on `feature/recordings`. Local `main` was reset to `origin/main` (`68f2fc7`); none of this was on `origin`, so nothing was force-pushed. To test or deploy, rebase or merge `feature/recordings` onto the current `main` first.
