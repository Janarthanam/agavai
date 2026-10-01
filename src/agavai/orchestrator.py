from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from agavai.config import Config
from agavai.llm import LlmError, chat, health, parse_tool_calls
from agavai.heads import head_for_tool, schemas_for_heads
from agavai.router import select_head_ids
from agavai.canvas import model_view, read_aloud
from agavai.tools import DISPATCH, call_tool
from agavai.ui import ChatUi

SYSTEM = """You are Agavai, a local Omarchy Linux voice assistant.
Your final message is spoken aloud automatically. Always answer in one or two short spoken sentences. No markdown, no code fences, no lists.
Never say you cannot speak, talk, generate voice, or say a word. If asked to say something, say it.
Desktop actions exist only through the tools you were given this turn. Never claim you launched an app, changed a setting, or clicked something unless a tool result says so.
Do not call remote models or coding agents. Do not ask for a shell.
If a needed desktop action is not among the tools you were given, say you cannot do that action — still in a spoken sentence.
When the user asks to see wallpaper, background, or screensaver images, call wallpaper_list before you answer so the pictures appear. Then ask which image they want, in one short question.
Later messages are the same person continuing. Use the earlier list and call wallpaper_set with the image they name. Do not ask them to pick an image that was not listed.
When a tool succeeds, say exactly what finished in one sentence, naming the wallpaper, reminder, or other change.
File, folder, image, and video results give you a kind and a name. Speak those names. Never speak a filesystem path.
Current local time: {now}
"""

_FOLLOWUP = re.compile(r"\b(you want|which|tell me|let me know)\b", re.IGNORECASE)

_RESULT_LIMIT = 500


def _model_tool_text(name: str, result: str) -> str:
    text = model_view(name, result)
    if len(text) > _RESULT_LIMIT:
        text = text[: _RESULT_LIMIT - 1] + "…"
    return text


def wants_followup(reply: str) -> bool:
    """True when the spoken line is waiting for the user's choice."""
    text = " ".join(str(reply).split())
    if text.endswith("?"):
        return True
    return len(text) >= 12 and _FOLLOWUP.search(text) is not None


def _asking_for_images(text: str) -> bool:
    blob = " " + re.sub(r"[^a-z0-9]+", " ", text.lower()) + " "
    showing = any(token in blob for token in (" show ", " see ", " list ", " images ", " image ", " pictures ", " picture "))
    subject = any(token in blob for token in (" screensaver ", " wallpaper ", " background ", " images ", " image ", " pictures ", " picture "))
    return showing and subject


def _merge_heads(new: list[str], prior: list[str]) -> list[str]:
    merged: list[str] = []
    for hid in [*new, *prior]:
        if hid and hid not in merged:
            merged.append(hid)
    return merged[:2]


def _asks_for_images(text: str) -> bool:
    blob = f" {re.sub(r'[^a-z0-9]+', ' ', text.lower())} "
    compact = blob.replace(" ", "")
    viewing = any(f" {word} " in blob for word in ("show", "see", "list"))
    subject = any(
        f" {word} " in blob or word.replace(" ", "") in compact
        for word in ("screensaver", "screen saver", "wallpaper", "background")
    )
    return viewing and subject


def _already_listed(messages: list[dict[str, Any]]) -> bool:
    for message in messages:
        if message.get("tool_call_id") == "wallpaper_list":
            return True
        for call in message.get("tool_calls") or []:
            if (call.get("function") or {}).get("name") == "wallpaper_list":
                return True
    return False


def _list_images(text: str, cfg: Config, ui: ChatUi | None, messages: list[dict[str, Any]]) -> None:
    """Show the gallery even when the model only asks which image to set."""
    if not _asks_for_images(text) or _already_listed(messages):
        return
    if ui:
        ui.tool_start("wallpaper_list", "{}")
    result = call_tool("wallpaper_list", "{}", cfg)
    if ui:
        ui.tool_done("wallpaper_list", result)
    messages.append(
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "wallpaper_list",
                    "type": "function",
                    "function": {"name": "wallpaper_list", "arguments": "{}"},
                }
            ],
        }
    )
    messages.append({"role": "tool", "tool_call_id": "wallpaper_list", "content": _model_tool_text("wallpaper_list", result)})


def _remember(ui: ChatUi, messages: list[dict[str, Any]], heads: list[str]) -> None:
    stored = [message for message in messages if message.get("role") != "system"][-24:]
    while stored and stored[0].get("role") == "tool":
        stored.pop(0)
    ui.model_messages = stored
    ui.model_heads = list(heads)


def run_turn(
    text: str,
    cfg: Config,
    ui: ChatUi | None = None,
    *,
    continue_conversation: bool = False,
) -> str:
    text = text.strip()
    if not text:
        return "I did not hear anything."
    if ui:
        ui.user(text, keep_display=continue_conversation)
    if not health(cfg.llm):
        msg = (
            "The local model is not running. Start it with: "
            "systemctl --user start agavai-llm"
        )
        if ui:
            ui.error(msg)
        return msg
    prior_messages = list(ui.model_messages) if ui and continue_conversation else []
    prior_heads = list(ui.model_heads) if ui and continue_conversation else []
    head_ids = _merge_heads(select_head_ids(text, cfg), prior_heads)
    selected = schemas_for_heads(head_ids, limit=cfg.router.max_tools)
    selected_names = {item["function"]["name"] for item in selected}
    messages: list[dict[str, Any]] = [
        {
            "role": "system",
            "content": SYSTEM.format(now=datetime.now().strftime("%A, %Y-%m-%d %H:%M")),
        },
        *prior_messages,
        {"role": "user", "content": text},
    ]
    if "wallpaper_list" in selected_names and _asking_for_images(text):
        listed = call_tool("wallpaper_list", "{}", cfg)
        if ui:
            ui.tool_start("wallpaper_list", "{}")
            ui.tool_done("wallpaper_list", listed)
        messages.append(
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "wallpaper_list",
                        "type": "function",
                        "function": {"name": "wallpaper_list", "arguments": "{}"},
                    }
                ],
            }
        )
        messages.append({"role": "tool", "tool_call_id": "wallpaper_list", "content": _model_tool_text("wallpaper_list", listed)})
    retried = False
    try:
        for _ in range(cfg.llm.max_tool_rounds):
            if ui and ui.cancelled():
                return ""
            message = chat(cfg.llm, messages, tools=selected)
            calls = parse_tool_calls(message)
            content = (message.get("content") or "").strip()
            if not calls:
                _list_images(text, cfg, ui, messages)
                reply = read_aloud(_strip_think(content) or "Done.", ui.data.get("display") if ui else None)
                messages.append({"role": "assistant", "content": reply})
                if ui:
                    _remember(ui, messages, head_ids)
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
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.get("id") or name,
                        "content": _model_tool_text(name, result),
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
