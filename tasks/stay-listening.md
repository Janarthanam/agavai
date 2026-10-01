# Stay listening until dismiss

The overlay should remain open and listening until the user dismisses it. A finished desktop action needs an obvious Done state.

## Surface

- [~] P0 voice Keep the microphone open until dismiss, and show when an action finished

### Log

- 2026-10-01 06:40 +0530 — Cursor session stay-listening — in progress. After a completed action the listen loop went idle, and silence ended the session. Completion was only the spoken sentence.
- 2026-10-01 06:50 +0530 — Cursor session stay-listening — implemented, not committed. Silence and a finished turn both return to listening; dismiss still stops the session. Action tools write `completion` (`Done` or `Not completed`) and the overlay shows that line in the accent color while the listening ring stays up. Lookups such as `wallpaper_list` do not set it. Live plugin `~/.config/omarchy/plugins/janar.agavai/Chat.qml` updated in place.
- Files: `src/agavai/__main__.py`, `src/agavai/ui.py`, `src/agavai/orchestrator.py`, `plugin/Chat.qml`, `docs/ui-design.md`, `features/invocation.feature`, `features/chat_ui.feature`, and their steps.
