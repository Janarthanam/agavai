# Agavai as a voice-native agent harness

## Requirements

Agavai is the in-process harness. ASR, VAD, decision models, reasoning models and
speech synthesis are replaceable services behind explicit adapters. This is an
architectural rewrite of the existing application, not a separate framework or
another daemon. The native UI is a projection of harness state.

This document describes the implemented rewrite; [flow.md](flow.md) governs
runtime behavior. The separately authorized local deployment from main is recorded
in [harness-deployment.md](../tasks/harness-deployment.md) and preserves the saved
model configuration. Existing recording, confirmation and allowlist guarantees
are retained by the implementation.

The initial harness must own:

1. **Voice commitment.** Revisable ASR hypotheses, explicit endpoint policies,
   pause/resume and cancellation. A partial or a silence event is never an action.
2. **Context.** Session identity, task boundaries, relevant history, active
   resources, transcript revisions, pending actions and bounded model inputs.
3. **Decisions.** Continue or start a task, resolve an explicit correction,
   select an action or reasoning path, request missing context, and narrow tools.
4. **Execution.** Validate calls, bind confirmations to their exact arguments,
   track completed calls, preserve actual outcomes across model escalation, and
   separate tool completion from fulfillment of the user's request.
5. **Output boundary.** Publish ordered, serializable decisions, sources and
   outcomes through a UI-independent event sink, then produce an appropriate
   spoken response. The native snapshot is one consumer.
6. **Architectural parity.** CLI, live voice, recordings, typed requests, evals,
   BDD fixtures and current specifications use the same harness contracts.

One local user and one active microphone session remain the supported workload.
Persistent personal memory, inferred preferences, remote agents and a general
plugin platform are outside this first implementation. Recording files remain
durable; conversation context remains session-scoped unless explicitly stated.

### Evidence motivating the change

On 2026-10-25, a saved-recording summary request selected `screen_context` through
Needle. The tool-only branch replaced its structured result with “The tools
returned results. See the details on screen.” and ended without Qwen. The saved
recording existed, but its transcript had not been attached to model context.
The same test session showed recording shortcut requests waiting behind an
approximately 55-second CPU Qwen call. These are separate failures in task
selection, source binding, completion policy and scheduling.

The [native comparison](../evals/results/20261025-brain-comparison-cached/README.md)
also found accepted wrong calls for self-corrections and general questions.
Schema validity and a no-match fallback cannot establish semantic correctness.
No component in this design may treat a model's claimed confidence as proof.

## High-level design

### Ownership and component boundaries

The decision layer is central, but it proposes a route; the harness owns state
transitions and execution authority. Acoustic timing, exact local controls,
permission checks and cancellation do not depend on a model agreeing with them.

```mermaid
flowchart TD
    Input[CLI and native controls] --> Session[Session controller]
    Audio[Microphone transport] --> Voice[Speech services: ASR and VAD]
    Voice -->|partial, endpoint, final| Session
    Session -->|committed request| Engine[Turn engine]
    Engine <--> Context[Context store]
    Engine <--> Routing[Decision router]
    Routing <--> Models[Decision and reasoning services]
    Engine <--> Models
    Engine --> Execution[Execution manager]
    Execution --> Tools[Allowlisted tool adapters]
    Tools -->|typed outcome and source| Execution
    Execution --> Context
    Engine --> Events[Harness output events]
    Session --> Events
    Events --> View[Native snapshot and canvas]
    Events --> Collector[Headless collector]
    Engine --> Speech[Speech output service]
```

All controller, context, decision and execution components above run in the
Agavai Python process. Model services can remain local HTTP servers or existing
isolated workers. “Service” describes their contract, not a requirement to run
each component as a network daemon. Quickshell remains a separate presentation
process; it never stores the authoritative model history or pending action.

### Decisions and alternatives

