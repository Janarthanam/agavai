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
