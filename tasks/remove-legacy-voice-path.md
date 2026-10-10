# Remove the legacy voice path and stale duplicates

## Surface

- [ ] P1 voice Remove the Voxtype fallback and the silence-timer path from the assistant
- [ ] P2 Merge `agent.md` into `AGENTS.md`
- [ ] P2 Bring `docs/architecture.md` in line with the streaming path and retire `docs/v2.md`

### Acceptance

- No assistant command calls `voxtype record start`, `stop`, or `cancel` (`docs/flow.md` Voxtype section).
- `agavai stop` and `agavai cancel` with no live listener do not touch Voxtype.
- Code reachable only through `[vad] enabled = false` or `agavai toggle` is gone: `voxtype.py`, `vad_silero.py`, the energy endpointer, the `transcribing` phase, `[vad]` and `[voxtype]` config. Live helpers (`rms_dbfs`, the `parec` argv) keep their scenarios.
- Configs that still contain `[vad]` or `[voxtype]` load unchanged.
- One agent-instructions file; no rule from either copy is lost.
- Full Behave suite passes (`--tags=-asr_model`).

### Log

- 2026-10-10T19:46+05:30 — Claude Code session bloat-cleanup — in progress. User asked whether the assistant uses Voxtype and flagged bloat; after a read-only survey they said "Implement this" for the proposed cut list. Starting commit `d170bb1` (another session committed `183d74f`/`d170bb1` to `plugin/Chat.qml`, `docs/ui-design.md`, `README.md` during the survey; re-read before editing). Findings: the live path is Parakeet streaming (`listen_session`); Voxtype is reachable only via `toggle`, `[vad] enabled = false`, and the no-listener fallbacks of `cancel`/`stop`, which violate `docs/flow.md` ("must not call record start, stop, or cancel"). User config has no `[vad]` override, so runtime behavior is unchanged. Dropped from the plan: deleting `tests/report/` and committed eval runs, because `tasks/eval.md` records the user asking for `tests/report/` and confirming run folders stay in git. Left `LocalRouter` alone: removing it would route `backend = "local"` to OpenRouter, which needs a decision.