| Approach | Benefit | Cost / failure | Decision |
|---|---|---|---|
| Extend the existing head router only | Small diff; retains fast tool selection | Cannot represent correction, source selection, topic change or fulfillment | Keep as a tool-schema selector inside the harness |
| Give one model every control and tool | Few application rules | Wrong accepted calls, expensive history, model-dependent cancellation | Do not use as the control plane |
| Make a remote harness daemon or separate framework | Independent deployment | Adds state ownership and IPC to a single-user application | Agavai remains the in-process harness, per user direction |
| Deterministic controller with a semantic decision layer | Explicit lifecycle; replaceable models; testable decisions | More explicit contracts and task-state handling | Chosen |

The decision layer chooses task relation, source binding and capability.
The implemented routing module recognizes supported English source/correction/question
forms; the language tier classifies task relation and resolves self-corrections.
This is explicit policy with model decisions, not a claim that keyword rules
understand arbitrary intent. Ambiguous edits and invalid decisions stop for
clarification. The existing router module still only selects tool heads. An action model
then proposes concrete calls within that route. The execution manager validates
them. A general language model interprets results when the task needs an answer,
summary or explanation. A simple verified action can finish with a deterministic
acknowledgement; it need not invoke another model just to say “opened.”

Needle's supported role is tool-call proposal. A provider that cannot produce
semantic decisions must not be labelled a general context router merely because
it emits a valid function name. The configured chat-capable model handles
decisions that require language reasoning; its latency is visible. The harness
does not silently add a cloud dependency or promise that current CPU Qwen can
meet interactive routing targets.

### Three different contexts

| Context | Contains | Owner / lifetime |
|---|---|---|
| Session | Session ID, capture mode, current task, cancellation | Session controller; one listener |
| Task | Committed requests, relevant results, active recording, corrections | Context store; retained within the session |
| Execution | Current request, model attempt, advertised schemas, pending confirmation, completed calls and outcomes | Execution manager; one turn, with explicit pending-action continuation |

A new task archives the previous task and drops inherited tools and unrelated
conversation from the next prompt. It does not delete recordings or pretend earlier actions never ran.
Continuing a task keeps its relevant sources. A correction changes a source or
pending request revision; it never rewrites the historical result of an action.

### UI-independent event interface

The public interface has no concrete UI parameter:

```python
events = []
harness = Harness(cfg, on_event=events.append, should_cancel=cancelled.is_set)
try:
    result = harness.run_turn("list the planets")
    if result.speech_text:
        speak(result.speech_text, cfg)
finally:
    harness.close()
serialized = [event.to_dict() for event in events]
```

`on_event` receives one `HarnessEvent` synchronously on the controller thread.
The constructor emits `session_started`, or `session_resumed` for an explicit
`session_id`. `close()` drains audio, checkpoints and emits `session_closed`.
Each event has `schema_version=1`, a
session-local increasing `sequence`, UTC ISO `timestamp`, `session_id`, `task_id`,
`request_id`, a typed `kind` and a detached `data` dictionary. `to_dict()` produces
JSON-serializable data. Consumers cannot mutate action arguments or context through
the payload; consumer exceptions reach the caller as `EventDeliveryError` with
the original cause, so source/model handlers cannot misclassify them. There is one sink,
no background event bus or consumer retry protocol. Default persistence records
canonical events transactionally before the sink, independently of its presence.
Storage failures stop dispatch. Slow consumers delay the controller, so callbacks
must stay short.

`request_committed` records raw input once, before task classification. Its task
ID is the task at admission. `task_started` explicitly reports each subsequent
change, with the new envelope task ID and `previous_task_id` in its payload.
Later action/result events carry the task selected for that request. Request IDs
remain stable across classification and fallback. Capture events before the first
request have an empty request ID; subsequent capture events reflect the current
context and do not themselves commit another turn.

