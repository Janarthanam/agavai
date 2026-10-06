# Silent listening

- [~] P0 voice Remove repeated listening beeps while preserving speech warmup

### Log

- 2026-10-06 06:27 +0530 — Codex session silent-listening — in progress. User reports constant beeping when listening. `cue_listen` generates two tones on every microphone reopen. Make that cue silent, retain Kokoro warmup, and verify initial and repeated cues. Existing unrelated working-tree changes are outside scope.
- Files: `src/agavai/tts.py`, `features/tts.feature`, `features/steps/tts_steps.py`, `docs/flow.md`, `tasks/silent-listening.md`.
