from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request
from typing import Any

from agavai.config import LlmConfig

log = logging.getLogger(__name__)


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
    tools: list[dict[str, Any]],
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": cfg.alias,
        "messages": messages,
        "temperature": cfg.temperature,
        "max_tokens": cfg.max_tokens,
        "stream": False,
    }
    if cfg.seed is not None:
        payload["seed"] = cfg.seed
    if cfg.cache_prompt is not None:
        payload["cache_prompt"] = cfg.cache_prompt
    # The caller routes the tools (see agavai.router).
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
    started = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=cfg.timeout_secs) as resp:
            body = json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:800]
        raise LlmError(f"llama-server HTTP {exc.code}: {detail}") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise LlmError(f"llama-server unreachable at {cfg.base_url}: {exc}") from exc
    except (ValueError, OSError) as exc:
        raise LlmError(f"Invalid llama-server response: {exc}") from exc
    if not isinstance(body, dict):
        raise LlmError("llama-server response must be an object.")
    choices = body.get("choices") or []
    if not choices:
        raise LlmError(f"empty llama-server response: {body!r}"[:500])
    message = choices[0].get("message") or {}
    if not isinstance(message, dict) or not isinstance(message.get("content") or "", str):
        raise LlmError("Invalid assistant message from llama-server.")
    usage = body.get("usage") or {}
    calls = [str((call.get("function") or {}).get("name")) for call in parse_tool_calls(message)]
    log.info(
        "llm model=%s tools=%d prompt_tokens=%s completion_tokens=%s calls=%s secs=%.2f",
        cfg.model_id, len(tools), usage.get("prompt_tokens"), usage.get("completion_tokens"),
        ",".join(calls) or "none", time.monotonic() - started,
    )
    return message


def parse_tool_calls(message: dict[str, Any]) -> list[dict[str, Any]]:
    """OpenAI tool_calls, plus Qwen <tool_call> XML if the template leaks."""
    calls = message.get("tool_calls") or []
    if calls:
        if not isinstance(calls, list) or any(not isinstance(call, dict) or not isinstance(call.get("function"), dict) for call in calls):
            raise LlmError("Invalid tool calls from the model.")
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
