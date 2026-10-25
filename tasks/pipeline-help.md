# Version and pipeline help

- [ ] P1 ui Show the running version and each pipeline stage from a small help icon

Status: in progress.

### Acceptance

- Expanded native overlay has a keyboard-accessible help toggle and bounded scrolling details; compact input and capture remain unchanged.
- Version comes from running Python code, with source revision when available. Configuration comes from the session's loaded Config, never a newly read config or an old snapshot.
- Configured stages and latest-turn execution are explicitly distinguished. Routing bypass/fallback, brain escalation and speech selection report actual decisions. Recording explains its model bypass.
- E2E BDD and native overlay checks cover the behavior; changes reviewed and committed.

### Log

- 2026-10-25T18:36:56+05:30 — Codex session pipeline-help — started at `31db757`, clean tree. Scope: native help UI, session metadata and execution reporting, governing UI/flow docs and BDD/native checks. Existing `ChatUi` atomic snapshots and `NativeButton` will be reused. `setup.walkthrough` is CLI-oriented and includes saved-config/service assumptions; help will describe the loaded session and separately report actual execution. Planned files: `src/agavai/{ui,router,orchestrator,tts,__main__}.py`, `evals/runner.py` routing observer, `plugin/Chat.qml`, `docs/{ui-design,flow}.md`, `features/pipeline_help.feature`, its steps and the existing native harness/script.

- 2026-10-25T18:55:00+05:30 — Codex session pipeline-help — implementation and review in progress. Added session version/config snapshots, explicit requested-model labels with endpoints, actual routing/escalation/tool/speech events, and the native help toggle. Shared TTS preference ordering with execution to prevent drift. Updated the eval routing observer and confirmation-budget fixture for the reporting argument. New CLI E2E scenarios use local HTTP services and the real dispatcher/snapshot path; existing engine BDD now checks combined Needle routing and Qwen fallback reporting. Full suite passed 438 scenarios/2152 steps before the final speech-order scenario; targeted TTS/controls/help and all 84 engine scenarios pass. Native help passes with seven new scenarios/39 steps; the complete existing native run exposed a focus-fixture mapping issue being reconciled. The isolated runtime needed access to Hyprland sockets plus a shorter temp path (AF_UNIX path limit) to select the focused monitor accurately on this two-monitor desktop. No installed configuration changed. Changed files: `src/agavai/{ui,router,orchestrator,tts,__main__}.py`, `evals/runner.py`, `plugin/Chat.qml`, `docs/{ui-design,flow}.md`, `features/pipeline_help.feature`, `features/steps/{pipeline_help,engine,voice_control}_steps.py`, `features/support/compact-ui.qml`, `scripts/check-compact-ui.py`, this task.

- 2026-10-25T19:02:18+05:30 — Codex session pipeline-help — implementation and self-review finished, awaiting commit. Final full E2E BDD run with `AGAVAI_NATIVE_UI_CHECK=1`, example config and installed Cactus/Silero test assets: 31 features, 440 scenarios and 2159 steps passed; four opt-in brain-comparison scenarios skipped. Native scenario runs all four real Quickshell checks (compact, canvas-focus, recording, help), including keyboard scrolling/Escape, Enter isolation, all corners, live updates, stale metadata and recording bypass. Corrected the focus fixture by mapping with on-demand focus and parenting QtTest to the target window. Inspected the captured help panel visually; version and wrapped stage details are readable. `git diff --check` clean. Scope reviewed against the user request; no deployment or installed files changed.