| Event kinds | Payload contract |
|---|---|
| `session_started`, `session_resumed`, `session_closed`, `request_committed`, `task_started` | Session lifecycle, raw `text`, or previous task identity |
| `task_status` | Final `status` and detached serialized `result`, identical to the returned TurnResult |
| `turn_input`, `conversation_cleared`, `listening`, `partial`, `transcribing`, `level` | Effective input and context retention, capture state, provisional text, dB/VAD metadata |
| `decision`, `model_requested`, `stage` | Capability/reason/source, actual model/backend/path/purpose, or stage/detail |
| `confirmation_requested` | Validated action `name`, exact `arguments` object and `question`; no action has executed |
| `tool_started`, `tool_completed` | `name` and `call_id`; exact argument JSON on start, full `result` and typed `status` on completion |
| `answer`, `reply`, `source_changed`, `display` | Title/raw Markdown, spoken text, source revision/staleness, or normalized content |
| `recording`, `recording_ended`, `speech`, `idle`, `error` | Recording metadata, lifecycle, actual speech engine or error message; no raw audio |

The event sink enables structured answers and confirmations even in a headless
caller. Without a sink, those interactive tool schemas are not offered.
`should_cancel` is a separate input callback; an event consumer's return value has
no execution authority. Cancellation fences late model output. If cancellation
arrives during a dispatched side effect, its actual `tool_completed` event is
still emitted before `task_status=cancelled`; further actions and reply are
suppressed. Cancellation cannot undo that side effect.

`ChatUi.on_harness_event` adapts these events to the existing native snapshot
methods and renders Markdown there. Harness producers never read the snapshot
or import `agavai.ui`. Shared pure-Python canvas normalization supplies spoken
result labels independently of the renderer. A dismissed native adapter ignores
late projections, while a headless collector can retain the actual outcome.

Durable sessions use a schema-versioned SQLite ledger, full context checkpoints
and separate audio files. Accepted spoken input saves audio by default; typed
turns have no audio. `audio_status` includes attachment state, relative path,
checksum and any warning, with the original turn identity. A bounded capture
spool and one encoder worker keep encoding off the controller; level callbacks
publish finished metadata during subsequent listening. `listen_session` closes its
harness before unpublishing the listener PID. Headless one-shot callers must call
`Harness.close()` themselves.

`Harness(cfg, session_id=...)` claims a process lease and restores context, full
outcomes and source bindings. It never dispatches a saved request or restores a
pending confirmation. Interrupted effects are unknown; generic Yes/Continue/Resume
requires a fresh instruction. Configuration for each resumed writer is recorded
on its lifecycle event. The native adapter rebuilds presentation from saved events;
it does not put replayed events back into the ledger. CLI and native session
identity/history use the same repository. See [session-persistence.md](session-persistence.md)
for paths, controls, export, deletion and recovery contracts.

### Structured turn result

`Harness.run_turn` and `harness.engine.run_turn` return `TurnResult`, exported with
`ToolExecution` and `TurnStatus` from `agavai.harness`. Events describe progress;
the result describes the completed invocation. Returning a result does not certify
the factual accuracy of model text or imply that every requested action succeeded.

```python
@dataclass(frozen=True)
class TurnResult:
    session_id: str
    task_id: str
    request_id: str | None
    status: TurnStatus
    speech_text: str | None
    content: dict | None
    executions: tuple[ToolExecution, ...]
    first_event_sequence: int | None
    last_event_sequence: int | None
    schema_version: int = 1
```

`ToolExecution` contains `call_id`, `name`, exact argument JSON in `arguments`,
typed `status` (`ok`, `error`, `unknown`) and the full `result` text. It is a
projection of the existing ledger for this request only, including completed
effects during cancellation. Earlier requests' actions are excluded even after
resume. The result's IDs identify the final selected task and current request;
the initial `request_committed` event can refer to the task before classification.

| Turn status | Client meaning |
|---|---|
| `answered` | The engine produced a response; inspect executions for action outcomes |
| `awaiting_confirmation` | A proposal is waiting inside the harness; no proposed action has run |
| `needs_input` | More or corrected input is required |
| `held` | Input is paused; finalized words may be buffered as a draft |
| `listening` | Reset/resume control completed and the listener can continue |
| `cancelled` | This turn stopped; completed effects remain in executions |
| `failed` | A model/validation/action failure was handled and reported |
| `unknown` | An action's outcome could not be established; do not blindly retry |
| `incomplete` | Model/tool round budget ended before fulfillment |

