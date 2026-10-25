# Agavai voice-agent harness design

- [~] P0 voice Design Agavai as an in-process harness for voice, context, routing and tool execution

Status: in progress. Owner: Codex session voice-agent-harness. User expanded scope to an architectural rewrite with implementation, documentation and E2E BDD parity. No host deployment is part of this rewrite.

### Acceptance

- Define Agavai's in-process harness and its model/service adapters; separate current behavior from proposed changes.
- Specify semantic routing, turn commitment, corrections, pauses, task continuation/change, context budgets and compaction.
- Define tool authorization, execution lifecycle, cancellation, result interpretation and truthful completion.
- Include module contracts, failure handling, migration, Mermaid architecture and critical-use-case sequences, and E2E BDD acceptance criteria.
- Implement the harness, migrate existing callers and tests, align authoritative docs, validate and commit locally.

### Log

- 2026-10-25T22:43:54+05:30 — Codex session voice-agent-harness-design — started at `09bdac7`, clean tree, branch `t3/test-whistle-needle-engines`. Read design-doc skill, runtime authority `docs/flow.md`, speech/UI/engine/recording specs, existing context/control tasks, current orchestration/adapters and native comparison evidence. User asks to design an independent harness; proposed default is a local reusable library with a thin Agavai adapter, pending optional clarification. Changes planned: `docs/voice-agent-harness.md`, this tracker. Current main differs by deployment bookkeeping; no runtime source changes are needed for this task.

- 2026-10-25 — Codex session voice-agent-harness-design — scope clarified by user: Agavai itself is the harness, in process; local ASR/VAD/reasoning and other models are integrated as services. This supersedes the proposed separate reusable library boundary. Design an internal controller and explicit provider contracts, without a new daemon or independent framework. Runtime rewrite remains a staged proposal in this design task.

- 2026-10-25 — Codex session voice-agent-harness — user explicitly authorized the architectural rewrite and complete code/docs parity. Fast-forwarded this branch onto main `c2d34a9` to retain deployment records. Implementation scope: move session control out of CLI; establish harness-owned context, semantic routing and execution; make UI a projection; add source-bound recording follow-ups/corrections and bounded context compaction; migrate internal callers/evals/BDD and current architecture/runtime docs. Existing speech/runtime workers, desktop dispatch and native surfaces will be reused. The initial design-only scope is superseded.

- 2026-10-25 — Codex session voice-agent-harness — ownership migration implemented: CLI delegates to `harness/session.py`; `harness/engine.py` replaces the old orchestrator; `Harness` owns `ContextStore`, pending actions and complete task history. UI is presentation only. Model inputs use bounded complete-exchange projections. `ExecutionManager` retains outcomes; adapters emit explicit error/unknown status rather than inspecting result text. Internal callers, eval runner and existing BDD fixtures migrated together. Validation: ownership baseline 439 scenarios/2157 steps passed (5 opt-in skipped); typed action/control regression 77 scenarios/664 steps passed. Remaining initial full-slice fixture issues corrected: explicit UI failure status and dispatch boundary for invalid wallpaper paths. Changed: `src/agavai/{__main__,app,tools,ui,outcomes}.py`, new `src/agavai/harness/`, `evals/runner.py`, affected `features/steps/`, `features/chat_ui.feature`, `features/support/tool_replay.py`. Behavioral routing, source binding and interruptible inference follow next.
