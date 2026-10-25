# Request logging

Every layer of a voice request should leave a line in one place, so a bad request can be traced after it happens.

## Surface

- [x] P1 voice Log each request through speech recognition, routing, the model, tools and speech in the user journal, tagged with one request id

Status: implemented, validated and committed on `t3/request-logging` (`bfc869e`, `b3d586a`). Waiting for input: may `t3/request-logging` be merged into `main`? It fast-forwards from `68f2fc7`. Merging means running the merge in the main checkout `/home/janar/Projects/agavai`, which has an untracked `:memory:.ses` that isn't mine. The running assistant uses `~/.local/bin/agavai` → `t3-0363bfd0` (`t3/test-whistle-needle-engines`), so this logging is not live until that branch takes it.

### Acceptance

- `journalctl --user -t agavai` shows, for each utterance:
  - session start and end, with the reason it ended;
  - recognizer readiness, with device and load time;
  - the end of each capture, with reason, duration and word count;
  - the conversation-context choice;
  - the router's backend, heads and fallback, with why it fell back;
  - each model call, with tools offered, tool calls, tokens and time;
  - each tool, with time and failure;
  - the speech engine and playback outcome;
  - the turn's time and errors, with tracebacks.
- All lines from one utterance carry the same `request=<first 8 of session id>-<n>`. Lines outside an utterance carry `request=-`.
- The default `[log] level = "info"` records no user text. `"debug"` adds what was heard, replies, and tool arguments and results, all clipped. An unknown level fails config loading.
- Errors and tracebacks from the detached listener reach the journal, not `/dev/null`.
- The Observability bullets in `docs/flow.md` describe the log. The full Behave suite passes.

### Log

- 2026-10-25T12:33:15+05:30 — Claude Code session request-logging — in progress. User request: "Build the logging as you suggest a fix to main. Can you create a new task for yourself?"
  - Workspace: branch `t3/request-logging` from `main` at `68f2fc7`, in worktree `/home/janar/.t3/worktrees/agavai/request-logging`. The untracked `:memory:.ses` in the main checkout is not mine and is left alone.
  - Findings, from an investigation on `t3/test-whistle-needle-engines` and checked against `main`:
    - Nothing configures Python logging. The root logger is at WARNING with no handler.
    - `start_session` starts the listener with stdout and stderr sent to `/dev/null`. Its tracebacks (`traceback.print_exc` in `_run_stop_body`), recognizer errors and TTS engine notes are lost.
    - Only `agavai-llm` reaches the journal: timing and token counts, with no request content.
    - No id joins the layers.
    - `docs/flow.md` already says "Router's choice is not logged" and "There is no trace of why a session exited".
    - A live session on the host at 12:08 to 12:12 recorded five "Thank you." turns. Nothing showed why, which is the motivating case.
  - Decisions:
    - Logs go to the journal through the standard-library `SysLogHandler` on `/dev/log`, so there's no new dependency. A probe from Python 3.14 here shows the lines under `journalctl --user -t <ident>`. With no socket it reports a logging error and never raises.
    - The user did not choose whether to log text. The default keeps it out, and debug level adds it.
    - Request id = first 8 characters of the session id plus a capture counter. Captures that hear nothing still use up a number.
    - User-facing CLI messages (`agavai stop` with no listener, overlay summon failure) stay on stderr. Diagnostics from the background path move to the log.
  - Out of scope here: the energy/Silero VAD and the Whistle/Needle brain tiers exist only on `t3/test-whistle-needle-engines`. They need log lines when that branch merges into `main`.
  - Planned files: `src/agavai/{journal,config,__main__,app,asr,orchestrator,router,llm,tools,tts}.py`, `share/config.example.toml`, `features/environment.py`, a new `features/request_log.feature` with steps, `features/config.feature`, `docs/flow.md`, this task.