`speech_text=None` means no speech, including held drafts, silent task reset and
cancellation. `content` is the last normalized content produced during this turn,
not an inherited canvas. Explicit answers contain raw Markdown in `text`; tools
reuse the existing normalized canvas contract. A turn can have no new content
while the UI retains an earlier canvas. Clears and source invalidation remain
explicit events. Pending proposals, callbacks and executable authority are never
included in the result.

Finalization builds one result, publishes its `to_dict()` in `task_status`, then
returns it. The inclusive sequence bounds run from admission through that final
event. Payloads are detached from live context and from each other; dataclasses
are frozen, while the content dictionary is caller-owned. `to_dict()` makes a
fresh JSON-serializable copy, including an executions array. The result payload
has schema version 1; the event envelope remains version 1 with an additive field.
Old persisted status events without a result still replay in the native adapter.

Blank input is rejected before admission: `needs_input`, the existing “I did not
hear anything.” speech, no executions/content, and `None` request ID and sequence
bounds. It emits no turn events and changes no context or pending confirmation.
The voice controller normally filters empty capture before calling the engine.
Infrastructure/consumer failures raise instead of manufacturing a successful
result. Audio publication and playback may happen after the turn's final event;
their later events are outside its range and do not mutate the returned result.

Voice and typed CLI adapters speak only `speech_text` when present and suppress
cancelled output. `agavai ask` retains plain spoken-text stdout and its existing
exit-code policy; this change does not add a JSON CLI mode. Evaluation consumes
the speech field for existing graders. The native adapter continues projecting
individual events and uses final `status`; it does not render the embedded result
again or grant it action authority.

### Voice and correction semantics

- ASR partials replace the provisional display text. Only finalized EOU, Enter,
  or an explicit configured endpointer can commit one request.
- VAD indicates speech activity, not intent. Whistle uses explicit Silero/energy
  or manual endpointing; Parakeet keeps native endpointing. Pauses shorter than
  the configured endpoint remain within the utterance.
- “Wait” or an explicit pause control holds assistant input; it is different
  from pausing recording audio. While recording, preserve the existing isolated
  name-addressed control rules; other speech is content, never desktop intent.
- Self-correction inside a committed utterance must reach decision/argument
  resolution before any call runs. “Five, no ten minutes” cannot execute both.
- Correcting a saved transcript uses its recording identity and exact segment.
  Keep heard text, apply the correction as an overlay, and acknowledge the actual
  update. Ambiguous repeated words or an unspecified recording require a choice.
- A late correction of an already executed action is a new request. The harness
  reports the earlier outcome; cancellation does not claim to undo it.

### Context packing and compaction

Raw task history and source references are retained separately from the bounded
messages supplied to a model. Compaction changes the prompt projection, not the
recording, user correction, execution record or pending confirmation.

Pack complete request/tool/result groups. Never leave an orphan tool result or
split the call from its outcome. Retain the current request, pending action and
active source revision. The oldest complete exchanges are omitted from the prompt when necessary;
the original remains in the context store. No generated memory digest or persistent
personal memory is implemented. If required input
cannot fit, use bounded source chunks or report the limit. Never silently omit
the transcript and answer as if it had been read. The current adapters do not expose tokenizers. The application uses a UTF-8
byte limit of 2 * (ctx_size - max_tokens), including serialized messages and
tool schemas. This is a packing policy, not an exact or guaranteed token limit;
a provider context-limit error remains visible. System text, schemas and the
active exchange must fit; otherwise the request fails explicitly.

### Reliability

