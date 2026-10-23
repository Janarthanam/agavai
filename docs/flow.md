# Agavai voice loop

Design spec for the voice loop. Audio stages are in [audio.md](audio.md). The assistant listen path follows this spec: streaming ASR, then end of utterance, then the existing tool loop. Visual layout stays in [ui-design.md](ui-design.md). Model selection and the full config key list stay in [architecture.md](architecture.md) and [share/config.example.toml](share/config.example.toml).

This file wins on runtime behavior where those documents disagree. [README.md](../README.md) says v1 talks to no remote model. That does not match the code: head selection may call OpenRouter.

## Requirements

Agavai is a local Omarchy assistant for one person at the machine.

- One overlay. The launcher, Super+M, Super+Ctrl+M, and the bar icon open `janar.agavai`. Invoking again while a request is active raises that overlay and does not restart capture.
- Speak, and the words appear while you are still talking. The utterance is sent when streaming ASR emits end of utterance. A second shortcut press is not required. In the expanded view, Enter sends the current line immediately and Escape dismisses.
- The overlay starts as an orb in the configured corner (`[overlay] placement`, default bottom right) without keyboard focus. Clicking expands transcripts and results in that corner, and the orb stays exactly where it was; minimizing releases focus without changing capture. Both views keep a 28-logical-pixel inset from the corner's two edges. The expanded view uses on-demand focus and minimizes when another window takes focus, unless a canvas is on screen. A canvas stays up until the user minimizes it or a new request clears it; clearing it while another window has focus minimizes the view. Newly published canvas results expand automatically in that corner; retained results and ordinary snapshots preserve manual minimization.
- The overlay stays up after a turn, with results retained for the expanded view, and listens for the next utterance. A new session, after the previous process has exited, starts blank.
- Isolated finalized controls are handled locally before model health, context classification or routing. For other utterances, a context response from the local model distinguishes a follow-up from a new conversation. Follow-ups retain earlier results and messages. An unrelated query clears earlier conversation output and inherited tool heads before its answer is generated, while the same session stays active.
- The reply is one or two short spoken sentences. Richer content (files, images, lists) is on screen. An answer that is a list or steps, asked with no desktop tools in the turn, goes on the canvas as Markdown, and only its one-sentence summary is spoken. Spoken list replies summarize results on the canvas; references to individual files use readable names without extensions or filesystem paths.
- Desktop actions go through an allowlist. There is no generic shell. The model may claim a change only after a tool result says it happened.
- Interim text from streaming ASR is shown in the expanded overlay and is not a turn. The finished line, after end of utterance or Enter, is the only user text the LLM sees. Partials are replaced when the hypothesis changes. [ui-design.md](ui-design.md) already states that rule.
- F9 dictation stays on Voxtype. The assistant does not start, stop, or cancel a Voxtype recording. The two still must not use the microphone at the same time. Agavai does not enforce that lock.
- The brain is an on-device GGUF. Tool execution stays on the machine. The exception is the default router, which may send the utterance to OpenRouter Jev.

These are current tuning knobs, not separate service targets. Defaults are in [share/config.example.toml](share/config.example.toml).

| Knob | Default | What it changes |
|---|---|---|
| Streaming ASR device | CPU | GPU when the config selects GPU and an NVIDIA GPU is present |
| `[router] timeout_secs` | 2 s | Cap on the Jev call |
| `[router] max_tools` | 8 | Schemas injected into one completion |
| `[llm] max_tool_rounds` | 6 | Tool loop cap |
| `[llm] timeout_secs` | 120 s | Cap on one llama-server call |
| `[llm] max_tokens` | 512 | Cap on one completion |

No end-to-end latency target is written down. The 120 s llama timeout is the failure bound, not the hoped-for reply time.

## High-level design

```mermaid
flowchart LR
  Bar --> ListenSession
  ListenSession --> Snapshot
  Snapshot --> Overlay
  ListenSession --> StreamingAsr[Streaming ASR]
  ListenSession --> TurnTaking[Turn taking]
  ListenSession --> Orchestrator
  ListenSession --> Speech
  Orchestrator --> Router
  Orchestrator --> LlamaServer
  Orchestrator --> Tools
```

ListenSession is one process. It owns the microphone, writes Snapshot, and calls the others. Overlay and Bar only watch Snapshot and run CLI commands. Orchestrator is a function inside ListenSession, not its own process.

```mermaid
flowchart TB
  subgraph thisMachine [This computer]
    Overlay
    Bar
    ListenSession
    StreamingAsr[Streaming ASR]
    TurnTaking[Turn taking]
    Orchestrator
    LlamaServer["LlamaServer 127.0.0.1:18766"]
    Tools
    Speech["Speech Kokoro socket"]
    Snapshot
    Router
  end
  subgraph openRouter [OpenRouter]
    Jev["Decisions API"]
  end
  Orchestrator --> Router
  Router --> Jev
```

There are no containers. Voxtype’s sanitizer on port 18765 is a third llama-server and is not in the diagram. The assistant never calls it. Dictation still uses the Voxtype daemon.

### Decisions

