# Agavai architecture

Agavai is an in-process voice-agent harness. It owns session control, task context,
routing decisions, model calls and tool execution. Models provide capabilities
behind adapters; the native UI projects harness state. The detailed design and
module contracts are in [voice-agent-harness.md](voice-agent-harness.md).
[flow.md](flow.md), [audio.md](audio.md), [ui-design.md](ui-design.md) and
[recording.md](recording.md) govern runtime, speech, presentation and saved sources.

## Processes and ownership

~~~mermaid
flowchart LR
    CLI[CLI / native controls] --> Session[Session controller]
    ASR[Speech worker / VAD] --> Session
    Session --> Harness[Harness / turn engine]
    Harness <--> Context[Context store]
    Harness --> Decisions[Decision layer]
    Decisions --> Heads[Tool-head selector]
    Harness <--> Brain[Needle worker / llama-server]
    Harness --> Execute[Execution manager]
    Execute --> Tools[Allowlisted desktop adapters]
    Harness --> Snapshot[Native snapshot]
    Session --> Snapshot
    Snapshot --> UI[Quickshell overlay]
    Harness --> TTS[Speech service / playback]
~~~

The harness, context store, decision layer, execution manager and snapshot writer
run in the agavai listen process, or the one-shot agavai ask process. There is no
harness daemon. ASR/Cactus workers remain isolated processes; llama-server and
Kokoro retain existing service deployment. Quickshell runs the presentation surface.
The listener PID plus its /proc start token and exclusive start lock keep one
microphone session. Closing it discards session memory; recording files survive.

| Owner | State |
|---|---|
| Session controller | Listener identity, capture, endpoint commitment, recording controls |
| Context store | Session/task/request identity, complete task messages, task archive, source revision, hold/draft, pending proposal |
| Execution manager | Ordered call records, exact arguments, actual full outcomes |
| Inference slot | One outstanding provider operation and cancellation fence |
| Native snapshot | Transcripts, canvas, task status, tool status, actual pipeline events |

ChatUi has no model-message history, inherited tools or executable pending action.
A snapshot cannot resurrect a proposal. Task reset archives the previous task,
clears its prompt/head inheritance and invalidates confirmation.

## Routing and models

Two routing levels have distinct authority:

1. The harness decision layer selects source/correction/reasoning/action paths for
   supported request forms. A language tier determines task continuity and resolves
   utterance self-corrections before action proposal. Exact local controls bypass
   models. Ambiguity and invalid decisions stop execution.
2. The existing head router selects tool schemas for an action path. Jev, Needle
   and keyword backends retain their contracts. Candidate tool names select schemas;
   arguments from a standalone head router never execute.

The primary action brain is [brain.small], or [llm]. A language-capable primary or
[brain.large] is selected directly for language questions, recording interpretation
and self-correction. Needle remains useful for supported tool proposals. It cannot
satisfy a recording summary by selecting an unrelated function.

The all-tools policy and router none expose the desktop allowlist on action paths.
Identical Needle router/agent configurations share one proposal inference. Source
interpretation and reasoning paths have no desktop authority regardless of that
policy. Structured results from a tool-only model go to the language tier for
interpretation; completed calls are not replayed. Without a suitable language tier
the harness states the limitation.

Defaults, setup and mix-and-match profiles are in [engines.md](engines.md).
The legacy [llm] selection uses agavai model list/set and the model catalog;
explicit brain roles use agavai setup or TOML. See [role selection](engines.md#small-brain-then-larger-brain).
The Voxtype sanitizer on port 18765 is separate and never used by the harness.
Jev can send committed action text to OpenRouter; choose keyword/Needle/none for
fully local operation. No OpenAI/cloud brain adapter is implemented.

## Context, sources and execution

Messages are retained for the current task and archived on task change. Before
inference, the context store omits oldest complete exchanges to fit an application
UTF-8 byte budget, including schemas. The original exchanges, full execution records,
pending action and recording files remain. This is not tokenizer-exact compaction
or persistent personal memory.

Saved recording segments are loaded directly from recording.json, honoring corrected,
then final, then live text. Source revisions are checked before publishing derived
answers. Exact edits overlay corrections without altering heard words.
[Recording behavior](recording.md) lists supported requests and limits.

Calls are validated against schemas offered for that route before dispatch.
Prepared confirmations bind exact validated arguments and session identity. The
dispatcher has no general shell or model-supplied command runner. Tool adapters return
typed ok/error/unknown outcomes; OCR text containing “error” remains data. MCP uses
the text serialization of that same adapter boundary. Unknown outcomes are not
evidence of failure or success and must not be retried blindly.

Only provider work runs in the inference thread. Controls remain responsive while
it waits; cancellation prevents its result from reaching tools, canvas or playback.
An HTTP call may continue until its deadline. The slot rejects further model work
until it completes. Desktop side effects remain ordered on the controller thread
with existing timeouts; interruption does not claim rollback.

## Code map

| Path under src/agavai | Responsibility |
|---|---|
| __main__.py | CLI parsing and command composition |
| harness/__init__.py | Harness entry point and owned context |
| harness/session.py | Capture, listener/control transport, recording lifecycle |
| harness/context.py | Task state, history/archive, prompt packing |
| harness/routing.py | Task decisions and context relation |
| harness/engine.py | Model/tool turn coordination |
| harness/sources.py, source_turn.py | Recording binding, corrections, grounded interpretation |
| harness/execution.py | Schema validation and ordered execution records |
| harness/inference.py | Single provider slot and stale-result fence |
| brain.py, speech_backends.py, worker.py | Model adapters and worker transport |
| tools.py, outcomes.py | Allowlist and typed outcomes |
| ui.py, canvas.py, plugin/ | Snapshot and native presentation |

[Component design](architecture-design/design.md) maps modules and critical flows.
[Harness BDD](../features/harness.feature), speech replays and native UI checks
validate production entry points. This branch's implementation does not imply a
host deployment.
