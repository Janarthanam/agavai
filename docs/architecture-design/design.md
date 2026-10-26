# Agavai component design

The implemented in-process harness design is maintained in
[voice-agent-harness.md](../voice-agent-harness.md). It contains the requirements,
choices, tradeoffs, architecture diagram, per-module deployment, lifecycle, latency,
throughput, configuration and observability contracts, critical sequences,
acceptance matrix and references.

[architecture.md](../architecture.md) maps processes and code.
[flow.md](../flow.md) governs runtime; [audio.md](../audio.md),
[ui-design.md](../ui-design.md), [engines.md](../engines.md) and
[recording.md](../recording.md) specify their respective boundaries.

## Implementation mapping

| Component | Code / interface |
|---|---|
| Harness | Harness(cfg, on_event=consumer, should_cancel=callback).run_turn(text, continue_conversation=...) |
| Output events | harness/events.py: ordered, serializable HarnessEvent envelopes with detached data |
| Session controller | harness/session.py: listener identity, ASR events, controls, recording |
| Context store | harness/context.py: tasks, archive, proposals, source revision, prompt projection |
| Decision layer | harness/routing.py: capability/source policy, language task relation |
| Turn engine | harness/engine.py: bounded provider and tool coordination |
| Source interpretation | harness/sources.py, source_turn.py: corrected text, exact edits, chunk/combine |
| Execution manager | harness/execution.py: schema checks and ordered outcome records |
| Inference slot | harness/inference.py: one provider operation and cancellation fence |
| Model adapters | brain.py, speech_backends.py, worker.py |
| Native projection | ui.py, canvas.py, plugin/Chat.qml, plugin/BarWidget.qml |

The former orchestrator and CLI-owned listener were migrated rather than retained
alongside a second harness. ChatUi owns display data only and consumes events
through `on_harness_event`. Headless consumers require no native snapshot.

## Critical flows

~~~mermaid
sequenceDiagram
    participant Session as Session controller
    participant Engine as Turn engine
    participant Context as Context store
    participant Decide as Decision layer
    participant Model as Model service
    participant Execute as Execution manager
    Session->>Engine: One finalized request
    Engine->>Context: Replace pending proposal; retain raw request
    Engine->>Decide: Task relation, source and capability
    Decide-->>Engine: Action, language, correction or source path
    Engine->>Context: Bounded complete-exchange projection
    Engine->>Model: Messages and route-scoped schemas
    Model-->>Engine: Answer or candidate calls
    Engine->>Execute: Validate and dispatch ordered calls
    Execute-->>Context: Full typed outcome, task and request identity
    Engine-->>Session: Accepted reply and UI-independent output events
~~~

Recording summaries bind corrected source before calling a language model, with no
desktop schemas. Word edits preserve heard words, change the source revision and
invalidate derived output. Cancellation during provider work stops acceptance of
the result; that thread never executes tools. Recording controls are served before
the provider finishes. [Harness BDD](../../features/harness.feature) exercises these
flows.

The [interactive component map](index.html) is a historical visual baseline; the canonical
contracts above take precedence over a historical source baseline.