**One overlay, not a second window.** [ui-design.md](ui-design.md) rejects a GTK window: the launcher is an invocation of the same Quickshell layer. A separate window would still work if the layer failed to appear, but it would split focus, results, and cancel across two surfaces. The choice stands only while the Omarchy shell can summon `janar.agavai`. If summon fails, ListenSession is not started.

**One process per session, not a resident agent.** ListenSession exits when the user dismisses it, capture fails, or the mic stream ends. A daemon could keep the model transcript across dismissals. It would also hold the microphone and race F9. The transcript lives in that process only. Assumption: a follow-up happens before dismiss. After exit, the next invoke is a blank session.

**Assistant GGUF, not the dictation sanitizer.** `agavai-llm` loads the configured GGUF on port 18766, in its own user-service cgroup. Port 18765 is Voxtype’s smaller cleanup model. Reusing it would couple assistant restarts to `systemctl restart voxtype`, which [architecture.md](architecture.md) calls out as a hang. Assumption: the selected GGUF emits OpenAI tool calls or Qwen `<tool_call>` JSON. Default `n_gpu_layers = 0` runs that model on CPU. That setting is independent of the streaming ASR device.

**Heads, not the full tool list.** [architecture.md](architecture.md) says the full set is about thirty schemas and about 1.7k tokens, which does not fit a 4B’s useful budget. Jev answers one typed choice (“which head?”). Keyword overlap is the offline path. A local decision model is the same `select()` contract and today runs the keyword router. Keyword-only stays on the machine and matches only the words listed on each head. Jev with `fallback = "none"` returns no tools when the key is missing or the call fails. The chosen path is Jev, then keyword. Assumption: two heads and eight schemas are enough for one utterance. A successful Jev answer of `chat` is not final: if keywords still match a head, those heads are attached anyway.

**In-process tools, not MCP inside the turn.** The voice loop calls `DISPATCH` directly so the 4B does not speak a second protocol. `agavai mcp` exposes the same functions for other clients. Putting MCP on the voice path would add a stdio hop and a second schema encoding without changing what can run. Assumption: every desktop action the model needs is already a named function.

