# Clear the canvas when the conversation changes

Use the context response to distinguish a new conversation from a follow-up. An unrelated query clears earlier conversation output; a related query keeps the context and results it needs.

## Surface

- [x] P1 ui Clear prior conversation output for an unrelated query and retain it for a follow-up

### Acceptance

- Decide from the current query and earlier conversation, rather than whether this is the second utterance or whether tool heads match.
- Clear earlier canvas results, turns, answer, completion, model messages, and inherited tool heads for a new conversation.
- Preserve the earlier results and model context for a follow-up, and keep the listening session active.
- Leave partial speech and silence outside the context decision.

### Log

- 2026-10-08T16:56:28+05:30 — Codex session conversation-context — in progress. User requested task bookkeeping and implementation. Starting commit: `f44544c`. Existing listen loop treats every later utterance as a continuation; `run_turn` retains the canvas and merges previous model messages and tool heads without testing relevance. Reviewed `docs/flow.md` (runtime authority), `docs/ui-design.md`, `docs/architecture.md`, `docs/v2.md`, UI snapshot and orchestrator patterns. Working tree contains existing changes from other sessions; this task will keep its diff separate.
- Planned files: `src/agavai/orchestrator.py`, `src/agavai/ui.py`, `docs/flow.md`, `docs/ui-design.md`, `features/orchestrator.feature`, `features/steps/orchestrator_steps.py`, and this task file. Reuse the local model chat client for a bounded context classification before the action turn.
- 2026-10-08T17:04:00+05:30 — Codex session conversation-context — implementation and validation. The local model returns `follow_up` or `new_conversation` with no tools, temperature zero, and 16 output tokens. A new conversation clears output and inherited messages/heads before routing; the existing session id is retained so cancellation continues to suppress late writes. Invalid/failed decisions keep prior results and surface an error. Added `features/conversation_context.feature` for new topics, short follow-ups, same-head resets, errors, cancellation, first/fresh turns, partials, and empty input. Updated the runtime and UI specifications.
- Validation so far: the original 45 relevant scenarios passed before implementation; 57 focused scenarios and seven read-only classifications against the actual local model passed afterward. The broad sandbox run had two speech-test failures caused by denied runtime writes; rerunning with `XDG_RUNTIME_DIR=/tmp/agavai-conversation-context-tests` outside the sandbox passed all 158 non-model scenarios (three ASR model replays skipped). Final review added explicit inherited-head and context-tool-call rejection checks; validating those before committing.
- Changed files: `src/agavai/orchestrator.py`, `src/agavai/ui.py`, `docs/flow.md`, `docs/ui-design.md`, `features/orchestrator.feature`, `features/conversation_context.feature`, `features/steps/orchestrator_steps.py`, `tasks/conversation-context.md`. No other session's changes are part of this task.
- 2026-10-08T17:13:36+05:30 — Codex session conversation-context — complete. Implementation committed as `260705f57ed395ec3a74b9901d9a2b84849c97ec`. Final focused run: `PYTHONPATH=src .venv/bin/behave -f progress features/conversation_context.feature features/orchestrator.feature features/chat_ui.feature features/native_ui.feature features/invocation.feature` — 58 scenarios, 385 steps passed. Seven real local-model classifications passed. Broad validation: 158 scenarios passed with three ASR model replays skipped, using the isolated temporary runtime noted above. Reviewed the implementation and test diff against the acceptance criteria. The installed launcher resolves to this repository; a newly opened Agavai session loads the fix.
- Concurrent-edit reconciliation: independent display-id and spoken-name hunks arrived during commit approval and entered the initial local commit `74f9718`. Restored the original staged task snapshot into `260705f` without changing working files; retained `74f9718` on `codex/conversation-context-collision`. Those other-session hunks remain uncommitted in the working tree. Repeated the 58 focused scenarios against the combined working tree; all passed.
