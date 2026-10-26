"""Session-scoped source records and bounded projections of task history."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any, Callable
import uuid

from agavai.llm import LlmError
from agavai.harness.execution import ExecutionManager
from agavai.harness.inference import InferenceSlot


@dataclass(frozen=True)
class PendingAction:
    session_id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class ContextStore:
    session_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    request_id: str = ""
    turn_status: str = "idle"
    task_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    messages: list[dict[str, Any]] = field(default_factory=list)
    heads: list[str] = field(default_factory=list)
    pending_action: PendingAction | None = None
    committed_requests: list[str] = field(default_factory=list)
    archived_tasks: list[dict[str, Any]] = field(default_factory=list)
    recording: Path | None = None
    source_active: bool = False
    source_revision: str = ""
    derived_revision: str = ""
    compacted_exchanges: int = 0
    execution: ExecutionManager = field(default_factory=ExecutionManager)
    inference: InferenceSlot = field(default_factory=InferenceSlot)
    should_cancel: Callable[[], bool] = field(default=lambda: False, repr=False)
    held: bool = False
    draft: str = ""
    recovery_required: bool = False
    remembered_request_id: str = ""

    def checkpoint(self) -> dict:
        names = ("session_id", "request_id", "turn_status", "task_id", "messages", "heads",
                 "committed_requests", "archived_tasks", "source_active", "source_revision",
                 "derived_revision", "compacted_exchanges", "held", "draft", "recovery_required", "remembered_request_id")
        return {**{name: deepcopy(getattr(self, name)) for name in names},
                "recording": str(self.recording) if self.recording else None,
                "execution": deepcopy(self.execution.records)}

    @classmethod
    def from_checkpoint(cls, data: dict) -> ContextStore:
        values = deepcopy(data)
        values["recording"] = Path(values["recording"]) if values.get("recording") else None
        values["execution"] = ExecutionManager(values.pop("execution"))
        return cls(**values)

    def new_task(self) -> None:
        if self.messages:
            self.archived_tasks.append({"id": self.task_id, "messages": self.messages, "heads": self.heads})
        self.task_id = uuid.uuid4().hex
        self.messages = []
        self.remembered_request_id = ""
        self.heads = []
        self.pending_action = None
        self.compacted_exchanges = 0
        self.held = False
        self.draft = ""
        self.source_active = False

    def remember(self, messages: list[dict], heads: list[str]) -> None:
        self.remembered_request_id = self.request_id
        self.messages = deepcopy([m for m in messages if m.get("role") != "system"])
        self.heads = list(heads)

    def pack(self, messages: list[dict], tools: list[dict], tier) -> list[dict]:
        # This is an application byte budget, not an exact model token count.
        # Reserve generated output and account for schemas before retaining history.
        budget = max(0, tier.ctx_size - tier.max_tokens) * 2
        overhead = len(json.dumps(tools, ensure_ascii=False).encode())
        system = [m for m in messages if m.get("role") == "system"]
        groups: list[list[dict]] = []
        for message in messages:
            if message.get("role") == "system":
                continue
            if message.get("role") == "user" or not groups:
                groups.append([])
            groups[-1].append(message)
        kept = list(groups)
        def size():
            return overhead + len(json.dumps([*system, *(m for g in kept for m in g)], ensure_ascii=False).encode())
        while len(kept) > 1 and size() > budget:
            kept.pop(0)
        self.compacted_exchanges = len(groups) - len(kept)
        if size() > budget:
            raise LlmError("The current request, source and tools exceed the model input budget. Please narrow the request.")
        return deepcopy([*system, *(m for g in kept for m in g)])
