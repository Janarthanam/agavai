# Durable sessions and spoken-turn audio

- [ ] P2 voice Persist and resume sessions, with explicit audio retention

Status: planned. Owner: unassigned. Depends on [P1 harness events](harness-events.md). User asked how session storage should include audio; the structure below is a recommendation, not implemented behavior. User decision: save ordinary spoken-turn audio by default. Explicit recordings retain existing behavior. This changes the planned default, not the current runtime.

### Proposed structure

- Default durable root: `$XDG_DATA_HOME/agavai/` (normally `~/.local/share/agavai/`), separate from disposable runtime snapshots.
- `sessions.sqlite3`: transactional session/task/turn records, ordered harness events, full execution outcomes, source references/revisions and checkpoints. Version the schema and event payload contracts. Store canonical facts; UI snapshots are rebuildable projections.
- `sessions/<session-id>/audio/<turn-id>.opus`: per-turn audio attachments, saved by default for accepted spoken turns, outside SQLite. Metadata records relative path, codec/sample format, duration, capture timestamps, source span, checksum and retention/deletion status. Typed turns have no audio.
- Preserve committed transcript, correction overlays and original heard text independently of audio. Record ASR/VAD/model/config fingerprints and task/request/call identities for inspection. Event IDs order events; wall-clock timestamps support display, not execution deduplication.
- Link existing durable recordings by recording identity/revision; do not duplicate their audio. Define missing/deleted-source behavior.
- Capture only an explicit recording or an accepted spoken-turn interval with retention enabled by default for ordinary spoken turns, and an explicit opt-out; do not retain continuous background/microphone-idle audio. Implement retention duration, storage limits and deletion/export controls with the selected default.
- Keep audio append/write work off the action-control path with a bounded capture spool. Persist metadata and publish finalized audio atomically; recover interrupted files as incomplete, never silently present them as complete. Do not claim deleted audio still exists.
- Resume reconstructs context and complete tool exchanges from durable records/checkpoints; prompt compaction never deletes the source ledger. Runtime sockets, handles, cancellation callbacks and stale confirmation authority are not serialized.
- Crash recovery never repeats a possibly executed action. Mark interrupted execution unknown; require a fresh user decision where appropriate. Previous pending confirmations require revalidation/reconfirmation after resume.
- Provide session list/new/resume/close APIs and a visible session indicator/history selector through the UI adapter; headless callers use the same repository API. Durable personal preferences/memory remain separately scoped.

### Acceptance to refine before implementation

- E2E BDD: restart/resume, crash during action/audio write, missing source/audio, retention disabled, explicit recording references, correction/compaction preservation, session isolation and delete/export consistency.
- Preserve the user's save-audio-by-default decision; provide configurable directory, retention/storage limits, opt-out and schema migration behavior.
- No raw PCM or audio bytes in the generic event stream or ordinary logs; use attachment references after finalization. Redaction/retention policy applies to persisted text/tool results too.

### Log

- 2026-10-26 — Codex session harness-events — queued as P2 at the user's request. Current sessions remain memory-only; recordings already save audio separately. Initial recommendation: transcript/outcome persistence by default and optional spoken-turn audio, with one SQLite ledger plus filesystem attachments. No runtime or host storage changes for P2. Open preference: opt-in ordinary-turn audio versus retained by default; implementation can proceed after the contract is finalized. Changed files: this task; P1 tracked independently.

- 2026-10-26T09:11:16+05:30 — Codex session harness-events — user selected “Save spoken-turn audio by default.” P2 must retain accepted spoken-turn audio by default, expose retention controls/opt-out, and keep typed turns audio-free. Continuous idle/background audio remains excluded. Changed file: this task only; no capture/storage behavior changed yet.

- 2026-10-26T09:29:21+05:30 — Codex session harness-events — reconciled the proposed structure and acceptance with the selected audio default. Plan: transactional SQLite facts/checkpoints plus separate finalized Opus attachments, recording references, crash-safe unknown-action recovery, and session list/resume/close UI/API. P2 remains planned; no storage/capture implementation. Changed file: `tasks/session-persistence.md`.
