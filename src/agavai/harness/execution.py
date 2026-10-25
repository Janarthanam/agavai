"""Ordered execution records, independent of model prompts and the native view."""
from dataclasses import dataclass, field
import json

from agavai.outcomes import ToolOutcome
from agavai.llm import LlmError


@dataclass
class ExecutionManager:
    records: list[dict] = field(default_factory=list)

    def execute(self, call, cfg, dispatch, cancelled, *, task_id, request_id) -> ToolOutcome | None:
        if cancelled():
            return None
        fn = call["function"]
        record = {"id": call.get("id"), "name": fn["name"], "arguments": fn.get("arguments") or "{}",
                  "status": "running", "task_id": task_id, "request_id": request_id}
        self.records.append(record)
        result = dispatch(fn["name"], fn.get("arguments") or "{}", cfg)
        record.update(status=result.status, result=result.text)
        # The result remains recorded even if dismissal happened during the side effect.
        if cancelled():
            return None
        return result


def validate_call(call, selected):
    """Validate model-generated arguments against the schemas actually offered."""
    fn = call["function"]
    try:
        args = json.loads(fn.get("arguments") or "{}")
    except (ValueError, TypeError) as exc:
        raise LlmError("Invalid tool arguments JSON; no action has executed.") from exc
    schema = next(item["function"]["parameters"] for item in selected if item["function"]["name"] == fn["name"])

    def validate(value, spec):
        types = {"object": dict, "string": str, "integer": int, "number": (int, float), "boolean": bool, "array": list}
        kind = spec.get("type")
        if kind in types and (not isinstance(value, types[kind]) or (kind in {"integer", "number"} and isinstance(value, bool))):
            raise LlmError(f"Invalid {fn['name']} arguments: expected {kind}.")
        if "enum" in spec and value not in spec["enum"]:
            raise LlmError(f"Invalid {fn['name']} argument choice.")
        if isinstance(value, dict):
            properties = spec.get("properties", {})
            if any(key not in value for key in spec.get("required", [])):
                raise LlmError(f"Missing required {fn['name']} arguments.")
            if spec.get("additionalProperties") is False and value.keys() - properties.keys():
                raise LlmError(f"Unexpected {fn['name']} arguments.")
            for key in value.keys() & properties.keys():
                validate(value[key], properties[key])
    validate(args, schema)
