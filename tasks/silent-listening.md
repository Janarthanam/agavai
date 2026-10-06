# Silent listening

- [x] P0 voice Remove repeated listening beeps while preserving speech warmup

### Log

- 2026-10-06 06:27 +0530 — Codex session silent-listening — in progress. User reports constant beeping when listening. `cue_listen` generates two tones on every microphone reopen. Make that cue silent, retain Kokoro warmup, and verify initial and repeated cues. Existing unrelated working-tree changes are outside scope.
- Files: `src/agavai/tts.py`, `features/tts.feature`, `features/steps/tts_steps.py`, `docs/flow.md`, `tasks/silent-listening.md`.
- 2026-10-06 06:30 +0530 — Codex session silent-listening — complete. Fix committed as `9566b01`. Full Behave suite passed: 16 features, 123 scenarios, 467 steps, using `XDG_RUNTIME_DIR=/tmp/agavai-silent-listening-tests` to keep test runtime writes in the sandbox. `git diff --check` passed. Installed launcher resolves to this repository, so reopening Agavai loads the fix. Audible hardware verification was not performed.
