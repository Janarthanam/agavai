"""Ordered execution records, independent of model prompts and the native view."""
from dataclasses import dataclass, field
import json

from agavai.outcomes import ToolOutcome


@dataclass
class ExecutionManager:
    records: list[dict] = field(default_factory=list)

    def execute(self, call, cfg, dispatch, cancelled) -> ToolOutcome | None:
        if cancelled():
            return None
        fn = call["function"]
        record = {"id": call.get("id"), "name": fn["name"], "arguments": fn.get("arguments") or "{}",
                  "status": "running"}
        self.records.append(record)
        result = dispatch(fn["name"], fn.get("arguments") or "{}", cfg)
        record.update(status=result.status, result=result.text)
        # The result remains recorded even if dismissal happened during the side effect.
        if cancelled():
            return None
        return result
