"""Completed turn outcomes, independent of presentation and execution authority."""
from dataclasses import asdict, dataclass
from typing import Any, Literal


TurnStatus = Literal[
    "answered", "awaiting_confirmation", "needs_input", "held", "listening",
    "cancelled", "failed", "unknown", "incomplete",
]


@dataclass(frozen=True)
class ToolExecution:
    call_id: str
    name: str
    arguments: str
    status: Literal["ok", "error", "unknown"]
    result: str


@dataclass(frozen=True)
class TurnResult:
    session_id: str
    task_id: str
    request_id: str | None
    status: TurnStatus
    speech_text: str | None
    content: dict[str, Any] | None
    executions: tuple[ToolExecution, ...]
    first_event_sequence: int | None
    last_event_sequence: int | None
    schema_version: int = 1

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["executions"] = list(data["executions"])
        return data
