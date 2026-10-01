# Speak result names, not paths

Typed results (files, folders, images, videos) should be read by the name for that type.

## Surface

- [x] P0 voice Read files and images by name

### Log

- 2026-10-01 07:10 +0530 — Cursor session spoken-names — in progress. The spoken answer repeated full paths from the file search result.
- 2026-10-01 07:20 +0530 — Cursor session spoken-names — implemented. The model receives kind and name for typed results. The spoken line replaces any leftover path with that name: folder and file names, image titles such as “ship at sea”. Orchestrator, native UI, and chat UI features passed (31 scenarios).
- Files: `src/agavai/canvas.py`, `src/agavai/orchestrator.py`, `docs/ui-design.md`, `features/orchestrator.feature`, `features/steps/orchestrator_steps.py`.