Every asynchronous result belongs to the request that created it. InferenceSlot
allows one provider operation at a time and polls cancellation every 50 ms.
Only provider work runs in its daemon thread; tools and UI updates stay on the
controller thread. An interrupted HTTP operation may continue until its configured
deadline. The slot rejects new model work until it returns instead of queuing
abandoned operations. Provider logs retain the originating request ID. Cancellation
or replacement prevents later inference output from dispatching tools or
overwriting the current view. An interrupted external action may already have
executed; report an unknown outcome when it cannot be established. Never retry
non-idempotent actions merely because a model changed or a response timed out.

Structured tool failure must remain a failure. Text in OCR or a document that
contains “error” is data, not proof that the tool failed. Structured/long output
does not automatically mean “see the screen”: publish a usable canvas or produce
an interpretation from the relevant source. A tool-only provider cannot satisfy
a summary request by choosing any available tool.

## Modules

### Session controller

Code: [session.py](../src/agavai/harness/session.py).

- **Deployment:** in process, under the harness; CLI starts and controls it.
- **Lifecycle/protocol:** existing listener identity/lock, ASR commitment,
  recording controls, cancellation, input hold and playback; explicit modes.
- **Performance:** control handling must not wait for a synchronous model call.
  Endpointer latency remains separately observable, including the configured
  1100 ms Silero window; no new measured SLA is claimed.
- **Throughput:** one microphone owner; one active voice session. Model work
  cannot create a second capture process.
- **Configuration:** existing ASR/VAD and recording selections; controller policy
  is independent of model identity.
- **Observability:** session/request IDs, mode transitions, commit reason,
  discarded stale output and control-to-acknowledgement latency.

### Context store

Code: [context.py](../src/agavai/harness/context.py).

- **Deployment:** in process, independent of the native view.
- **Lifecycle/protocol:** create/reset task, append committed exchanges, bind
  resource, retain pending proposals, and pack model context. Recording source
  reads and corrections use the existing recording repository functions.
- **Performance:** ordinary metadata operations require no inference. Source
  reads and compaction are bounded and measured separately from model response.
- **Throughput:** serial task mutations; immutable snapshots for inference.
- **Configuration:** each tier's ctx_size and max_tokens determine the byte budget;
  oldest complete exchanges are omitted until it fits. No vector database or
  personal-memory service.
- **Observability:** task identity, relation decision, source revision, retained
  exchanges, compacted exchanges and prompt budget outcome, without transcript
  bodies in ordinary logs.

### Decision router

Code: [routing.py](../src/agavai/harness/routing.py).

- **Deployment:** in-process policy with calls to configured model services.
- **Lifecycle/protocol:** committed request + task snapshot + capability catalog
  → validated route: continue/new/clarify, action/reasoning/correction, bound
  source and required tools. Decisions never execute a function.
- **Performance:** avoid a hidden context-classification call followed by an
  identical planning call. Local exact controls skip inference. Warm/cold routing
  and escalation are measured; current CPU Qwen is a known bottleneck.
- **Throughput:** one accepted decision per request revision; late results have
  no authority over a newer request.
- **Configuration:** model capabilities and route policy are explicit. Existing
  `[router]` backends continue selecting tool schemas, not session authority.
- **Observability:** selected capability, task relation, source requirements,
  decision provider, retries and reason for clarification/escalation.

### Turn engine and model services

Code: [engine.py](../src/agavai/harness/engine.py).

- **Deployment:** engine in process; existing Needle, llama-server, ASR/VAD and
  speech workers retain their isolation and native dependencies.
- **Lifecycle/protocol:** source-grounded messages and allowed schemas in;
  answer, candidate calls, unsupported or error out. Services declare tool-only
  versus language-generation capability. A successful transport is not task
  success.
- **Performance:** reuse warm workers and stable prompt prefixes. Preserve
  configured absolute deadlines and model-round limits. No inference-time
  downloads or silent engine/device substitutions.
- **Throughput:** bounded work per service; waiting on inference must not own the
  control loop. No unbounded abandoned requests after interruption.
- **Configuration:** existing independent speech/brain roles and service sync;
  task routing may choose the language-capable role when required.
