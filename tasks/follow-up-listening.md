# Follow-up listening

After a spoken choice prompt, such as screensaver images, the same session should show the images, return the orb to listening, and send the earlier conversation with the next utterance.

## Surface

- [~] P0 voice Keep results on screen, reopen listening, and send the conversation to the model

### Log

- 2026-09-30 22:40 +0530 — Cursor session follow-up listening — in progress. A request like “show me all the images of screensaver” listed nothing and only spoke “set the image you want as your screensaver”, then left the phase on speaking. The next utterance was a fresh turn with no prior messages and often no image tools.
- 2026-09-30 22:55 +0530 — Cursor session follow-up listening — implemented, not committed. Screensaver wording selects the wallpaper head even when Jev answers chat. `wallpaper_list` is titled Images. A reply that asks for a choice (`?`, “you want”, “which”, “tell me”, “let me know”) reopens the mic for up to two follow-ups without clearing the canvas. Silence leaves the results up. `run_turn(..., continue_conversation=True)` sends the prior model messages and keeps the earlier tool head, so “ship at sea” can call `wallpaper_set`. The listening orb draws a ring and settles until speech. Live plugin `~/.config/omarchy/plugins/janar.agavai/Chat.qml` was updated in place so the overlay matches; its existing focus-priming change was left in place.
- 2026-09-30 23:05 +0530 — Cursor session follow-up listening — if the model only asks which image to set, `wallpaper_list` still runs first so the gallery is on screen and in the saved conversation. Orchestrator scenarios pass.
- Files: `src/agavai/orchestrator.py`, `src/agavai/__main__.py`, `src/agavai/ui.py`, `src/agavai/router.py`, `src/agavai/heads.py`, `src/agavai/tools.py`, `src/agavai/canvas.py`, `plugin/Chat.qml`, `docs/ui-design.md`, `features/heads.feature`, `features/orchestrator.feature`, `features/native_ui.feature`, `features/invocation.feature`, and their steps.
- Validation: `PYTHONPATH=src .venv/bin/behave features/heads.feature features/orchestrator.feature features/native_ui.feature features/invocation.feature features/chat_ui.feature` — pass after the follow-up frame mock was corrected.
