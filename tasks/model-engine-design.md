# Whistle and Needle engine design

## Status

- [x] P1 docs Show the proposed Whistle/Needle seams, process boundaries, data contracts and latency evidence in an interactive HTML design.

## Acceptance

- Compare current Parakeet and router implementations with proposed Cactus workers.
- Show process ownership, IPC payloads, turn commit and the Qwen/tool/reply loop.
- Distinguish historical measurements, configured budgets and unmeasured candidates.
- Validate offline interactions and desktop/mobile rendering; publish the page in the thread.

## Log

- 2026-10-23T16:34:20+05:30 — Codex session whistle-needle-design — in progress. Starting commit `92dcd94`, clean working tree. Resuming the interrupted HTML request; historical scratch HTML is unavailable. Read current audio/flow/architecture specs and implementation, existing architecture atlas, eval runner, measurement code and report `20261010-1250`. Scope: new `docs/architecture-design/model-engines.html` and this task; no runtime implementation or changes to endpointing policy. Needle is proposed as a router, Whistle automatic endpointing remains undecided. Validation planned: syntax, responsive browser previews, controls, source references and diff review.

- 2026-10-23T16:37:08+05:30 — Codex session whistle-needle-design — implementation complete, awaiting local commit. Added `docs/architecture-design/model-engines.html`: two engine selectors, eight process/data-flow stages, trace controls, historical latency/budget chart, proposed worker contracts and source references. Changed files: this task and the new HTML only. Validation: 187 browser assertions each at 728 px dark, 360 px light and 320 px light, covering six configurations, eight trace controls and expanded evidence/source layout; visual desktop/mobile review; JavaScript syntax; all 22 reference targets checked (local paths checked for existence); six medians match the stored report; whitespace and self-review passed. Published with T3 html_render. No models, microphones or desktop actions run.

- 2026-10-23T16:37:19+05:30 — Codex session whistle-needle-design — complete. Design and validation record committed as `084edd5`. All acceptance items satisfied and interactive HTML published in the thread. This completion update changes only this task. Runtime implementation and the Whistle automatic endpointing decision remain outside this documentation task.
