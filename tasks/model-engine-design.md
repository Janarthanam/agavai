# Whistle and Needle engine design

## Status

Complete: Omarchy design and replacement visual committed as `9bdeea4`. Proposed endpoint policy and model-tier choices are documented in [the design](../docs/model-engines.md). Runtime implementation is outside this task.

- [x] P1 docs Show the proposed Whistle/Needle seams, process boundaries, data contracts and latency evidence in an interactive HTML design.

## Acceptance

- Show small-local-model-first answering, with larger-model escalation only when needed; do not assume every request needs both Needle and Qwen.
- Compare current Parakeet and router implementations with proposed Cactus workers.
- Show process ownership, IPC payloads, turn commit and the Qwen/tool/reply loop.
- Distinguish historical measurements, configured budgets and unmeasured candidates.
- Validate offline interactions and desktop/mobile rendering; publish the page in the thread.

## Log

- 2026-10-23T16:34:20+05:30 — Codex session whistle-needle-design — in progress. Starting commit `92dcd94`, clean working tree. Resuming the interrupted HTML request; historical scratch HTML is unavailable. Read current audio/flow/architecture specs and implementation, existing architecture atlas, eval runner, measurement code and report `20261010-1250`. Scope: new `docs/architecture-design/model-engines.html` and this task; no runtime implementation or changes to endpointing policy. Needle is proposed as a router, Whistle automatic endpointing remains undecided. Validation planned: syntax, responsive browser previews, controls, source references and diff review.

- 2026-10-23T16:37:08+05:30 — Codex session whistle-needle-design — implementation complete, awaiting local commit. Added `docs/architecture-design/model-engines.html`: two engine selectors, eight process/data-flow stages, trace controls, historical latency/budget chart, proposed worker contracts and source references. Changed files: this task and the new HTML only. Validation: 187 browser assertions each at 728 px dark, 360 px light and 320 px light, covering six configurations, eight trace controls and expanded evidence/source layout; visual desktop/mobile review; JavaScript syntax; all 22 reference targets checked (local paths checked for existence); six medians match the stored report; whitespace and self-review passed. Published with T3 html_render. No models, microphones or desktop actions run.

- 2026-10-23T16:37:19+05:30 — Codex session whistle-needle-design — complete. Design and validation record committed as `084edd5`. All acceptance items satisfied and interactive HTML published in the thread. This completion update changes only this task. Runtime implementation and the Whistle automatic endpointing decision remain outside this documentation task.

- 2026-10-23T16:48:42+05:30 — Codex session whistle-needle-design-rewrite — reopened after user review. Previous page met mechanical checks but failed the core requirement of human understanding: an inventory replaced an architecture diagram, details obscured roles, and the worked request was fragmented. Scope remains the same HTML and task. Replace with a labeled process graph, plain-language roles, one complete example and an honest latency summary. Keep protocol/eval details behind disclosure. No runtime changes.

- 2026-10-23T16:54:40+05:30 — Codex session whistle-needle-design-rewrite — rewrite ready for review. Replaced the inventory with one process graph and labeled audio, text, prompt, tool/result and speech paths; current/proposed toggle; a complete browser-opening example; four latency checkpoints with provenance. Main desktop view reduced from about 3841 px to 1937 px; implementation details are disclosed on demand. Corrected the capture path to show audio passing through the session before recognition. Changed files: `docs/architecture-design/model-engines.html` and this task. Validation: visually inspected proposed/current desktop and phone views; checked toggle state and graph-label bounds at 728/320 px; checked expanded-page width, JS syntax, local references and whitespace; published replacement with html_render. Runtime unchanged. Leaving the task open for review of the explanation rather than treating layout checks as user acceptance.

- 2026-10-23T17:31:09+05:30 — Codex session model-escalation-note — recorded user direction in `docs/v2.md` and this task: small local model first; larger model only if no answer; Qwen is a local brain. This supersedes the router-only interpretation of the candidate design. Tier assignments, larger-model deployment and escalation criteria remain unspecified. Existing HTML is explicitly marked as needing revision; no runtime or HTML changes in this note. Validation: reviewed the two-file Markdown diff and whitespace.

- 2026-10-23 — Codex session omarchy-engine-design — in progress, starting at `58a670b`, clean tree. Scope: `docs/model-engines.md`, replacement HTML and this log. User narrowed platform scope to Omarchy. Verified cactus-needle 3.2.8 Whistle streaming API: committed/pending text and flush tail, no turn-end event in that contract. Design separates recognition from endpointing and model roles from runtimes; no runtime implementation.

- 2026-10-23 — Codex session omarchy-engine-design — documentation ready. Changed files: `docs/model-engines.md`, `docs/architecture-design/model-engines.html`, this task. Reviewed contracts against source and current specs; checked local references and whitespace; inspected 728 px dark and 360 px light previews (including expanded details), no console errors. Published with html_render. No runtime tests or model benchmarks run; performance figures are explicitly targets, historical evidence or unknowns.

- 2026-10-23 — Codex session omarchy-engine-design — complete. Design committed as `9bdeea4`; validation recorded above. This completion entry changes only task bookkeeping.
