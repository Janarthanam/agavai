# Structured harness results and clients

- [x] P1 voice Return typed turn outcomes and migrate clients

Status: complete (implementation committed at `b253af8`; not deployed). Owner: Codex session harness-results. User approved the proposed TurnResult and client changes. No deployment or host configuration/data changes.

### Acceptance

- Public Harness and engine return detached, serializable TurnResult values: identities, explicit status, optional speech/content, this request's full execution outcomes and event sequence bounds.
- Final task_status event embeds the same result before return; persistence and native status remain consistent. Cancellation retains completed effects and suppresses speech. Confirmation authority stays internal.
- Empty input creates no request and preserves pending confirmation; return needs_input with no request/event range. Audio finalization remains asynchronous and observable through audio_status.
- Migrate voice, CLI, evaluation and BDD callers without string compatibility shims. Preserve event-only native rendering and infrastructure exception propagation.
- E2E BDD covers outcomes, confirmation/controls, cancellation, failed/unknown actions, source content, isolation, persistence/resume and client speech behavior. Update governing documentation and commit after validation/review.

### Log

- 2026-10-26T19:29:25+05:30 — Codex session harness-results — started from clean `e0abffc`. Read current harness design/runtime/architecture/persistence/UI contracts, events/engine/execution/storage, voice and CLI clients, eval caller and existing BDD replays. Reuse execution ledger and normalized content; add no model policy or persistence schema migration. Planned files: `src/agavai/harness/{results,__init__,engine,events,session}.py`, `src/agavai/__main__.py`, `evals/runner.py`, related BDD steps/support and new result scenarios, current harness/architecture/runtime/persistence/test docs, this task. Final event gains an additive result payload; blank input is explicitly outside the committed trace.

- 2026-10-26T19:44:00+05:30 — Codex session harness-results — implemented typed TurnResult/ToolExecution/TurnStatus exports, detached serialization, request-local execution/content projection and one final event/result state. Migrated public/engine signatures, voice, typed CLI, evaluator and all string-consuming BDD callers. Preserved recording takeover: cancelled inference does not dismiss the listener unless its dismissal input is set. Blank input retains pending authority without admitting a request. Updated canonical design (including client sequence), architecture/runtime/UI/persistence docs and test instructions. Cold diff review complete. Full BDD with actual installed ASR/Cactus/Silero assets: 528 scenarios / 2655 steps passed, 6 optional skips (four model comparisons and two native interactions). Two additional client-cancellation scenarios added afterward; final focused result/client BDD: 26 scenarios / 172 steps passed. Compileall and diff whitespace checks passed. No unit tests, installed-data/config changes, merge or deployment. Logs: `/tmp/agavai-results-full.log`, `/tmp/agavai-results-final-focused.log`. Changed files: `README.md`, `docs/{architecture,flow,session-persistence,ui-design,voice-agent-harness}.md`, `docs/architecture-design/design.md`, `evals/runner.py`, `features/harness_results.feature`, `features/steps/{engine,harness_event,harness_result,harness,orchestrator,request_log,voice_control}_steps.py`, `features/support/persistent_process.py`, `src/agavai/__main__.py`, `src/agavai/harness/{__init__,engine,events,results,session}.py`, `tests/README.md`, this task. Implementation complete; awaiting local commit.

- 2026-10-26T19:45:00+05:30 — Codex session harness-results — completed acceptance at local implementation commit `b253af8`; full changed-file list and diff available with `git show --stat b253af8` / `git show b253af8`. Validation and limitations recorded above; no merge/deployment. Working tree was clean after implementation commit. Changed file for completion bookkeeping: this task.