- **Observability:** actual model/backend/purpose, request revision, provider
  timing, fallback and result-synthesis timing.

### Execution manager

Code: [execution.py](../src/agavai/harness/execution.py).

- **Deployment:** in process; existing dispatcher functions remain tool adapters.
- **Lifecycle/protocol:** proposed call → schema/route validation → confirmation
  when required → dispatched → succeeded/failed/unknown. Pending confirmation
  binds an exact task, tool and argument revision and is consumed once.
- **Performance:** validation is local; external tool deadlines remain explicit.
  Cancellation suppresses future calls without claiming rollback.
- **Throughput:** ordered calls with dependencies; completed calls are not
  replayed on escalation. A compound request completes only when its requested
  operations have known outcomes.
- **Configuration:** allowlist, tool schemas, confirmation and timeout policy;
  no model-generated shell escape hatch.
- **Observability:** call ID, arguments revision, status, result reference,
  source kind, cancellation and request fulfillment independently of transport.

### Harness output events and results

Code: [events.py](../src/agavai/harness/events.py),
[results.py](../src/agavai/harness/results.py).

- **Deployment:** in process, constructed by `Harness`; no graphical imports.
- **Lifecycle/protocol:** one ordered `HarnessEvent` callback with detached data
  and one finalized `TurnResult` per admitted invocation; native and headless
  consumers use the same versioned contract above.
- **Performance:** synchronous callback/deep-copy cost is on the controller path;
  result copying scales with this turn's content and full outcomes. No extra model
  call or audio-encoding wait is added and no new latency SLA is claimed.
  Consumers must not perform long blocking work.
- **Throughput:** one controller producer and one sink; capture updates follow
  existing bounded audio-level cadence. The presentation sink has no retries;
  durable domain events are retained independently.
- **Configuration:** optional `on_event` and independent `should_cancel` callback.
- **Observability:** sequence, timestamp, session/task/request/call identity,
  actual decisions/models, complete outcomes, source revisions and task progress.

### Native snapshot and speech output

- **Deployment:** snapshot writer and speech client in process; native Quickshell
  surface and existing synthesis/playback services remain separate.
- **Lifecycle/protocol:** `ChatUi.on_harness_event` projects domain events into
  view data and actual pipeline events. UI commands return to the controller.
  UI state is never the authoritative conversation memory.
- **Performance:** metadata/capture updates do not wait for reasoning. Keep
  microphone level updates bounded; speech starts only from an accepted reply.
- **Throughput:** one current snapshot and one accepted spoken response; stale
  writes/playback cannot revive a cancelled request.
- **Configuration:** existing placement, voice and speech fallback selections.
- **Observability:** current task/mode, source, pending action, actual execution,
  model identity and speech outcome; preserve accessible native controls.

## Low-level design

### Client outcome and cancellation

```mermaid
sequenceDiagram
    participant Client as Voice or typed client
    participant Engine as Turn engine
    participant Execute as Execution manager
    participant Events as Harness output events
    Client->>Engine: run_turn(final text)
    Engine->>Events: request_committed and task/model progress
    Engine->>Execute: Validated call with task/request IDs
    opt Cancellation arrives during the external action
        Client->>Engine: should_cancel becomes true
    end
    Execute-->>Engine: Actual typed tool outcome
    Engine->>Events: tool_completed with actual outcome
    Engine->>Engine: Build TurnResult from finalized state
    Engine->>Events: task_status(status, result.to_dict())
    Note over Events: Persist canonical result before presentation
    Engine-->>Client: Same TurnResult
    Client->>Client: Speak optional speech; inspect status and executions
```

The finalized input enters the engine once. The execution manager returns its
actual outcome even if the caller cancelled during the effect. Finalization then
sets `cancelled`, retains that execution and returns no speech. A recording
shortcut can supersede inference without dismissing the listener; the voice
controller continues into recording when its dismissal input is false. The
result reports the turn's end, not a command to terminate the whole session.

### Recording summary, then a transcript correction

