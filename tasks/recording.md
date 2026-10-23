# Recordings: listen, keep the audio, transcript, notes, translation

Waiting for input. The design is proposed in [docs/recording.md](../docs/recording.md). Before implementation, the user needs to decide:

1. Audio sources for the first version: microphone only, or also computer audio.
2. Translation languages, spoken and target. This decides the offline model: Parakeet-TDT-0.6B-v3 for 25 European languages, or a Whisper-family model for Tamil, Hindi, and others.
3. Recording folder and retention (proposed: `~/Documents/Agavai/Recordings/`, kept until deleted).
4. Record shortcut (proposed: repurpose Super+Ctrl+M, which today duplicates Super+M). This edits `~/.config/hypr/bindings.lua`, outside the repo.

## Surface

- [ ] P0 voice Record continuously to a recording folder with a live timestamped transcript; start by voice, shortcut, or CLI; stop never discards
- [ ] P0 ui Recording state: red orb ring, timer chip in compact, bar indicator, start and stop chimes, Pause, Mark, and Stop
- [ ] P0 ui Review sheet: player, click a line to seek, highlight during playback, in-place corrections, library list
- [ ] P1 voice Offline polish pass, title, Notes and Translation views, voice follow-ups and search over recordings
- [ ] P2 voice Computer audio as a second channel, live translation, glossary from corrections

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
