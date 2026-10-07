# Siri voice surface

The listening overlay still opens as an Omarchy menu card. Listening should be a voice presence, and results should grow from that same presence.

## Surface

- [~] P0 ui Replace the top menu popup with a bottom-centered voice orb, and show results on that same surface without menu chrome
- [~] P0 ui Keep listening in an orb-only corner mode without taking desktop focus

### Log

- 2026-09-30 — Auto (Cursor) — in progress. `plugin/Chat.qml` draws a `BorderSurface` near the top of the screen, using `Color.menu` and `Border.surfaceSpec("menu")`. Shell summon already loads the overlay entry (`Chat.qml`), not a bar-widget popup. The menu surface is what still looks like a native Omarchy popup. Scope: the overlay visual, result and button text that still uses the menu font, the UI design note, and the prototype so the study matches the native surface.
- 2026-09-30 — Auto (Cursor) — the live layer was mapped, but the card height collapsed so nothing drew. Top toasts come from `omarchy-notification-send`, which ran on every spoken reply. Overlay layout no longer derives its height from an anchored column, and a notification is posted only when speech fails.
- 2026-10-07 — Codex session compact-listening — in progress. User requests a minimized corner orb so other applications remain usable during listening. Current `Chat.qml` requests exclusive keyboard focus whenever open. Default new sessions to an orb-only bottom-right mode; click expands the existing full view, Minimize returns to the corner, right-click dismisses. Compact mode keeps capture and results alive, hides text, accepts pointer input only over the orb, and never takes keyboard focus or expands for incoming results. Scope: overlay, shared orb renderer, UI spec, focused native UI checks, and live plugin deployment after approval for changes outside the repo. Existing unrelated working-tree changes are excluded.
- 2026-10-07T19:17+05:30 — Codex session compact-listening — implementation validated, awaiting commit and approved live installation. Changed files: `plugin/Chat.qml`, new `plugin/VoiceOrb.qml`, `scripts/install.sh`, `README.md`, `docs/ui-design.md`, `docs/flow.md`, new `features/support/compact-ui.qml`, new `scripts/check-compact-ui.py`, and this task. Shared the existing orb painter between views; only expanded mode requests keyboard focus. Native regression checks actual mouse clicks, bottom-right 80px geometry, minimization, retained snapshots, replies/errors staying compact, dismissal and new sessions. The regression exposed anchor switching stretching the input area after minimize; explicit horizontal positioning fixes it. Validation: native Quickshell check passed; 128 Behave scenarios / 477 steps passed; orb qmllint, plugin validation, installer syntax and diff whitespace passed. No capture/ASR behavior changed. Live `Chat.qml` still matches the pre-change repository version; unrelated working-tree changes are excluded.
