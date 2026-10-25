"""Cactus Needle adapter worker. No callable tools enter the native SDK."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agavai.worker import emit, read_frame


def normalize(response):
    calls = response.get("function_calls") or []
    if response.get("type") != "call" or not calls:
        return {"unsupported": "No matching tool call"}
    if response.get("ungrounded") or (response.get("validation") or {}).get("ungrounded") or (response.get("validation") or {}).get("negation"):
        return {"unsupported": "Needle produced ungrounded arguments"}
    normalized = []
    for call in calls:
        if call.get("ungrounded") or not isinstance(call.get("name"), str) or not isinstance(call.get("arguments", {}), dict):
            return {"unsupported": "Needle produced invalid or ungrounded arguments"}
        normalized.append({"id": uuid.uuid4().hex, "type": "function", "function": {
            "name": call["name"], "arguments": json.dumps(call.get("arguments", {}), ensure_ascii=False)}})
    return {"content": "", "tool_calls": normalized}


def main():
    from agavai.cactus_runtime import prepare
    prepare(os.environ["NEEDLE3_LIB_PATH"])
    from needle import Needle
    agent = None
    previous = None
    try:
        while (frame := read_frame(sys.stdin.buffer)) is not None:
            request = json.loads(frame)
            schemas = [tool["function"] for tool in request["tools"]]
            system = request["messages"][0].get("content", "")
            key = json.dumps([schemas, system], sort_keys=True)
            if key != previous:
                if agent is not None:
                    agent.close()
                agent = Needle(tools=schemas, system=system, weights=sys.argv[1], auto_date=False, stateless=True)
                previous = key
            history = [message for message in request["messages"] if message["role"] != "system"]
            query = history[0]["content"] if len(history) == 1 else json.dumps(history, ensure_ascii=False)
            response = agent.complete(query, max_new_tokens=request["max_tokens"])
            emit({"kind": "result", "message": normalize(response)})
    finally:
        if agent is not None:
            agent.close()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        emit({"kind": "error", "text": str(exc)})
        sys.exit(1)
