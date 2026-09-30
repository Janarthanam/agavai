# Agavai voice and results interface

Open [the interactive prototype](ui-prototype/index.html) in a browser. It uses simulated microphone levels, partial transcription, and tool results. No microphone, model, desktop tool, or external network is accessed. Video playback accepts a local file. Use Alt+M in the prototype; Super+Ctrl+M remains the native shortcut.

## Interaction

The shortcut opens a compact listening presence at the bottom center of the active monitor and starts microphone capture immediately. The presence is a borderless orb. Its size and motion follow smoothed input amplitude. Silence settles the orb instead of playing an endless decorative animation.

Partial transcription occupies the primary line under the listening label, above the orb. Replace the current partial utterance as recognition revises it; append only finalized segments. Never turn each partial into a conversation turn. A pause submits the utterance; the same shortcut or Enter submits immediately. Escape cancels capture and pending work before dismissing the surface.

The surface transitions from Listening → Transcribing (when final recognition is pending) → Working → Results. During tool execution, show a human-readable activity such as “Searching files”, with the tool identifier available in details. Results expand the same surface instead of opening a second window. A brief spoken answer accompanies the richer screen content.

Results persist until dismissed or replaced by a new request. “Keep open” pins the surface against future automatic dismissal; explicit Escape still closes it. Starting a new request resets selection, transcription, tool status, and previous previews. Error states keep the surface visible and offer a retry.

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

The native surface requests keyboard focus so Escape can cancel listening and Enter can optionally send immediately. Pointer input is bounded to the orb and, when results are showing, the sheet; dismissing releases focus. Validate multi-monitor focus and cancellation manually in Hyprland; a browser cannot validate layer-shell behavior.

There is one native renderer: the Quickshell overlay. The desktop app entry is an invocation command for this same surface, not a separate GTK window. “Type instead” reveals an inline text field on the results sheet.

## Data and wiring

`ui.json` now carries `transcript: {text, final}`, a typed `display` block with ordered items, formatted `answer_html`, and a session identifier. `level_db` drives the mic. Cancellation marks the session and suppresses late snapshot writes; the overlay notifies the controller. Snapshot writes remain atomic. Partial transcript updates are accepted only during listening.

Typed results should include `id`, `kind`, `title`, `subtitle`, preview content/source, source tool, and explicit allowlisted actions. Markdown and HTML are distinct content types. Sanitize HTML, restrict link/media schemes, preserve local paths as data, and use an allowlisted file-open action. Do not execute tool-returned commands. The browser prototype deliberately renders a small escaped Markdown subset; it is not a production Markdown or HTML engine.

The orchestrator now passes full tool results to `ChatUi.tool_done()` **before** truncating model-facing text. `canvas.display_for()` normalizes file search, wallpapers, themes, windows, status, reminders and explicit Markdown/HTML blocks. File search's JSON path list and a newline-path fallback are supported. File paths are encoded into local media URIs; text previews read at most 8 KiB per item. Preview selection is independent of opening. `agavai ui-open` validates the current session, selection and supported file type before invoking `xdg-open` with a fixed argument list; folders can open in the file manager. Executables and desktop launcher files are excluded.

Voxtype’s current start/stop file flow returns words after recording stops. True live transcription requires a streaming local recognizer or a confirmed partial-output interface; simulated words in this prototype do not supply that capability. Keep the final recognizer authoritative, and handle partial revision, cancellation, missing devices, and slow recognition explicitly. The existing microphone meter drives the native orb now.

## Delivery boundary

The single native Quickshell overlay implements this design. Super+M, the desktop launcher, and the bar icon invoke automatic listening. Super+Ctrl+M remains an alias. Invoking again during a request raises the same widget without starting or stopping capture. Existing capture and speech services remain the source of audio and transcription. The browser prototype is still an isolated simulation for design exploration.

Native results persist until dismissal or a new request; no separate pin control is needed. The layer briefly requests exclusive focus and then settles to on-demand focus for arrow keys, Enter and Escape. Pointer input is bounded to the orb and the results sheet. The listening surface is the bottom-centered orb, not a menu card. Native motion is not yet connected to a system reduced-motion preference, and videos depend on locally available media codecs. PDF and office files can open in their associated app; previews currently show their names and paths rather than rendering pages.

Automatic listening sends after 900 ms of silence following speech. No speech, a missing microphone, or a stalled audio source ends with a visible retry message rather than waiting for a second shortcut. Capture readers observe cancellation while waiting for frames. All automatic entry points select `agavai listen`, even if the legacy manual capture option is disabled in config.

The interaction model is covered by `features/ui_design.feature` using Behave and Node.js. Run `PYTHONPATH=src .venv/bin/behave`. In a restricted environment where the current runtime directory is read-only, set `XDG_RUNTIME_DIR` to a fresh temporary directory for the suite; the existing mocked TTS scenarios write runtime logs there. Browser layout and native layer-shell behavior require visual/manual verification separately.
