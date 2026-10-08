# Speak result names, not paths

Typed results (files, folders, images, videos) should be read by the name for that type.

Result-canvas status: waiting for input. Implementation is committed and validated; approved Agavai reopening is pending so the running listener loads the new speech rules.

## Surface

- [x] P0 voice Read files and images by name
- [~] P0 voice Keep result speech brief without full filenames

### Log

- 2026-10-01 07:10 +0530 — Cursor session spoken-names — in progress. The spoken answer repeated full paths from the file search result.
- 2026-10-01 07:20 +0530 — Cursor session spoken-names — implemented. The model receives kind and name for typed results. The spoken line replaces any leftover path with that name: folder and file names, image titles such as “ship at sea”. Orchestrator, native UI, and chat UI features passed (31 scenarios).
- Files: `src/agavai/canvas.py`, `src/agavai/orchestrator.py`, `docs/ui-design.md`, `features/orchestrator.feature`, `features/steps/orchestrator_steps.py`.
- 2026-10-01 07:28 +0530 — Cursor session spoken-names — complete. Commit afef239.

- 2026-10-08T17:06+05:30 — Codex session result-canvas — in progress. User requests shorter list reading instead of whole filenames. Reuse `spoken_name`, `model_view`, and `read_aloud`: remove extensions and filename separators from spoken labels, retain exact filenames/paths on the canvas, replace echoed known filenames as well as paths, and instruct list replies to summarize rather than enumerate every item. Scope: `src/agavai/canvas.py`, the relevant line of the orchestrator system prompt, focused speech regression scenarios, existing listing assertions, and UI/runtime contracts. Preserve concurrent conversation-context changes; stage only speech-related hunks.

- 2026-10-08T17:16+05:30 — Codex session result-canvas — implementation validated, awaiting commit and approved listener restart. `Meeting_Notes-2026.md` is spoken as “Meeting Notes 2026”; exact names and paths remain on the canvas. Known paths and filenames are substituted in one pass with filename boundaries, so prefixes and labels matching other filenames are not rewritten. Changed files: `src/agavai/canvas.py`, system-prompt line in `src/agavai/orchestrator.py`, listing assertions in `features/orchestrator.feature` and `features/steps/orchestrator_steps.py`, new `features/result_speech.feature`, shared `features/steps/result_steps.py`, `docs/ui-design.md`, `docs/flow.md`, and this task. Coverage includes folders, explicit titles, uppercase extensions, Unicode, spaces, version dots, overlapping filenames, unknown paths, and punctuation. Full Behave suite passed: 176 scenarios / 755 steps; diff reviewed and whitespace clean. Concurrent conversation-context changes were preserved.

- 2026-10-08T17:17+05:30 — Codex session result-canvas — waiting for input. Source and tests committed as `2c40365`; validation recorded above. Installed launcher resolves to this repository, so reopening Agavai loads the new speech rules. Approval for live application and verification is pending with the canvas task.
