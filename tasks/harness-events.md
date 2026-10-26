# UI-independent harness events

- [x] P1 voice Decouple the harness from ChatUi through an explicit event interface

Status: complete. Owner: Codex session harness-events. User requested P1 so the harness can be exercised separately from the UI. No deployment or host configuration changes.

### Acceptance

- Harness accepts an event sink and cancellation input without a concrete ChatUi or snapshot dependency.
- Ordered, serializable events carry session/task/request identity and detached payloads for lifecycle, input, decisions/models, tools, answers, source changes, recording and task status.
- The native UI consumes events through one adapter; producers never read or mutate UI data. Preserve existing CLI, voice, recording, confirmation and cancellation behavior.
- Sink presence may enable interactive answer/confirmation delivery; it does not require a graphical UI. Cancellation remains an input, not a return value from an event consumer.
- Headless E2E BDD uses the real harness and model transport with a collector, no UI snapshot/native renderer, and scripted external service/OS boundaries. Cover confirmations, action outcomes, context/source events, cancellation and event ordering/identity.
- Update current architecture/interface documentation and migrate callers/evals/BDD together. Only E2E BDD verification.

### Log

- 2026-10-26 — Codex session harness-events — started at clean `33bf243`. Read runtime, harness, UI, recording and task conventions; searched for existing event interfaces/persistence. Existing pipeline_event is a ChatUi method, not a reusable event transport. Scope: `harness/` output contract and producers, native adapter in `ui.py`, CLI/eval/BDD wiring, current docs and this tracker. Reuse existing tool normalization, UI methods and provider interfaces. P2 persistence is tracked separately; P1 adds no session database or audio retention policy.

- 2026-10-26T09:29:21+05:30 — Codex session harness-events — implementation/review: added `HarnessEvent`, synchronous detached output and independent cancellation input; migrated engine/source/session producers, native adapter, CLI, evals and BDD callers. Explicit task transitions, prepared confirmations, call IDs and full outcomes are observable. Late inference cannot emit; dispatched side effects report actual completion before cancelled status. Consumer failures raise `EventDeliveryError` with their original cause. No event queue, replay persistence or new model policy. Focused regression: 67 scenarios / 376 steps passed. Headless E2E after review: 14 scenarios / 82 steps passed. First full suite before final consumer-error changes: 469 scenarios / 2341 steps passed, 5 optional skipped; final suite running.

- 2026-10-26T09:29:21+05:30 — Codex session harness-events — test-isolation incident: a recording-launch mock still patched the previous import location and two real recording workers started at 09:14 and 09:15. Both exited; the attributable live worker was stopped gracefully. User explicitly approved deleting only `2026-10-26 09.14 Recording` and `2026-10-26 09.15 Recording` under `/home/janar/Documents/Agavai/Recordings/`. Those two folders were deleted and absence verified. Corrected launcher mocks now patch `agavai.app.start_session`; the recording-launch scenario and focused regression passed. No other recordings were deleted and no host configuration was changed.

- 2026-10-26T09:29:21+05:30 — Codex session harness-events — changed files for handoff: `src/agavai/harness/{__init__,events,engine,execution,session,source_turn}.py`, `src/agavai/{__main__,app,brain,ui}.py`; `evals/runner.py`; `features/harness_events.feature`, `features/orchestrator.feature`, `features/steps/{harness_event,harness,asr_meter,chat_ui,engine,invocation,native_ui,orchestrator,pipeline_help,recording,request_log,voice_control}_steps.py`, `features/support/{session_replay,tool_replay}.py`; `docs/{architecture,flow,ui-design,voice-agent-harness}.md`, `docs/architecture-design/design.md`, `tests/README.md`, this task. P2 storage plan is separately tracked in `tasks/session-persistence.md`. Native compositor focus limitation remains documented under the original harness task; this P1 does not fix it or claim a native desktop rerun.

- 2026-10-26T09:30:51+05:30 — Codex session harness-events — final validation: full Behave suite with installed Cactus/Silero assets and native compositor opt-in unset: 471 scenarios / 2353 steps passed, 0 failed, 5 optional scenarios skipped (four model-comparison experiments and one desktop-help check). All 14 headless scenarios passed separately (82 steps). Python compilation and `git diff --check` passed. Reviewed runtime, adapter, caller migrations, event payloads, BDD and current documentation; reused canvas normalization and existing projection/provider/execution contracts. Implementation complete, awaiting local commit; P2 remains planned.

- 2026-10-26T09:31:03+05:30 — Codex session harness-events — completed P1 in local commit `c86f80a` after the validation above (471 scenarios / 2353 steps passed; 5 optional skipped). P2 plan committed as `48075d0` and remains planned. Changed file in this completion update: `tasks/harness-events.md`. No deployment or native desktop rerun.
