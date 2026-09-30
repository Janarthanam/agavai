# Siri voice surface

The listening overlay still opens as an Omarchy menu card. Listening should be a voice presence, and results should grow from that same presence.

## Surface

- [~] P0 ui Replace the top menu popup with a bottom-centered voice orb, and show results on that same surface without menu chrome

### Log

- 2026-09-30 — Auto (Cursor) — in progress. `plugin/Chat.qml` draws a `BorderSurface` near the top of the screen, using `Color.menu` and `Border.surfaceSpec("menu")`. Shell summon already loads the overlay entry (`Chat.qml`), not a bar-widget popup. The menu surface is what still looks like a native Omarchy popup. Scope: the overlay visual, result and button text that still uses the menu font, the UI design note, and the prototype so the study matches the native surface.
- 2026-09-30 — Auto (Cursor) — the live layer was mapped, but the card height collapsed so nothing drew. Top toasts come from `omarchy-notification-send`, which ran on every spoken reply. Overlay layout no longer derives its height from an anchored column, and a notification is posted only when speech fails.
