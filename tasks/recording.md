# Recordings: listen, keep the audio, transcript, notes, translation

In progress: P0. Design in [docs/recording.md](../docs/recording.md).

## Surface

- [ ] P0 voice Record continuously to a recording folder with a live timestamped transcript; start by voice, shortcut, or CLI; stop never discards
- [ ] P0 ui Recording state: red orb ring, timer chip in compact, bar indicator, start and stop chimes, Pause, Mark, and Stop
- [ ] P0 ui Review sheet: player, click a line to seek, highlight during playback, in-place corrections, library list
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