- 2026-10-25T12:46:05+05:30 — Claude Code session request-logging — implemented and committed: `bfc869e` (code and tests) and `b3d586a` (docs).
  - `src/agavai/journal.py`:
    - `setup(level)` attaches a `SysLogHandler("/dev/log")` with ident `agavai: ` to the `agavai` logger, unless that logger already has a handler.
    - `tagged(handler)` adds the `request=%(request)s` prefix.
    - `start_request(session_id)` numbers captures, and `clip()` makes one line of at most 500 characters for debug text.
  - Where `setup` is called: `main()` calls it with `info` before loading config, logs a config that fails to load with its traceback, then calls it again with `[log] level`.
  - Lines per module:
    - `__main__`: session start and end (`ended` reason, set at each return and logged in `finally`), `asr end reason=eou|empty|enter|cancel|stream_ended words= secs=`, `listen failed`, `asr failed`, `asr did not start`, `turn failed` (replaces `traceback.print_exc`), and `session crashed`.
    - `asr`: `asr ready device= load_secs=`; worker stderr is logged instead of printed, and `_failure` keeps the same overlay text.
    - `router`: a warning naming the exception and fallback, then `router backend= source= heads= secs=`. Fallback `none` still returns no heads.
    - `llm.chat`: `llm tools= prompt_tokens= completion_tokens= calls= secs=`, read from llama-server's `usage`.
    - `orchestrator`: `run_turn` wraps `_run_turn` with `turn start`/`turn done` (text and reply at debug), plus `context choice=`, `turn control=`, and warnings for a stopped model, `LlmError` and exhausted steps.
    - `tools.call_tool`: wraps `_run_tool` with `tool name= status= secs=`, where status reuses `ui._action_failed`. Arguments and result are at debug, and a raised exception leaves its traceback.
    - `tts`: engine, Kokoro `synth_secs` and `playback=`, and failures as warnings. Local `log` path variables were renamed `log_path` so they no longer shadow the module logger.
    - `app`: `invoke summoned the overlay; started_session=`, plus an error when summon fails. The user-facing stderr line stays.
  - Config: `[log] level` (`info` or `debug`), validated in `load_config`.
  - Files: `src/agavai/{journal,__main__,app,asr,config,llm,orchestrator,router,tools,tts}.py`, `share/config.example.toml`, `features/environment.py`, `features/request_log.feature`, `features/steps/request_log_steps.py`, `features/config.feature`, `features/steps/config_steps.py`, `docs/{flow,architecture}.md`.
  - Tests: `features/environment.py` installs an in-memory handler on the `agavai` logger, so the suite never writes to the user's journal. Verified: no `agavai` journal lines appeared from suite runs. `request_log.feature` covers:
    - the journal datagram format;
    - a strict per-layer sequence for a typed request, with no text at `info`;
    - text at `debug`;
    - capture numbering and endings in a listen session;
    - recognizer readiness;
    - a recognizer that does not start;
    - a turn traceback;
    - router fallback;
    - invoke outcome;
    - a config error.
  - Validation:
    - `PYTHONPATH=src AGAVAI_CONFIG="$PWD/share/config.example.toml" <t3-0363bfd0>/.venv/bin/behave --tags=-asr_model`: 259 passed, 3 skipped.
    - Without `AGAVAI_CONFIG`, the two `asr_worker` scenarios fail on missing numpy because they read `[asr] venv` from the live host config, which belongs to the other branch. That's environment, not this change.
    - Mutations, each caught by exactly its scenario: removing the per-capture `start_request`, dropping the tool line, logging the turn text at `info`, and dropping the router failure warning. The unmutated copy passes.
    - Live check on the host, with request `e2e0test-1`, the keyword router, the real `agavai-llm` and the `clock_now` tool: four lines under `journalctl --user -t agavai`, with real token counts (`prompt_tokens=15 completion_tokens=2`).
  - Observed, not changed: before the first turn of a session completes, each capture calls `ui.listening()`, which begins a new Snapshot session id. So noise before the first request moves later requests to a new prefix. Documented in `docs/flow.md` under Request log.
  - Follow-ups:
    - When `t3/test-whistle-needle-engines` merges, its energy/Silero VAD, Whistle and Needle/brain tiers need lines in this format. That branch already has a few `log.info` calls (`ASR ready`, `ASR endpoint`, `ASR final`, `brain …`), which would start reaching the journal.
    - The detached listener's stdout and stderr still go to `/dev/null`. Its diagnostics now go to the log instead.
- 2026-10-25T13:11:04+05:30 — Claude Code session request-logging — merged into `main` (fast-forward to `dc53f52`, not pushed). Follow-up done on `t3/test-whistle-needle-engines`, rebased onto `main` (see `tasks/model-engine-design.md`):
  - `6d65526` puts the engine branch's layers in this format: `asr ready backend= mode= endpoint= vad= device= load_secs=`, `asr endpoint policy= reason=`, `asr final backend= finish_secs=`, `llm model=`, `needle model= tools= calls= secs=`, `brain unsupported model= reason= tools=` and `turn escalated from= to=: reason`.
  - It removes the branch's `brain` line for llama-server, which repeated the `llm` line.
  - Validated by the full suite there (405 passed), including a real Needle inference scenario.
- 2026-10-25T17:21:45+05:30 — Claude Code session request-logging — deployed from `main` with user approval ("push and deploy main"). `t3/test-whistle-needle-engines` was fast-forwarded into `main` (`9434473`) and pushed (`68f2fc7..9434473`). `scripts/install.sh --configured` was run from `/home/janar/Projects/agavai`, so `~/.local/bin/agavai` now points at this checkout. The previous plugin directory is backed up at `/tmp/agavai-plugin-pre-main-deploy`. Ran `omarchy restart shell`; the new shell log shows no `janar.agavai` QML warnings.
  - The live journal showed Whistle, Jev, Needle, escalation, Qwen and Kokoro lines under one request id. It never showed `session start`, `asr end` or `session end`. Cause: the launcher runs `python3 -m agavai`, so `__main__.py`'s `getLogger(__name__)` is `__main__`, outside the `agavai` logger. Fixed in `69a1cd8` with an explicit `agavai.__main__` logger name.
  - New scenario "The installed command logs its own session lines" runs the entry point with `runpy.run_module(..., run_name="__main__")` against a test socket. It failed before the fix and passes after.
  - Files: `src/agavai/__main__.py`, `features/request_log.feature`, `features/steps/request_log_steps.py`.
  - Validation: full suite with all model tags, 406 passed. The suite wrote nothing to the user journal.
  - Observed, not changed: with Jev answering `chat`, a request routes twice, once for Needle and again after escalation to Qwen, each about 0.8 to 1.3 s.