```mermaid
sequenceDiagram
    participant Session as Session controller
    participant Context as Context store
    participant Router as Decision router
    participant Engine as Turn engine
    participant Model as Reasoning service
    participant Execute as Execution manager
    participant Events as Harness output events
    participant View as Native snapshot and canvas
    Session->>Context: Recording saved: identity and source revision
    Session->>Router: Committed "summarize this recording" + task snapshot
    Router-->>Engine: Reasoning route + bound recording
    Engine->>Context: Load corrected transcript within model budget
    Context-->>Engine: Source text/chunks + provenance
    Engine->>Model: Request + source; no unrelated desktop tools
    Model-->>Engine: Grounded summary
    Engine->>Events: Source revision + raw Markdown answer + spoken synopsis
    Events->>View: Native adapter renders the accepted answer
    Session->>Router: Committed "replace cube flow with Kubeflow"
    Router-->>Execute: Exact recording/segment/revision, or clarification
    Execute->>Context: Apply validated correction, preserve heard words
    Engine->>Events: Updated source revision; prior summary is stale
    Events-->>View: Native adapter projects source change
```

The saved recording enters the context store when capture finishes, not by OCR
of the desktop. If no unique source exists, the router asks which recording.
If the transcript is too large, the engine processes bounded segments and
combines source-labelled summaries; it cannot fall back to arbitrary screen
inspection. After a correction, derived output identifies its earlier source
revision and cannot be presented as an up-to-date summary without regeneration.

### Pauses, corrections, task changes and cancellation

```mermaid
sequenceDiagram
    participant Speech as Speech services
    participant Session as Session controller
    participant Context as Context store
    participant Router as Decision router
    participant Execute as Execution manager
    Speech-->>Session: Partial "remind me in five"
    Session->>Context: Provisional revision; no route or action
    Speech-->>Session: Final "five no ten minutes to call the bank"
    Session->>Router: One committed request + task snapshot
    Router-->>Execute: Resolved ten-minute proposal, or clarify
    Execute-->>Context: Actual result, never a five-minute intermediate action
    Session->>Context: Explicit new task clears inherited prompt/tools
    Session->>Router: Unrelated request with fresh task context
    Session->>Context: Cancel or record control invalidates active generation
    Note over Session,Execute: Controller remains responsive while providers wait
    Execute-->>Context: In-flight side effect: known result or unknown; no blind replay
```

Silence that does not commit remains speech state. An input hold preserves the
draft; a task reset clears conversation and pending proposals; stopping a
recording saves audio. These are distinct transitions. Recording capture never
routes meeting content as assistant instructions. Exact local confirmation
controls act only on the current pending proposal. Free-form “no, make it fifty”
is a correction route, not permission to execute an earlier forty-percent call.

### BDD acceptance matrix

Only E2E BDD verification is added. Existing model-replay and native UI scenarios
remain part of regression validation. Model-quality evaluations use frozen
tools and recorded speech rather than the real desktop.

| Given / When | Required Then |
|---|---|
| Partial words, a pause, revised words, then one final | No action before commit; exactly one accepted request |
| A short pause within configured silence window | The utterance remains open |
| Explicit input pause/resume | Draft remains; no model or tool runs while held |
| One finalized utterance corrects five to ten | One ten-minute reminder, or clarification; no five-minute side effect |
| A saved recording and a summary follow-up | Model receives its corrected transcript; no `screen_context` substitute |
| An ambiguous recording or correction span | Ask a concrete clarification; no guessed edit |
| An explicit word correction | Heard words retained, effective transcript updated, older derived views stale |
| A follow-up versus unrelated new request | Relevant task history retained versus inherited context/tools cleared |
| Context exceeds the model budget | Complete exchanges compacted; original results remain retrievable |
| A tool returns JSON containing the word error as data | Typed status is respected; content is not misclassified |
| A tool-only model returns a read result requiring explanation | Produce a grounded answer or explicit inability, never false fulfillment |
| Cancel/record while inference waits | Control acknowledged without waiting for model timeout; late output cannot act |
| A model escalates after an executed call | Known completed call is not repeated |
| Session reset, correction or cancellation before Yes | Stale proposal cannot execute |

