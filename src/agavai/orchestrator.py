from __future__ import annotations

from datetime import datetime
from typing import Any

from agavai.config import Config
from agavai.llm import LlmError, chat, health, parse_tool_calls
from agavai.tools import call_tool
from agavai.ui import ChatUi

SYSTEM = """You are a local Omarchy Linux voice assistant running on this machine.
You can only act through the provided tools. Never invent that you launched an app, changed a theme, or clicked something unless a tool result says so.
Keep the final answer short and speakable (one or two sentences). No markdown, no code fences.
Do not call remote models or coding agents. Do not ask for a shell.
If the user wants something you cannot do with these tools, say so plainly.
Current local time: {now}
"""


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
    messages: list[dict[str, Any]] = [
        {
            "role": "system",
            "content": SYSTEM.format(now=datetime.now().strftime("%A, %Y-%m-%d %H:%M")),
        },
        {"role": "user", "content": text},
    ]
    try:
        for _ in range(cfg.llm.max_tool_rounds):
            message = chat(cfg.llm, messages)
            calls = parse_tool_calls(message)
            content = (message.get("content") or "").strip()
            if not calls:
                reply = _strip_think(content) or "Done."
                if ui:
                    ui.assistant(reply)
                return reply
            messages.append(
                {
                    "role": "assistant",
                    "content": content or None,
                    "tool_calls": calls,
                }
            )
            for call in calls:
                fn = call.get("function") or {}
                name = fn.get("name") or ""
                raw_args = fn.get("arguments") or "{}"
                if ui:
                    ui.tool_start(name, raw_args)
                result = call_tool(name, raw_args, cfg)
                if ui:
                    ui.tool_done(name, result)
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
