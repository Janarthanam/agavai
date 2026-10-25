# Request logging

Every layer of a voice request should leave a line in one place, so a bad request can be traced after it happens.

## Surface

- [~] P1 voice Log each request through speech recognition, routing, the model, tools and speech in the user journal, tagged with one request id

Status: in progress.

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