### Implemented migration and limits

The CLI delegates to Harness and the session controller. The former orchestrator
was moved to the turn engine; no parallel legacy engine or UI context registry
remains. Live voice, typed requests, evals and BDD callers use these contracts.

Recording interpretation uses corrected recording.json segments with a SHA-256
revision, no desktop schemas, and a source canvas. A changed revision rejects the
in-flight answer. Inputs are chunked within the byte policy; at most
max_tool_rounds - 1 chunks plus one combining request are accepted. A larger
recording requires a narrower source rather than silent truncation. This does not
implement timestamp-linked Notes tabs or durable derived views. Voice edits support
“replace old with new” for one unique occurrence, or “correct line N to full corrected
text”. Ambiguity changes nothing. Corrections share a per-recording advisory edit lock;
source-derived edits compare their expected effective line inside that lock, so a
concurrent correction cannot be silently overwritten.

Exact “wait”/“pause” holds input; finalized words while held accumulate as a draft.
“Resume” keeps the draft without executing it; the next finalized request completes
it. This is separate from name-addressed recording pause/resume.

Execution records include task/request/call identity, exact arguments, full result
and ok/error/unknown status. Timeouts and unexpected tool exceptions have unknown
outcomes and are not automatically retried. Confirmations are schema-validated
before storage and consumed once. Task status is separate from tool status:
answered, awaiting_confirmation, needs_input, held, listening, failed, unknown, incomplete or
cancelled describes harness progress, not proof of a model answer's factual accuracy.

[Harness E2E BDD](../features/harness.feature) exercises real HTTP model transport,
recording files and tool dispatch with scripted external services. Existing speech
workers, endpoints, native UI, allowlist, confirmations and engine scenarios remain
regression requirements. Deployment is a separate operation.
[Headless event BDD](../features/harness_events.feature) additionally forbids UI
imports in a separate process and checks event identity/order, confirmations,
raw answer content, source revisions, cancellation, payload isolation, consumer
failure and recording controls without a snapshot.
[Structured-result BDD](../features/harness_results.feature) checks final event and
ledger agreement, per-request outcomes, silent controls, confirmation, cancellation,
detached content, resume, and actual voice/typed client consumption.

## Conclusion & References

Agavai owns the conversation and execution lifecycle. Models provide replaceable
capabilities inside it. The router's job grows from choosing tool heads to
choosing a source-grounded task path; it does not acquire control over commitment
or permission checks. This separates the observed wrong-tool, missing-context
and generic-acknowledgement failures into testable contracts.

- Runtime authority and controls: [flow.md](flow.md), [audio.md](audio.md),
  [voice controls](../tasks/voice-controls.md),
  [conversation context](../tasks/conversation-context.md).
- Native presentation and recordings: [ui-design.md](ui-design.md),
  [recording.md](recording.md), [recording task](../tasks/recording.md).
- Engines and deployment: [engines.md](engines.md),
  [model-engines.md](model-engines.md), [architecture.md](architecture.md),
  [existing component design](architecture-design/design.md).
- Implemented entry points: [CLI](../src/agavai/__main__.py), [session controller](../src/agavai/harness/session.py),
  [turn engine](../src/agavai/harness/engine.py), [router](../src/agavai/router.py),
  [brain adapters](../src/agavai/brain.py), [worker transport](../src/agavai/worker.py),
  [UI snapshot](../src/agavai/ui.py), [recordings](../src/agavai/recording.py).
- Local alternatives and limits: [native Qwen/Needle comparison](../evals/results/20261025-brain-comparison-cached/README.md),
  [evaluation contract](eval.md). These are local observations, not latency SLAs.
- Patterns used: explicit state ownership, ports/adapters, source references,
  versioned proposals, complete tool exchanges and bounded context projections.
  No external harness framework was evaluated or selected for this design.