**Streaming ASR, not a file transcript.** Transport in is one 16 kHz mono capture. [Parakeet-Realtime-EOU-120M](https://huggingface.co/nvidia/parakeet_realtime_eou_120m-v1) emits text while audio is still arriving. Interim hypotheses update user context and the overlay. They are not turns. End of utterance commits the line. End of boundary does not. The device defaults to CPU. When the config selects GPU and an NVIDIA GPU is present, the same model runs there. Detail is in [audio.md](audio.md). Voxtype’s file API stays on F9 dictation only. `ChatUi.partial` is the snapshot write for an interim line.

**Turn taking from the recognizer, not a silence timer.** The 900 ms quiet window, the 250 ms minimum, the 5 s reset, the 300 ms lead-in, the energy gate, and Silero are not on the assistant path. A second `parec` tap must not decide the turn. Enter commits the current hypothesis. Escape drops it. The LLM, including the router, does not run on a partial.

**Stay listening after every completed turn.** The session returns to the microphone with the canvas kept. `wants_followup` is not consulted. A policy that reopened the mic only for questions would drop the “still listening” behavior [ui-design.md](ui-design.md) describes. Assumption: the user dismisses with Escape when they are done. An end of utterance with no words is not a turn, so it does not continue the stored messages.

**Classify conversation context before the next answer.** When a completed utterance has stored history, the on-device model returns `follow_up` or `new_conversation` in a separate call with no tools, temperature zero, and at most 16 output tokens. It sees the new request and stored messages, including earlier tool results. A follow-up retains those messages, tool heads, and canvas; a new conversation clears them before routing and answering. This decision runs with every router backend. Neither the utterance count nor a matching tool head determines relevance. The first turn, partial speech, and empty utterances skip classification.

**Handle isolated controls before inference.** Match the whole committed utterance after trimming surrounding whitespace, ignoring case and removing terminal `.`, `!`, `?` or `…`. Never match substrings or act on interim/EOB text. `Yes!` is a control; `Yes, show me the wallpaper`, `Agavai show me the wallpaper` and `yes actually no` are ordinary model turns. ASR does not emit punctuation, so the same rule also serves typed input. EOU/Enter remain the only commit sources; no keyword timer or acoustic wake-word detector is added.

- `Agavai` clears turns, canvas, answer, completion, errors, remembered messages/heads and any pending action. It preserves the session id, returns to listening, and skips the thinking cue and spoken reply.
- `Yes` or `Continue` executes one pending action using its stored tool name and argument object through `call_tool`. The proposal is consumed before execution, including failures. Full results go to the existing snapshot/canvas, and matching action/result messages remain in model history. Speech uses the actual short tool result with readable path labels; structured, long or multi-sentence output gets a neutral pointer to on-screen details.
- `No` discards that action and says it was cancelled. It does not dismiss the listener. Unbound `Yes` asks what to confirm; unbound `No` reports that nothing is pending. These replies need no model. Unbound `Continue` uses Qwen because continuing an explanation requires generation.

**Prepare confirmation explicitly.** When confirmation is needed, Qwen calls the orchestration-only `request_confirmation(name, arguments, question)` alone. The name must be in the current advertised desktop tools and `DISPATCH`; arguments must be an object and the question nonempty. No desktop action runs at preparation. The question is published/spoken, and one `PendingAction` lives only in the current ChatUi process, bound to its session id. A prose question alone cannot create it. The normal tool dispatcher still validates the action's arguments when it executes. Direct commands continue to execute normally; this is not a new policy requiring confirmation for every action.

The confirmation schema reserves one slot within `[router] max_tools`, including on missing-head retry. With fewer than two slots, or no desktop tools selected, it is unavailable. Any other nonempty committed utterance invalidates the pending proposal before health/classification; Qwen can prepare a replacement with corrected arguments. Empty input and partials leave it intact. Fresh conversation/session, isolated `Agavai`, process exit or dismissal clear it. Cancellation is checked before and after preparation/execution; it cannot undo a tool that already ran. An incorrect ASR EOU can still split a longer sentence: whole-utterance matching cannot repair endpointing.

**Show structured answers on the canvas.** On a turn with a ChatUi and no desktop tools, Qwen is offered only the orchestration-only `show_answer(title, markdown, summary)`. A call must be alone, and all three fields must be nonblank. The Markdown becomes an `answer` canvas block, which expands the overlay, and the summary is the spoken reply. The turn ends in the same round, so no second model call runs after the canvas is published. The call and the Markdown stay in model history for follow-ups. These turns use a shorter chat system prompt without the desktop-tool lines. With those lines, Qwen3-4B put only 1 or 2 of 5 list answers on screen, and fewer still when the rule followed the short-answer rule. A missing-head retry that adds desktop tools switches back to the desktop prompt. A turn run without a ChatUi is never offered `show_answer`. Turns with desktop tools keep their whole `[router] max_tools` budget for those tools.

### How it fails

| Failure | What happens |
|---|---|
| Shell cannot summon Overlay | Invoke exits. The microphone is not opened. |
| llama-server is down | Handled controls still work locally. Other requests receive the systemctl hint; the session then listens again. |
| Confirmation is malformed, names an unavailable tool, or accompanies other calls | Snapshot shows an error; no pending action or desktop execution is created. |
| On-screen answer is missing a field or accompanies other calls | Snapshot shows an error; no canvas is published. |
| Context classification fails or returns an invalid choice | Snapshot shows an error; the earlier canvas and model history remain. No action or answer call runs for that request. |
| Jev times out, lacks a key, or HTTP fails | Keyword router, unless `[router] fallback` is `none`, in which case the turn has no tools. |
| Jev answers `chat` and keywords still match | Keyword heads are used. The remote answer is not authoritative. |
| No mic frames, or streaming ASR cannot start | Snapshot phase `error`. The session process exits. The turn is not run. |
| End of utterance with no words | The mic stays open. Nothing is spoken and the model is not called. Enter on an empty line speaks “I did not hear anything.” |
| Kokoro cannot play | eSpeak-ng, then an Omarchy notification. A notification does not end the session. |
| Tool name is unknown, arguments are bad, or the process times out | An error string goes back to the model. The loop continues. |
| Model calls an allowlisted tool whose head was not injected | That head is added and LlamaServer is called once more. The tool is not run on the first pass. One retry per turn. |
| Tool rounds are exhausted | The reply is “I ran out of tool steps before finishing.” |
| Cancel | `listen.cancel` plus SIGTERM. Playback stops. Later Snapshot writes for that session id are dropped. |

`agavai stop` and `agavai cancel` signal the published pid. Stop during listening commits the current hypothesis. Cancel drops it. During a recording both stop and save it; cancel also dismisses the overlay. With no live listener, stop exits 1 and cancel resets the snapshot and state to idle. Neither calls Voxtype.

There is no retry of a llama HTTP error beyond the one head-attach pass. There is no queue. There is no lock that refuses to start while F9 dictation holds the microphone.

## Modules

Throughput for the whole loop is one person, one ListenSession, one utterance at a time. LlamaServer is started with `--parallel 1`. No requests-per-second figure is measured.

### Overlay and Bar

[plugin/Chat.qml](../plugin/Chat.qml) and [plugin/BarWidget.qml](../plugin/BarWidget.qml).

- **Deploy.** Installed by `scripts/install.sh` into the Omarchy plugin directory and enabled with the shell. `keepLoaded` is set, so the plugin outlives a session.
- **Lifecycle.** The shell loads it for the graphical session. Overlay opens when summoned or when Snapshot says the phase is not idle, or when a result is still on screen, unless that session id was dismissed. Bar is always in the bar. Left click runs `agavai invoke`. Right click runs `agavai cancel`. Enter while listening runs `agavai stop`. Escape runs `agavai cancel`.
- **Latency.** No paint budget is written down. Assumption: a Snapshot change shows up on the next file watch, which is enough for tool rows to appear as they finish. A measured frame time would replace that assumption.
- **Throughput.** One overlay, one bar widget. It does not run a second session.
- **Configuration.** Plugin id `janar.agavai`. The runtime directory is `$XDG_RUNTIME_DIR`, or `/run/user/$UID` when that is unset. Layout tokens come from the shell style, specified in [ui-design.md](ui-design.md).
- **Observability.** The widget shows `phase` from Snapshot. There is no separate log.

### ListenSession

[src/agavai/__main__.py](../src/agavai/__main__.py), [src/agavai/app.py](../src/agavai/app.py), [src/agavai/state.py](../src/agavai/state.py), [src/agavai/feedback.py](../src/agavai/feedback.py).

- **Deploy.** `agavai invoke` and `agavai app` summon Overlay, then detach `python -m agavai listen` under a new session. The pid and the `/proc` start token are written to `listen.pid`. A second starter loses on `listen.lock` (`O_EXCL`) or on a live pid.
- **Lifecycle.** The process publishes its pid, opens transport in, and runs streaming ASR until cancel, a mic error, or the stream ending. Interim text updates user context. End of utterance, or Enter, commits the line and runs the turn, then listening resumes with the canvas kept. On the way in it unmutes the default source if muted, and mutes it again on the way out only if this session unmuted it. `state` holds one word: `idle`, `listening`, `thinking`, `speaking`, `recording`, or `error`. There is no transcribing wait. Invoke treats `listening`, `thinking`, and `speaking` as busy and does not start another process.
- **Latency.** Words are written to Snapshot as the hypothesis updates. The model card’s design latency is 80–160 ms. End of utterance, not a silence timer, submits the line. Enter force-submits the current hypothesis.
- **Throughput.** One listen process. Turns are serial. Follow-up utterances in that process keep the last 24 non-system model messages and the heads used so far, still at most two heads.
- **Configuration.** Streaming ASR device, default CPU. Runtime files live under `$XDG_RUNTIME_DIR/agavai/`: `state`, `listen.pid`, `listen.lock`, `listen.cancel`, `record.request`, `unmuted-by-us`.
- **Observability.** `agavai status` prints `state` and whether LlamaServer is up. Recognizer failures print to stderr. There is no trace of why a session exited.

### Recordings

[src/agavai/recording.py](../src/agavai/recording.py) and the recording loop in [src/agavai/__main__.py](../src/agavai/__main__.py). The product design is [recording.md](recording.md).

- **Deploy.** Inside ListenSession, which owns the microphone. `agavai record` toggles. With no live listener it summons Overlay and detaches `agavai listen --record`. With one, it appends the action to `record.request` and sends SIGUSR1; a listener still starting is not signalled, since it has no handler yet. `start_recording` sends this session the same toggle, so a voice start records right after the spoken reply.
- **Lifecycle.**
  - **Start.** A recording runs its own continuous recognizer process (`parakeet_worker.py --continuous`), started in about 1.3 s, while the assistant's stays loaded. The start chime plays to the end before capture begins.
  - **Capture.** One `parec` runs for the whole recording. Every packet goes to a growing `audio.wav`, whose header is rewritten on each write, and to the recognizer. Each committed line, mark, and pause is appended to `segments.jsonl`.
  - **Controls.** Only an isolated committed "Agavai stop", "stop recording", "pause", "resume", or "mark" acts; anything longer is a line. While paused the recognizer still hears, so "Agavai resume" works, but nothing is written or shown. Line times move onto the audio file's clock.
  - **Stop.** Stop, toggle, SIGTERM, dismissal, and a lost microphone all save. ffmpeg encodes `audio.opus`, and the WAV is deleted once ffprobe finds the same length. `recording.json` and `transcript.md` are written last, and the journal is removed. A recording with no audio leaves no folder.
  - **After.** A shortcut session then ends with the review on screen. An assistant session listens again.
  - **Recovery.** When a recording starts, folders still marked `recording` are finished from their WAV and journal and marked recovered.
- **Latency.** Live lines arrive at the recognizer's end of utterance. Stopping waits for the Opus encode, which grows with the recording's length. No measurement is in the repo.
- **Throughput.** One recording at a time, in the one listen process. Corrections are separate `agavai recording correct` processes that rewrite `recording.json`.
- **Configuration.** `[recordings] dir`, default `~/Documents/Agavai/Recordings`. Recordings are kept until the user deletes them.
- **Observability.** `state` is `recording`. Snapshot carries a `recording` block while recording, then a `recording` canvas pointing at the folder. `recording.json` records `audio_error` when compression failed and `recovered` after a crash.

### Streaming ASR

Transport in and the recognizer. The stage is specified in [audio.md](audio.md). F9 keeps Voxtype.

- **Deploy.** In the listen process. One capture of the default source, 16 kHz, mono, 16-bit. The model is Parakeet-Realtime-EOU-120M, with a dynamic cache-aware encoder and full-precision decoder installed by `scripts/download-asr.sh`. Not a separate service.
- **Lifecycle.** Each chunk updates a cache-aware hypothesis. Interim text is a partial. End of utterance clears that stream’s cache after the line is committed. End of boundary updates the partial and does not commit.
- **Latency.** The worker processes 160 ms of new features per step and waits for complete overlapping FFT windows. Model-card design latency is 80–160 ms. End-of-utterance median on the card’s test is 160 ms. No end-to-end latency has been measured here.
- **Throughput.** One stream. One hypothesis at a time.
- **Configuration.** Device defaults to CPU. GPU is used when the config selects GPU and an NVIDIA GPU is present.
- **Observability.** The partial is the snapshot transcript with `final` false. A startup failure is the error phase. The chosen device is not yet written anywhere else.

### Turn taking

The commit rule. It reads streaming ASR and keyboard input. It does not read a silence timer.

- **Deploy.** Inside ListenSession.
- **Lifecycle.** Interim hypothesis goes to user context and is shown. End of utterance or Enter commits that text as the user message and starts the LLM. Escape drops the hypothesis. End of boundary does not commit.
- **Latency.** The commit happens on the end-of-utterance marker, or on Enter. No 900 ms settle time.
- **Throughput.** One open utterance.
- **Configuration.** None beyond the recognizer.
- **Observability.** A committed line is the snapshot transcript with `final` true, then phase `thinking`.

### Voxtype

Not on the assistant path. The user service `voxtype` remains for F9 dictation. The assistant must not call `record start`, `stop`, or `cancel`.

### Orchestrator

[src/agavai/orchestrator.py](../src/agavai/orchestrator.py) and [src/agavai/canvas.py](../src/agavai/canvas.py).

- **Deploy.** In-process. `run_turn` on ListenSession, and also on the one-shot `agavai ask` process.
- **Lifecycle.** Input is the utterance string plus stored messages and heads when the caller permits continuation. Output is the spoken sentence. It health-checks LlamaServer and, if there is history, classifies the new query's context locally. A `new_conversation` response clears the prior canvas, turns, model messages, and heads while preserving `session_id`; `follow_up` retains them. It then asks Router for heads, merges any retained heads (at most two), and loops at most `max_tool_rounds`. A wallpaper or screensaver “show me” request runs `wallpaper_list` before the model speaks when that tool is in the selected schemas. Tool results pass through Snapshot in full. The model sees kind and spoken name, clipped to 500 characters, with paths removed. `<think>` blocks are stripped. Paths that leak into the final sentence are replaced the same way.
- **Latency.** Bound by `max_tool_rounds` times `[llm] timeout_secs`, plus tool time and one context call when there is history. That call uses the same timeout and a 16-token output cap. This is a ceiling, not a target. No typical-turn measurement is in the repo.
- **Throughput.** One turn at a time inside the process. `agavai ask` does not share memory with ListenSession.
- **Configuration.** `[llm] max_tool_rounds`, `max_tokens`, `temperature`, `timeout_secs`. The desktop and chat system prompts are fixed in code, including the local time line.
- **Observability.** Tool start and tool done land on Snapshot. Router’s choice is not logged. A Python traceback is printed when the turn raises; the user hears “The local agent hit an error.”

### Router

[src/agavai/router.py](../src/agavai/router.py) and [src/agavai/heads.py](../src/agavai/heads.py).

- **Deploy.** In-process. Jev is an HTTPS call. Keyword and local do not leave the machine.
- **Lifecycle.** `select(utterance)` returns up to two head ids, or none for chat. Jev posts one `choice` question to the Decisions API. `chat` or an empty choice means no heads from Jev. Keyword scores head keywords and keeps those tied for the top score, at most two. `local` calls keyword. After any successful empty result, keyword still runs when fallback is not `none`.
- **Latency.** [architecture.md](architecture.md) describes Jev as about 70–500 ms and not a measurement in this repo. The enforced cap is `[router] timeout_secs` (2 s). Keyword is local string matching; no budget is set. The 2 s cap is what keeps a dead OpenRouter from holding the turn longer than that before fallback.
- **Throughput.** One decision per turn. No batching.
- **Configuration.** `[router] backend` (`jev`, `keyword`, `local`), `fallback`, `timeout_secs`, `max_tools`. `[router.jev]` base URL, model `typesafe/jev-1.13`, and `api_key_env`. The key is `OPENROUTER_API_KEY` or `~/.config/agavai/secrets.toml` under `openrouter.api_key`. It is not committed.
- **Observability.** None. A failure is indistinguishable from a keyword route unless stderr happens to show a Python error. The chosen head ids are not written to Snapshot.

Heads:

| Head | Tools |
|---|---|
| wallpaper | `wallpaper_current`, `wallpaper_list`, `wallpaper_set`, `wallpaper_next`, `wallpaper_picker` |
| appearance | `list_themes`, `set_theme`, `toggle_nightlight` |
| audio | `set_volume`, `mute_microphone`, `bluetooth` |
| windows | `list_windows`, `focus_window`, `close_window`, `to_workspace`, `workspace_step`, `toggle_fullscreen` |
| system | `lock_screen`, `stay_awake`, `dnd`, `battery_status`, `network_status`, `set_brightness` |
| launch | `launch`, `open_app`, `play_url` |
| files | `search_files` |
| capture | `screenshot`, `screen_context` |
| reminders | `reminder`, `list_reminders`, `clear_reminders`, `send_notification`, `clock_now` |

### LlamaServer

[src/agavai/llm.py](../src/agavai/llm.py) and [scripts/agavai-llm](../scripts/agavai-llm). Unit: [systemd/agavai-llm.service](../systemd/agavai-llm.service).

- **Deploy.** User service `agavai-llm` under `graphical-session.target`, own cgroup, `Restart=on-failure` after 3 s. The script runs `agavai dump-llm` and execs `llama-server`. Model id resolution is in [architecture.md](architecture.md).
- **Lifecycle.** HTTP on `127.0.0.1:18766`. Health is `GET /health`, then `GET /v1/models`. A turn is `POST /v1/chat/completions` with `tool_choice: auto` when any schema was selected. Tool calls are the OpenAI array, or Qwen `<tool_call>` JSON if the template leaks. The server is not given a tool backend of its own.
- **Latency.** Client timeout is `[llm] timeout_secs` (120 s) per call. No tokens-per-second figure is recorded. `max_tokens` 512 limits one completion. Default `n_gpu_layers = 0` runs this model on CPU. A slower GGUF changes the wait, not the timeout, until the config changes.
- **Throughput.** `--parallel 1`. One completion at a time for the whole machine, shared by nothing else in this design.
- **Configuration.** `[llm]` host, port, alias, temperature, max tokens, timeout, and the model catalog. `AGAVAI_MODEL`, `AGAVAI_LLAMA_SERVER`, and `AGAVAI_CONFIG` override path, binary, and file for one process.
- **Observability.** `agavai status` prints up or down, the base URL, and the resolved model path. HTTP errors become `LlmError` text on Snapshot. The unit journal is the server log. There are no metrics.

### Tools

[src/agavai/tools.py](../src/agavai/tools.py).

- **Deploy.** In-process functions. Each one shells out to an existing Omarchy or Hyprland command, or to `fd`. Not separately installed.
- **Lifecycle.** `call_tool(name, arguments)` returns a string. Unknown names, invalid JSON, timeouts, and exceptions return an error string. They do not raise. `launch` is an enum. `play_url` allows only `http` and `https`. `search_files` runs `fd` under `[files] roots`. `screen_context` is the focused window plus `grim` and `tesseract` on that window. Pixel click is not a function. `list_agents` is on the allowlist and is not a member of any head, so the voice loop does not inject it. It reports local units, plugins, and the A2A card. It does not call a remote agent.
- **Latency.** The default subprocess timeout is 15 s. `launch` and `play_url` use 20 s. That bound is the tool’s contribution to a turn. No per-tool target is set.
- **Throughput.** Tools in one model step run one after another. They are not parallel.
- **Configuration.** `[files] roots` and `max_results` (default 20). Everything else is the command on `PATH`.
- **Observability.** Snapshot stores a clipped argument string and a clipped result, with status `running`, `ok`, or `error`. Lookup tools do not set the Done line: `wallpaper_list`, `wallpaper_current`, `list_themes`, `list_windows`, `search_files`, `list_reminders`, `battery_status`, `network_status`, `screen_context`, `list_agents`, `clock_now`. Neither do `start_recording` and `list_recordings`, where the recording itself is the feedback. `agavai mcp` neither lists nor runs those two, so other agents cannot start the microphone or read recordings. Other tools set Done or Not completed. Failure is a result that contains `unknown`, `invalid`, `need`, `failed`, `timed out`, or `error`.

### Speech

[src/agavai/tts.py](../src/agavai/tts.py).

- **Deploy.** A Kokoro process started by ListenSession on the first listen or think cue, if the socket is down. Weights come from `scripts/download-tts.sh`. eSpeak-ng is a system package. The notification sender is Omarchy’s.
- **Lifecycle.** Start cue: once the streaming recognizer is ready, the session plays one short rising chime (`start-chime.wav` in the runtime directory) as the orb appears. It plays once per listen process; a recognizer that cannot start shows its error without it. Record cues: three rising notes before a recording, which finish before capture starts, and two falling notes after it. Listen cue: warm the socket silently on every microphone reopen. Think cue: `ack-on-it.wav` if Kokoro has written it, otherwise two tones. Final speech tries `[tts] prefer`, then Kokoro, then eSpeak, then a notification. Kokoro playback in ListenSession is polled; cancel kills the process group. eSpeak plays to completion inside the engine call. `agavai ask` uses a blocking speak and does not poll cancel during playback.
- **Latency.** No time-to-first-audio measurement. Assumption: warming at the start of listening hides model load, so the reply plays when the sentence is ready. A cold socket on a short turn would break that. Only the start of a session is audible. Reopening the microphone between turns, including after an empty end of utterance, is silent.
- **Throughput.** One playback at a time. A new session starts another server only if the socket does not answer.
- **Configuration.** `[tts] prefer`, `voice` (`af_bella`), `model_path`, `voices_path`, `venv`.
- **Observability.** Stderr prints the engine name, or that playback fell through to a notification. The server appends to `kokoro-serve.log` in the runtime directory.

### Snapshot

[src/agavai/ui.py](../src/agavai/ui.py).

- **Deploy.** A JSON file, `$XDG_RUNTIME_DIR/agavai/ui.json`, written by ListenSession or by `agavai ask`. Overlay and Bar only read it.
- **Lifecycle.** Writes are a temp file and `replace`. `begin_session` clears turns, transcript, display, and the in-memory model messages, and sets a new `session_id`. `clear_conversation` clears conversation content and model heads while keeping that session id, so dismissal still suppresses late writes during a topic change. `continue_listening` clears the live transcript line and the error, and leaves the canvas. After `agavai cancel` stores the session id in `dismissed-session`, further writes from that id are skipped. `ui-open` checks the session id, `openable`, an absolute path, and the extension allowlist, then runs `xdg-open` with a fixed argument list.
- **Latency.** The file is the UI protocol. Assumption: readers see a replace as one snapshot, not a torn write. Interim hypotheses are the hottest writer. A slow reader falls behind the file watch; nothing queues intermediate frames.
- **Throughput.** One writer process in the voice path. `agavai ask` is another writer and will replace the file. It is not coordinated with ListenSession.
- **Configuration.** `[overlay] placement` is copied into every snapshot; an unknown corner fails config loading. Otherwise only the runtime directory. Turn history kept on the overlay is five. Result text is clipped (280 characters on the tool row, 160 on arguments).
- **Observability.** The file is the log: `phase`, `phase_label`, `ts` when the phase changes, `transcript`, `turns`, `display`, `answer_html`, `completion`, `error`, `level_db`, `session_id`, `model_id`, `placement`, and `recording` while one runs (path, elapsed time, paused, the last 30 lines and marks, the partial line, and whether the live transcript still runs). `state` can disagree with `phase`. The overlay shows `phase`.

## Low-level design

### Spoken file search

The user says “find the budget notes.” Words show up as they are recognized. End of utterance sends the line. This is the first utterance of a new session.

```mermaid
sequenceDiagram
  actor User
  participant Bar
  participant ListenSession
  participant Snapshot
  participant Overlay
  participant StreamingAsr as Streaming ASR
  participant TurnTaking as Turn taking
  participant Orchestrator
  participant Router
  participant LlamaServer
  participant Tools
  participant Speech

  User->>Bar: left click
  Bar->>ListenSession: agavai invoke
  ListenSession->>Overlay: summon
  ListenSession->>Snapshot: phase listening, new session id
  Snapshot->>Overlay: file watch
  ListenSession->>Speech: listen chime, warm socket
  ListenSession->>StreamingAsr: transport in, 16 kHz mono
  StreamingAsr-->>TurnTaking: interim hypothesis
  TurnTaking->>Snapshot: partial, final false
  Snapshot->>Overlay: live line
  StreamingAsr-->>TurnTaking: end of utterance
  TurnTaking->>Snapshot: final transcript, phase thinking
  TurnTaking->>Orchestrator: finished line, no prior messages
  Orchestrator->>Router: utterance
  Router-->>Orchestrator: files
  Orchestrator->>LlamaServer: messages plus search_files schema
  LlamaServer-->>Orchestrator: tool call search_files
  Orchestrator->>Snapshot: tool start
  Orchestrator->>Tools: search_files query
  Tools-->>Orchestrator: path list
  Orchestrator->>Snapshot: display with paths, model view without paths
  Orchestrator->>LlamaServer: tool result
  LlamaServer-->>Orchestrator: spoken sentence
  Orchestrator->>Speech: sentence
  Speech-->>User: audio
  ListenSession->>Snapshot: phase listening, display kept
```

What crosses each boundary:

1. Bar receives a left click and leaves with the command `agavai invoke`. No transcript yet.
2. ListenSession receives that command. It leaves a summoned Overlay and a detached listen process. If Overlay cannot be summoned, it leaves a stderr line and does not start capture.
3. Snapshot receives `begin_session`: empty turns, a new `session_id`, phase `listening`. Overlay receives that file and shows the orb.
4. Speech receives the start chime once, then the listen cue, which warms the Kokoro socket silently if one was not already up.
5. Streaming ASR receives microphone audio. It leaves interim hypotheses while the person is still talking. Turn taking writes each one to user context with `final` false. The router is not called.
6. End of utterance leaves the finished line. An end-of-boundary marker leaves another partial and does not commit. Enter commits whatever the hypothesis is now.
7. Orchestrator receives the finished text and an empty history. It leaves a health check. If LlamaServer is down, it leaves the hint sentence and does not call Router.
8. Router receives the utterance. It leaves the head id `files` (one schema, `search_files`), either from Jev or from the keyword fallback.
9. LlamaServer receives the system prompt, the user text, and that schema. It leaves a `search_files` tool call.
10. Tools receives the query. It leaves a JSON list of paths under the configured roots, or an error string such as `fd not installed`.
11. Snapshot receives the full list and stores a `display` block whose items have paths. Orchestrator sends LlamaServer only kind and name, clipped to 500 characters.
12. LlamaServer receives that tool message and leaves a short sentence. Speech receives the sentence after path substitution and leaves audio. Snapshot receives phase `speaking`, then phase `listening` with `display` still set.

The stored model messages and the head `files` stay in the process. A second utterance is sent with `continue_conversation`, which permits the local context decision. For `follow_up`, Orchestrator merges the new router choice with `files`, still at most two heads, and retains `display`. For `new_conversation`, it clears earlier turns and results, discards the stored model messages and head `files`, and answers using only the new request and its selected heads.

`agavai ask "find the budget notes"` does not open transport in or streaming ASR. It starts a blank Snapshot, plays the think cue, runs Orchestrator once, speaks, and sets phase `idle`. It does not keep messages for a later voice turn. If ListenSession is also running, both write Snapshot; they are not coordinated.

### Dismiss during speaking

The reply has started playing. The user presses Escape.

```mermaid
sequenceDiagram
  actor User
  participant Overlay
  participant Snapshot
  participant ListenSession
  participant Speech

  User->>Overlay: Escape
  Overlay->>Snapshot: cancel writes dismissed-session
  Overlay->>ListenSession: SIGTERM after listen.cancel exists
  ListenSession->>Speech: kill playback
  Speech-->>ListenSession: stopped
  ListenSession--xSnapshot: write dropped for this session id
  Overlay->>Overlay: hide
```

What crosses each boundary:

1. Overlay receives Escape. It leaves `dismissedSession` set locally and the command `agavai cancel` when phase is `listening`, `thinking`, or `speaking`.
2. The cancel command receives the live pid from `listen.pid`. It writes the current `session_id` into `dismissed-session`, creates `listen.cancel`, then sends SIGTERM. The file exists before the signal.
3. ListenSession’s handler sees SIGTERM and sees the cancel file. During streaming ASR that pair drops the hypothesis and does not commit. During Speech it means kill the `pw-play` or `paplay` process group. Speech leaves no further audio. The process exits.
4. Snapshot’s next write from that session sees `dismissed-session` and leaves the file unchanged, so a late tool row cannot reopen the layer.
5. Overlay hides the layer. `agavai stop` is the same SIGTERM without `listen.cancel`. During listening that commits the current hypothesis. During speech it does not abort playback, because abort requires both the signal and the cancel file.

## Conclusion & References

The loop is a single-flight session: one process, an allowlist, a snapshot file the UI watches, and a fallback chain for routing and for speech. The session lock is `listen.lock` plus a pid token. Those are the patterns the code actually uses.

Rejected options named by the sources below, and why this design did not take them:

| Option | Where it is named | Why it is not the voice path |
|---|---|---|
| GTK window | Rejected in [ui-design.md](ui-design.md) | Second surface. The launcher summons the overlay instead. |
| One speech-and-tools model | Earlier decision record, `docs/v2.md` in git history | Does not fit the 8 GB RX 590. Qwen3-Omni-30B-A3B needs about 79 GB at BF16 and about 19 GB at a third-party Q4 estimate. Qwen2.5-Omni GGUF has no audio output in upstream llama.cpp and no tool contract this loop uses. Ultravox, Moshi, GLM-4-Voice, and Mini-Omni still need an end-of-speech detector or do not call tools. The voice path stays a cascade: streaming ASR, the Qwen tool loop, Kokoro. |
| Sanitizer model on port 18765 | [architecture.md](architecture.md) | Different job and a different cgroup. Reusing it hangs a Voxtype restart. |
| All tool schemas on the 4B | [architecture.md](architecture.md) | Too many tokens for the useful budget. Heads cut that to at most eight. |
| MCP inside the turn | [architecture.md](architecture.md), [src/agavai/mcp_server.py](../src/agavai/mcp_server.py) | Same allowlist, extra hop. MCP remains a side door. |
| Streaming recognizer | [audio.md](audio.md) | Chosen. Parakeet-Realtime-EOU-120M. Partials are not turns. |
| Silence-timer endpointer | [audio.md](audio.md) | Removed. It guessed the end of a sentence. |
| Voxtype file transcript | [audio.md](audio.md) | Removed from the assistant. Stays on F9 dictation. |
| eSpeak or a notification as the voice | [src/agavai/tts.py](../src/agavai/tts.py) | Fallbacks when Kokoro cannot play. Kokoro is preferred. |
| Keyword-only routing | [src/agavai/router.py](../src/agavai/router.py) | Available as `backend = "keyword"` and as the fallback. Default is Jev. |

Sources: [README.md](../README.md), [docs/ui-design.md](ui-design.md), [docs/architecture.md](architecture.md), [docs/audio.md](audio.md), [share/config.example.toml](../share/config.example.toml), [plugin/Chat.qml](../plugin/Chat.qml), [plugin/BarWidget.qml](../plugin/BarWidget.qml), [src/agavai/__main__.py](../src/agavai/__main__.py), [src/agavai/orchestrator.py](../src/agavai/orchestrator.py), [src/agavai/router.py](../src/agavai/router.py), [src/agavai/heads.py](../src/agavai/heads.py), [src/agavai/llm.py](../src/agavai/llm.py), [src/agavai/tools.py](../src/agavai/tools.py), [src/agavai/tts.py](../src/agavai/tts.py), [src/agavai/ui.py](../src/agavai/ui.py), [scripts/agavai-llm](../scripts/agavai-llm).
