# Agavai voice and results interface

How a session moves from shortcut to spoken reply is specified in [`flow.md`](flow.md). This file is the interaction and presentation spec for the overlay.

Open [the interactive prototype](ui-prototype/index.html) in a browser. It uses simulated microphone levels, partial transcription, and tool results. No microphone, model, desktop tool, or external network is accessed. Video playback accepts a local file. Use Alt+M in the prototype; Super+Ctrl+M remains the native shortcut.

## Interaction

The shortcut opens an orb-only listening presence at the bottom right of the active monitor and starts microphone capture immediately. Compact mode hides all text and results and takes no keyboard focus, so the user can continue working. Click the orb to expand the transcript and results at the bottom center. Clicking another window minimizes without cancelling capture; the − button minimizes it again without stopping capture or discarding the session. Right-click the compact orb to dismiss and cancel. Incoming transcripts, answers, results, and errors never expand it automatically. The presence is a borderless orb. Its size and motion follow smoothed input amplitude. Silence settles the orb instead of playing an endless decorative animation.

In the expanded view, partial transcription occupies the primary line under the listening label, above the orb. Replace the current partial utterance as recognition revises it; append only finalized segments. Never turn each partial into a conversation turn. A pause submits the utterance; the same shortcut or Enter submits immediately. Escape cancels capture and pending work before dismissing the surface.

The surface stays open and listening until the user dismisses it, in either compact or expanded mode. Silence does not close the microphone or send noise to the model. Each finished utterance is sent with the earlier conversation, then the orb returns to listening with the results still on screen. A new invocation still starts a blank session.

A finished desktop action, such as setting the wallpaper, shows a Done line with what changed. The spoken reply says the same thing. A failed action shows Not completed with the reason. Looking something up does not use that line. The listening ring remains, with the hint that Escape dismisses.

The surface transitions from Listening → Transcribing (when final recognition is pending) → Working → Results. During tool execution, show a human-readable activity such as “Searching files”, with the tool identifier available in details. Results appear in the expanded view of the same surface instead of opening a second window. A brief spoken answer accompanies the richer screen content.

Results persist until dismissed or replaced by a new request. Escape closes the surface. Starting a new request resets selection, transcription, tool status, and previous previews. Error states keep the surface visible and offer a retry.

## Result presentation

| Result | Primary presentation | Selection preview |
| --- | --- | --- |
| File or folder | Icon, name, parent path, relevant metadata | File thumbnail, text excerpt, or folder summary |
| Markdown answer | Readable headings, paragraphs, lists, code, links | Full-width answer; no redundant list |
| HTML answer | Sanitized semantic content | Full-width content; no scripts or arbitrary embed |
| Image | Thumbnail rows with names and dimensions | Larger image, caption and source |
| Video | Named media rows with duration when known | Local player with controls; no autoplay |
| Desktop status | Compact labeled values | Relevant details |
| No matches | Plain empty state and new-request action | No blank preview pane |

Arrow keys move selection and update the preview. Enter opens the selected item through a specific allowlisted action. Merely selecting an image must not set the wallpaper. An explicit “Set wallpaper” action is separate. Showing a result does not imply its action has succeeded. Tool activity is secondary to useful content; raw JSON and arguments belong in an expandable details view.

## Omarchy and Hyprland implementation

Use the existing Quickshell plugin and `agavai-chat` layer namespace. Do not draw the listening surface with the menu or popup widgets (`BorderSurface`, `Color.menu`, `Style.font.menuFamily`). That chrome is what makes the overlay look like a native Omarchy popup. Results text, spacing, and the results sheet use `Color.background`, `Color.foreground`, and `Style.font.family`. The orb keeps its own spectrum so it stays recognizable. The card behind the words and the orb uses the Omarchy background at high opacity, with `Color.foreground` and `Style.font.family`, so the surface stays in front of the desktop and follows the theme. Respect display scale, active-monitor placement, reduced motion, and a bounded scrolling results area. Listening is only as wide as the words and the orb. Results expand the same bottom-centered surface to roughly 680 logical pixels, clamped to the available monitor width. Narrow screens stack the list above the preview.

