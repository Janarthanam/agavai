from __future__ import annotations

from datetime import datetime
from typing import Any

from agavai.config import Config
from agavai.llm import LlmError, chat, health, parse_tool_calls
from agavai.heads import head_for_tool, schemas_for_heads
from agavai.router import select_head_ids
from agavai.tools import DISPATCH, call_tool
from agavai.ui import ChatUi

SYSTEM = """You are Agavai, a local Omarchy Linux voice assistant.
Your final message is spoken aloud automatically. Always answer in one or two short spoken sentences. No markdown, no code fences, no lists.
Never say you cannot speak, talk, generate voice, or say a word. If asked to say something, say it.
Desktop actions exist only through the tools you were given this turn. Never claim you launched an app, changed a setting, or clicked something unless a tool result says so.
Do not call remote models or coding agents. Do not ask for a shell.
If a needed desktop action is not among the tools you were given, say you cannot do that action — still in a spoken sentence.
Current local time: {now}
"""

_RESULT_LIMIT = 500


def run_turn(text: str, cfg: Config, ui: ChatUi | None = None) -> str:
    text = text.strip()
    if not text:
        return "I did not hear anything."
    if ui:
        ui.user(text)
    if not health(cfg.llm):
        msg = (
            "The local model is not running. Start it with: "
            "systemctl --user start agavai-llm"
        )
        if ui:
            ui.error(msg)
        return msg
    head_ids = select_head_ids(text, cfg)
    selected = schemas_for_heads(head_ids, limit=cfg.router.max_tools)
    selected_names = {item["function"]["name"] for item in selected}
    messages: list[dict[str, Any]] = [
        {
            "role": "system",
            "content": SYSTEM.format(now=datetime.now().strftime("%A, %Y-%m-%d %H:%M")),
        },
        {"role": "user", "content": text},
    ]
    retried = False
    try:
        for _ in range(cfg.llm.max_tool_rounds):
            if ui and ui.cancelled():
                return ""
            message = chat(cfg.llm, messages, tools=selected)
            calls = parse_tool_calls(message)
            content = (message.get("content") or "").strip()
            if not calls:
                reply = _strip_think(content) or "Done."
                if ui:
                    ui.assistant(reply)
                return reply
            extra_heads: list[str] = []
            for call in calls:
                name = (call.get("function") or {}).get("name") or ""
                if name in DISPATCH and name not in selected_names:
                    head = head_for_tool(name)
                    if head and head not in head_ids:
                        extra_heads.append(head)
            if extra_heads and not retried:
                retried = True
                head_ids.extend(extra_heads)
                selected = schemas_for_heads(head_ids, limit=cfg.router.max_tools)
                selected_names = {item["function"]["name"] for item in selected}
                continue
            messages.append(
                {
                    "role": "assistant",
                    "content": content or None,
                    "tool_calls": calls,
                }
            )
            for call in calls:
                fn = call.get("function") or {}
                if ui and ui.cancelled():
                    return ""
                name = fn.get("name") or ""
                raw_args = fn.get("arguments") or "{}"
                if ui:
                    ui.tool_start(name, raw_args)
                result = call_tool(name, raw_args, cfg)
                if ui:
                    ui.tool_done(name, result)
                if len(result) > _RESULT_LIMIT:
                    result = result[: _RESULT_LIMIT - 1] + "…"
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.get("id") or name,
                        "content": result,
                    }
                )
        msg = "I ran out of tool steps before finishing."
        if ui:
            ui.error(msg)
        return msg
    except LlmError as exc:
        if ui:
            ui.error(str(exc))
        return str(exc)


def _strip_think(text: str) -> str:
    if "<think>" in text and "</think>" in text:
        pre, _, rest = text.partition("<think>")
        _, _, post = rest.partition("</think>")
        text = (pre + post).strip()
    return text
