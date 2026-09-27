from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

from oma_voice.config import LlmConfig
from oma_voice.tools import OPENAPI_TOOLS


class LlmError(RuntimeError):
    pass


def health(cfg: LlmConfig) -> bool:
    for path in ("/health", "/v1/models"):
        try:
            with urllib.request.urlopen(f"{cfg.base_url}{path}", timeout=1) as resp:
                if 200 <= resp.status < 300:
                    return True
        except (urllib.error.URLError, TimeoutError, OSError):
            continue
    return False


def chat(
    cfg: LlmConfig,
    messages: list[dict[str, Any]],
    *,
    tools: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": cfg.alias,
        "messages": messages,
        "temperature": cfg.temperature,
        "max_tokens": cfg.max_tokens,
        "stream": False,
    }
    if tools is None:
        tools = OPENAPI_TOOLS
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        f"{cfg.base_url}/v1/chat/completions",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=cfg.timeout_secs) as resp:
            body = json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:800]
        raise LlmError(f"llama-server HTTP {exc.code}: {detail}") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise LlmError(f"llama-server unreachable at {cfg.base_url}: {exc}") from exc
    choices = body.get("choices") or []
    if not choices:
        raise LlmError(f"empty llama-server response: {body!r}"[:500])
    message = choices[0].get("message") or {}
    return message


def parse_tool_calls(message: dict[str, Any]) -> list[dict[str, Any]]:
    """OpenAI tool_calls, plus Qwen <tool_call> XML if the template leaks."""
    calls = message.get("tool_calls") or []
    if calls:
        return list(calls)
    content = message.get("content") or ""
    if "<tool_call>" not in content:
        return []
    out: list[dict[str, Any]] = []
    chunks = content.split("<tool_call>")
    for chunk in chunks[1:]:
        raw = chunk.split("</tool_call>", 1)[0].strip()
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            continue
        name = obj.get("name")
        args = obj.get("arguments") or obj.get("parameters") or {}
        if not name:
            continue
        out.append(
            {
                "id": f"xml-{len(out)}",
                "type": "function",
                "function": {
                    "name": name,
                    "arguments": args if isinstance(args, str) else json.dumps(args),
                },
            }
        )
    return out