Only the expanded native surface requests on-demand keyboard focus so Escape can cancel listening and Enter can optionally send immediately. It must not request exclusive focus, which traps pointer input in Hyprland. Losing native window focus minimizes the surface without cancelling capture. Minimizing releases keyboard focus. Compact pointer input is bounded to the 80-logical-pixel orb area, inset 28 logical pixels from the bottom and right edges; expanded pointer input is bounded to the sheet. Validate multi-monitor focus and cancellation manually in Hyprland; a browser cannot validate layer-shell behavior.

There is one native renderer: the Quickshell overlay. The desktop app entry is an invocation command for this same surface, not a separate GTK window. “Type instead” reveals an inline text field on the results sheet.

## Data and wiring

`ui.json` now carries `transcript: {text, final}`, a typed `display` block with ordered items, formatted `answer_html`, and a session identifier. `level_db` drives the mic. Cancellation marks the session and suppresses late snapshot writes; the overlay notifies the controller. Snapshot writes remain atomic. Partial transcript updates are accepted only during listening.

Typed results should include `id`, `kind`, `title`, `subtitle`, preview content/source, source tool, and explicit allowlisted actions. Markdown and HTML are distinct content types. Sanitize HTML, restrict link/media schemes, preserve local paths as data, and use an allowlisted file-open action. Do not execute tool-returned commands. The browser prototype deliberately renders a small escaped Markdown subset; it is not a production Markdown or HTML engine.

The orchestrator passes full tool results to `ChatUi.tool_done()` before building the model-facing text. Typed results (files, folders, images, videos, and the other lists) are sent to the model as kind and name, and the spoken line uses those names. A path that still appears in the reply is replaced the same way. The overlay keeps the full path for opening and preview. `canvas.display_for()` normalizes file search, wallpapers, themes, windows, status, reminders and explicit Markdown/HTML blocks. File search's JSON path list and a newline-path fallback are supported. File paths are encoded into local media URIs; text previews read at most 8 KiB per item. Preview selection is independent of opening. `agavai ui-open` validates the current session, selection and supported file type before invoking `xdg-open` with a fixed argument list; folders can open in the file manager. Executables and desktop launcher files are excluded.

Voxtype’s current start/stop file flow returns words after recording stops. True live transcription requires a streaming local recognizer or a confirmed partial-output interface; simulated words in this prototype do not supply that capability. Keep the final recognizer authoritative, and handle partial revision, cancellation, missing devices, and slow recognition explicitly. The existing microphone meter drives the native orb now.

## Delivery boundary

The single native Quickshell overlay implements this design. Super+M, the desktop launcher, and the bar icon invoke automatic listening. Super+Ctrl+M remains an alias. Invoking again during a request raises the same widget without starting or stopping capture. Existing capture and speech services remain the source of audio and transcription. The browser prototype is still an isolated simulation for design exploration.

Native results persist until dismissal or a new request; no separate pin control is needed. The expanded surface uses on-demand keyboard focus, so Escape dismisses while it is focused. Clicking another window releases that focus and minimizes the surface. Compact mode releases focus and uses right-click dismissal, or the existing bar cancel action. The default listening surface is the bottom-right orb. The expanded view retains the bottom-centered transcript and results sheet. Native motion is not yet connected to a system reduced-motion preference, and videos depend on locally available media codecs. PDF and office files can open in their associated app; previews currently show their names and paths rather than rendering pages.

Automatic listening sends when streaming ASR emits end of utterance. In the expanded view, Enter sends the current line and Escape dismisses. A missing microphone ends with a visible error. Silence that never becomes an utterance is not sent. All automatic entry points select `agavai listen`, even if the legacy manual capture option is disabled in config.

The interaction model is covered by `features/ui_design.feature` using Behave and Node.js. Run `PYTHONPATH=src .venv/bin/behave`. In a restricted environment where the current runtime directory is read-only, set `XDG_RUNTIME_DIR` to a fresh temporary directory for the suite; the existing mocked TTS scenarios write runtime logs there. Browser layout and native layer-shell behavior require visual/manual verification separately.

On an Omarchy Wayland desktop, `python3 scripts/check-compact-ui.py` loads the actual overlay in an isolated Quickshell instance and checks native mouse expansion and dismissal, minimization, keyboard-focus settings, corner geometry, snapshot preservation, and a real focus switch to a second window that receives typing while Agavai minimizes. It shows a brief preview without starting microphone capture.
