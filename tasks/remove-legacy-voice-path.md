# Remove the legacy voice path and stale duplicates

## Surface

- [x] P1 voice Remove the Voxtype fallback and the silence-timer path from the assistant
- [x] P2 Merge `agent.md` into `AGENTS.md`
- [x] P2 Bring `docs/architecture.md` in line with the streaming path and retire `docs/v2.md`

### Acceptance

- No assistant command calls `voxtype record start`, `stop`, or `cancel` (`docs/flow.md` Voxtype section).
- `agavai stop` and `agavai cancel` with no live listener do not touch Voxtype.
- Code reachable only through `[vad] enabled = false` or `agavai toggle` is gone: `voxtype.py`, `vad_silero.py`, the energy endpointer, the `transcribing` phase, `[vad]` and `[voxtype]` config. Live helpers (`rms_dbfs`, the `parec` argv) keep their scenarios.
- Configs that still contain `[vad]` or `[voxtype]` load unchanged.
- One agent-instructions file; no rule from either copy is lost.
- Full Behave suite passes (`--tags=-asr_model`).

### Log

- 2026-10-10T19:46+05:30 — Claude Code session bloat-cleanup — in progress. User asked whether the assistant uses Voxtype and flagged bloat; after a read-only survey they said "Implement this" for the proposed cut list. Starting commit `d170bb1` (another session committed `183d74f`/`d170bb1` to `plugin/Chat.qml`, `docs/ui-design.md`, `README.md` during the survey; re-read before editing). Findings: the live path is Parakeet streaming (`listen_session`); Voxtype is reachable only via `toggle`, `[vad] enabled = false`, and the no-listener fallbacks of `cancel`/`stop`, which violate `docs/flow.md` ("must not call record start, stop, or cancel"). User config has no `[vad]` override, so runtime behavior is unchanged. Dropped from the plan: deleting `tests/report/` and committed eval runs, because `tasks/eval.md` records the user asking for `tests/report/` and confirming run folders stay in git. Left `LocalRouter` alone: removing it would route `backend = "local"` to OpenRouter, which needs a decision.
- 2026-10-10T19:59+05:30 — Claude Code session bloat-cleanup — complete. Commits (inspect with `git show <hash>`):
  - `065ec9a` legacy path. Deleted `src/agavai/{voxtype,vad_silero,meter}.py`, `scripts/download-vad.sh`, `features/vad.feature`, `features/steps/vad_steps.py`. Edited `src/agavai/{__main__,asr,config,state,ui,app,a2a}.py`, `plugin/{Chat,BarWidget,VoiceOrb}.qml`, `share/{config.example.toml,a2a-card.json}`, `pyproject.toml`, `features/{asr_meter,config,invocation}.feature`, `features/steps/{asr_meter,config,invocation,native_ui,result}_steps.py`, `docs/{flow,ui-design}.md`, `docs/architecture-design/{index.html,architecture.js}`. `toggle` and `start` commands, `_start_manual`/`_stop`, `transcribing` phase, `VadConfig`, `prompt_file`, `ui.level` VAD arguments and `vad_state`/`vad_backend` snapshot fields removed. `rms_dbfs` and `PAREC_ARGV` moved into `asr.py`; their scenarios moved to `asr_meter.feature`. New scenarios: stop/cancel with no listener start no program; retired `[vad]`/`[voxtype]` sections load. Dropped scenarios covered only deleted code (endpointer, energy/Silero backend, `frame_iter`, `_select_read` stall).
  - `7825bad` no-op loop in `_pid_marker` and unused `time` import in `__main__.py` (both pre-existing).
  - `d41698e` `agent.md` deleted; its Tests section copied word for word into `AGENTS.md`. Diff before deletion showed only that section and the bookkeeping line differed.
  - `4562a58` `docs/architecture.md` rewritten where stale (intro, diagram, process note, config example, Voice I/O, security, source map, script paths); `docs/v2.md` deleted, single-model rationale moved to the `docs/flow.md` rejected-options table; links updated in `README.md`, `docs/flow.md`, `docs/architecture-design/{design.md,index.html}`.
- Validation: `PYTHONPATH=src .venv/bin/behave --tags=-asr_model` with a temporary `XDG_RUNTIME_DIR`: 23 features, 232 scenarios passed, 3 skipped, at `4562a58`. (With `XDG_DATA_HOME` also redirected, two `asr_worker` frontend checks error because the ASR venv is not found; they pass with the real data dir.) `bash -n scripts/*.sh`, `py_compile src/agavai/*.py`, `node --check docs/architecture-design/architecture.js`, `git diff --check`, and a relative-link scan of README and docs passed; the only broken links are two pre-existing `share/config.example.toml` links on `docs/flow.md` lines 3 and 22 (missing `../`), left untouched.
- Not done, for the user: the installed shell plugin still has the old QML (harmless; reinstall with `scripts/install.sh` to pick up the trimmed phases). A running listener keeps its imported code until dismissed. Open decisions: `LocalRouter`/`backend = "local"`; README's "v1 talks to no remote model" versus the Jev default; untracked `:memory:.ses` at the repo root was left in place.
