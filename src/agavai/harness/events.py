"""Ordered harness output, independent of the native snapshot or graphical UI."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Literal

from agavai.brain import brain_label
from agavai.canvas import display_for

EventKind = Literal[
    "session_started", "session_resumed", "session_closed", "audio_status",
    "request_committed", "task_started", "turn_input", "conversation_cleared",
    "listening", "partial", "level", "transcribing", "stage", "decision",
    "model_requested", "confirmation_requested", "tool_started", "tool_completed", "answer", "display",
    "reply", "source_changed", "task_status", "recording", "recording_ended",
    "speech", "idle", "error",
]


@dataclass(frozen=True)
class HarnessEvent:
    sequence: int
    timestamp: str
    session_id: str
    task_id: str
    request_id: str
    kind: EventKind
    data: dict[str, Any]
    schema_version: int = 1

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


EventSink = Callable[[HarnessEvent], None]


class EventDeliveryError(RuntimeError):
    """A consumer failure must not be handled as a model or source failure."""


class HarnessOutput:
    def __init__(self, context, sink: EventSink | None = None, *, on_record: EventSink | None = None):
        self.context = context
        self.sink = sink
        self.on_record = on_record
        self.sequence = 0
        self.phase = "idle"
        self.current_result = None

    @property
    def interactive(self) -> bool:
        return self.sink is not None

    def emit(self, kind: EventKind, *, request_id: str | None = None, task_id: str | None = None, **data) -> None:
        self.sequence += 1
        event = HarnessEvent(self.sequence, datetime.now(timezone.utc).isoformat(),
            self.context.session_id, task_id if task_id is not None else self.context.task_id, request_id if request_id is not None else self.context.request_id,
            kind, deepcopy(data))
        try:
            if self.on_record is not None:
                self.on_record(event)
            if self.sink is not None:
                self.sink(event)
        except Exception as exc:
            raise EventDeliveryError(f"Could not deliver {kind}: {exc}") from exc

    def begin_session(self, **metadata) -> None:
        self.emit("session_started", **metadata)

    def clear_conversation(self) -> None:
        self.current_result = None
        self.emit("conversation_cleared")

    def task_state(self, status: str) -> None:
        self.emit("task_status", status=status)

    def pipeline_event(self, stage: str, detail: str) -> None:
        self.emit("stage", stage=stage, detail=detail)

    def decision(self, decision) -> None:
        self.emit("decision", capability=decision.capability, reason=decision.reason, source=decision.source)

    def brain(self, tier, purpose: str) -> None:
        self.emit("model_requested", model_id=tier.model_id, backend=tier.backend,
                  model_path=str(tier.model_path), purpose=purpose, label=brain_label(tier))

    def speech(self, engine: str) -> None:
        self.emit("speech", engine=engine)

    def listening(self) -> None:
        self.phase = "listening"
        self.current_result = None
        self.emit("listening", fresh=True)

    def continue_listening(self) -> None:
        self.phase = "listening"
        self.emit("listening", fresh=False)

    def partial(self, text: str) -> None:
        self.emit("partial", text=text)

    def display(self, content: dict | None) -> None:
        self.current_result = deepcopy(content)
        self.emit("display", content=content)

    def answer(self, title: str, markdown: str) -> None:
        self.current_result = {"kind": "answer", "title": title, "text": markdown}
        self.emit("answer", title=title, markdown=markdown)

    def source_changed(self, source: dict) -> None:
        self.emit("source_changed", source=source)

    def level(self, db: float | None, vad_state: str, vad_backend: str) -> None:
        self.emit("level", db=db, vad_state=vad_state, vad_backend=vad_backend)

    def transcribing(self) -> None:
        self.phase = "transcribing"
        self.emit("transcribing")

    def user(self, text: str, *, keep_display: bool = False) -> None:
        if not keep_display:
            self.current_result = None
        self.phase = "thinking"
        self.emit("turn_input", text=text, keep_context=keep_display)

    def tool_start(self, name: str, arguments: Any, *, call_id: str) -> None:
        self.phase = "thinking"
        self.emit("tool_started", name=name, arguments=arguments, call_id=call_id)

    def tool_done(self, name: str, result: str, *, status: str, call_id: str) -> None:
        # The spoken reply uses the same normalized labels even without a UI sink.
        content = display_for(name, result)
        if content is not None:
            self.current_result = content
        self.emit("tool_completed", name=name, result=result, status=status, call_id=call_id)

    def assistant(self, text: str) -> None:
        self.phase = "speaking"
        self.emit("reply", text=text)

    def recording(self, content: dict, *, summon: bool = False) -> None:
        self.phase = "recording"
        self.emit("recording", content=content, summon=summon)

    def end_recording(self) -> None:
        self.emit("recording_ended")

    def idle(self) -> None:
        self.phase = "idle"
        self.emit("idle")

    def error(self, text: str) -> None:
        self.phase = "error"
        self.emit("error", message=text)
