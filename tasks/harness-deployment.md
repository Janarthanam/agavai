# Deploy the Agavai harness from main

- [~] P1 voice Deploy the validated in-process harness and UI-independent events

Status: in progress. Owner: Codex session harness-deploy. User authorized deployment. Preserve the saved Whistle/Cactus ASR, Silero VAD, Needle router/primary and Qwen fallback configuration. Deploy from local main; no remote push requested. P2 persistence remains planned.

### Acceptance

- Preserve main's independent changes and integrate the validated harness branch.
- Back up installed Agavai files/source before switching main; keep model configuration unchanged.
- Verify installed imports/version, model services, plugin and a live read-only request. Run the existing native BDD check and report any known compositor limitation accurately.
- Record deployed revision, backup, changed files, validation and local commit.

### Log

- 2026-10-26T11:26:25+05:30 — Codex session harness-deploy — started from clean `2041497`. Main was `35f2c35`; its only additional change is tracked `:memory:.ses` metadata, now merged into this branch without conflicts. Fetch found no newer origin/main. Existing installed launcher points to `/home/janar/Projects/agavai/scripts/agavai`; no active listener/recording. Read install/configuration and Omarchy plugin instructions. Scoped deployment will reuse unchanged launchers/units/plugin where identical and omit installer legacy deletions or layout/config edits. Backed up saved config, plugin, Agavai units, launcher targets and previous-main source archive under `~/.local/share/agavai/deployments/` before updating the live main checkout. Changed repository files planned: this tracker plus deployment-status sentences in README/current design docs.

- 2026-10-26T11:29:04+05:30 — Codex session harness-deploy — deployed local main `933cf25` (runtime includes `c86f80a`; integration retains `35f2c35`). Backup/rollback: `/home/janar/.local/share/agavai/deployments/20261026-112624-harness-events/`. Main checkout is already the installed launcher target, so fast-forward activates the new Python harness. Installed plugin and all four Agavai units match main byte-for-byte and were reused; plugin validation/rescan succeeded. Saved config SHA-256 matches the backup; no model/config/layout changes or installer legacy deletions. `configure.sh --ready` passed; services sync kept the existing Qwen service active with settings unchanged, secondary inactive, config watcher active.

- 2026-10-26T11:29:04+05:30 — Codex session harness-deploy — validation: installed `agavai explain/status` identifies the new harness and existing Whistle/VAD/Silero/Needle/Qwen configuration. Live installed “what time is it” completed with a typed successful screen read, Qwen interpretation and Kokoro; UI reports `0.1.0 · 933cf25`, answered task and actual Needle→Qwen execution. Model-quality limitation: Needle chose `screen_context` rather than the dedicated time tool; this deployment does not change model inference quality. Native BDD `features/pipeline_help.feature:35` passed (1 scenario / 5 steps, all four underlying compact/canvas-focus/recording/help checks). Earlier intermittent focus failures remain historical evidence, not a bug fix claim. Logs: `/tmp/agavai-harness-deploy-smoke.log`, `/tmp/agavai-harness-deploy-native.log`. Existing full runtime validation: 471 scenarios / 2353 steps passed before deployment. Reviewed diff; current changes only deployment-status docs and trackers. Implementation/deployment complete, awaiting bookkeeping commit. P2 persistence remains planned; no recording/audio data deleted.
