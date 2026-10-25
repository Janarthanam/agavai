from __future__ import annotations

import json
import logging
import re
import time
import uuid
from dataclasses import replace
from datetime import datetime
from typing import Any

from agavai import journal
from agavai.config import Config
from agavai.brain import create_brain
from agavai.llm import LlmError, chat, health, parse_tool_calls
from agavai.heads import head_for_tool, schemas_for_heads
from agavai.router import fallback_head_ids, routes_itself, select_head_ids
from agavai.canvas import answer_block, model_view, read_aloud
from agavai.tools import DISPATCH, OPENAPI_TOOLS, execute_tool as call_tool
from agavai.ui import ChatUi
from agavai.harness.context import ContextStore, PendingAction
from agavai.harness.inference import TurnCancelled
from agavai.harness.routing import CONTEXT_SYSTEM, continues_conversation, decide
from agavai.harness.execution import validate_call as _validate_call
from agavai.harness.source_turn import language_tier, run_source_turn

log = logging.getLogger(__name__)

SYSTEM = """You are Agavai, a local Omarchy Linux voice assistant.
Your final message is spoken aloud automatically. Always answer in one or two short spoken sentences. No markdown, no code fences, no lists.
Never say you cannot speak, talk, generate voice, or say a word. If asked to say something, say it.
Answer general knowledge, reasoning and conversational questions directly; these do not require tools. Missing tools limit desktop actions, not your ability to answer questions.
Desktop actions exist only through the tools you were given this turn. Never claim you launched an app, changed a setting, or clicked something unless a tool result says so.
Do not call remote models or coding agents. Do not ask for a shell.
If a needed desktop action is not among the tools you were given, say you cannot do that action — still in a spoken sentence.
When a desktop action needs the user's confirmation, call request_confirmation alone with the exact tool name, fully resolved arguments, and one short confirmation question. Do not execute the action yet or ask for confirmation only in prose. Use this only when the user asks to confirm first or you need their permission; ordinary direct commands still execute normally. If request_confirmation is unavailable, explain that you cannot prepare a confirmation in this turn. Do not prepare an action whose arguments still need a choice or clarification.
When the user asks to see wallpaper, background, or screensaver images, call wallpaper_list before you answer so the pictures appear. Then ask which image they want, in one short question.
Later messages are the same person continuing. Use the earlier list and call wallpaper_set with the image they name. Do not ask them to pick an image that was not listed.
When a tool succeeds, say exactly what finished in one sentence, naming the wallpaper, reminder, or other change.
File, folder, image, and video results give you a kind and a readable name. When listing results, give a brief summary and point to the canvas instead of reading every filename. Refer to an individual item by its readable name. Never speak a filesystem path or file extension.
Current local time: {now}
"""

# Turns offered only show_answer get their own prompt. With the desktop lines
# above, Qwen3-4B showed 1 or 2 of 5 list answers, and it showed fewer when the
# rule came after the short-answer rule.
CHAT_SYSTEM = """You are Agavai, a local Omarchy Linux voice assistant.
Your final message is spoken aloud automatically.
Use show_answer for any list, steps, or several items. Answer anything else in one or two short spoken sentences, with no markdown.
Never say you cannot speak, talk, generate voice, or say a word. If asked to say something, say it.
You have no desktop tools this turn. Never claim you launched an app, changed a setting, or clicked something.
Do not call remote models or coding agents. Do not ask for a shell.
Current local time: {now}
"""

_FOLLOWUP = re.compile(r"\b(you want|which|tell me|let me know)\b", re.IGNORECASE)

_RESULT_LIMIT = 500
ESCALATE = {"type": "function", "function": {
    "name": "escalate_to_larger_model",
    "description": "Use when you cannot answer or handle the request. Call alone before taking actions.",
    "parameters": {"type": "object", "properties": {"reason": {"type": "string"}}, "required": ["reason"]},
}}



def control_command(text: str) -> str | None:
    """Recognize only isolated controls in an already committed utterance."""
    word = text.strip().rstrip(".!?…").rstrip().casefold()
    return word if word in {"yes", "no", "continue", "agavai"} else None


_SHOW_ANSWER = {
    "type": "function",
    "function": {
        "name": "show_answer",
        "description": "Show an answer that is easier to read than hear, such as a list or steps, on screen, and speak a one-sentence summary. Not for short answers.",
        "parameters": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Short heading for the answer."},
                "markdown": {"type": "string", "description": "The full answer. Use '- ' bullets or '1. ' numbered lines, short paragraphs, and '## ' headings."},
                "summary": {"type": "string", "description": "One short spoken sentence saying what is on screen."},
            },
            "required": ["title", "markdown", "summary"],
            "additionalProperties": False,
        },
    },
}


def _turn_tools(
    head_ids: list[str], cfg: Config, ui: ChatUi | None, *, all_tools: bool = False,
) -> list[dict[str, Any]]:
    can_confirm = ui is not None and (all_tools or cfg.router.max_tools > 1)
    if all_tools:
        selected = list(OPENAPI_TOOLS)
    else:
        selected = schemas_for_heads(head_ids, limit=cfg.router.max_tools - int(can_confirm))
    # Questions with no desktop tools can still put a structured answer on the canvas.
    if ui is not None and not selected and cfg.router.max_tools > 0:
        return [_SHOW_ANSWER]
    if can_confirm and selected:
        selected.append({
            "type": "function",
            "function": {
                "name": "request_confirmation",
                "description": "Prepare one action for Yes or Continue; do not execute it. Call this alone when confirmation is needed.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "enum": [item["function"]["name"] for item in selected]},
                        "arguments": {"type": "object", "description": "Fully resolved arguments for that tool."},
                        "question": {"type": "string", "description": "One short question naming the action to confirm."},
                    },
                    "required": ["name", "arguments", "question"],
                    "additionalProperties": False,
                },
            },
        })
    return selected


def _system_message(selected_names: set[str]) -> dict[str, str]:
    prompt = CHAT_SYSTEM if selected_names == {"show_answer"} else SYSTEM
    return {"role": "system", "content": prompt.format(now=datetime.now().strftime("%A, %Y-%m-%d %H:%M"))}


def _call_arguments(call: dict[str, Any], label: str) -> dict[str, Any]:
    raw = (call.get("function") or {}).get("arguments")
    try:
        arguments = json.loads(raw) if isinstance(raw, str) else raw
    except json.JSONDecodeError as exc:
        raise LlmError(f"Invalid {label} arguments JSON.") from exc
    if not isinstance(arguments, dict):
        raise LlmError(f"{label.capitalize()} arguments must be an object.")
    return arguments


def _prepare_confirmation(call: dict[str, Any], selected_names: set[str], ui: ChatUi, context: ContextStore) -> str:
    proposal = _call_arguments(call, "confirmation")
    name = proposal.get("name")
    arguments = proposal.get("arguments")
    question = proposal.get("question")
    if not isinstance(name, str) or name not in selected_names or name not in DISPATCH:
        raise LlmError("That action is not available for confirmation in this turn.")
    if not isinstance(arguments, dict) or not isinstance(question, str) or not question.strip():
        raise LlmError("Confirmation needs resolved arguments and a question.")
    _validate_call({"function": {"name": name, "arguments": json.dumps(arguments)}}, OPENAPI_TOOLS)
    context.pending_action = PendingAction(context.session_id, name, arguments)
    context.turn_status = "awaiting_confirmation"
    return read_aloud(question, ui.data.get("display"))


def _show_answer(call: dict[str, Any], ui: ChatUi) -> str:
    """Publish the model's structured answer on the canvas; its summary is the spoken reply."""
    answer = _call_arguments(call, "on-screen answer")
    title, markdown, summary = (answer.get(key) for key in ("title", "markdown", "summary"))
    if not all(isinstance(value, str) and value.strip() for value in (title, markdown, summary)):
        raise LlmError("An on-screen answer needs a title, Markdown, and a spoken summary.")
    ui.display(answer_block(title.strip(), markdown.strip()))
    return read_aloud(summary, None)


def _finish_with_local_call(
    calls: list[dict[str, Any]], note: str, reply: str,
    messages: list[dict[str, Any]], ui: ChatUi, head_ids: list[str], context: ContextStore,
) -> str:
    """End the turn on a call handled here, without another model round."""
    messages.append({"role": "assistant", "content": None, "tool_calls": calls})
    messages.append({"role": "tool", "tool_call_id": calls[0].get("id") or calls[0]["function"]["name"], "content": note})
    messages.append({"role": "assistant", "content": reply})
    _remember(context, messages, head_ids)
    ui.assistant(reply)
    return reply


def _handle_control(text: str, cfg: Config, ui: ChatUi, *, continue_conversation: bool, context: ContextStore) -> str | None:
    command = control_command(text)
    if command == "agavai":
        context.new_task()
        context.turn_status = "listening"
        ui.clear_conversation()
        ui.continue_listening()
        return ""
    pending = context.pending_action if continue_conversation else None
    if pending and pending.session_id != context.session_id:
        pending = None
    if command not in {"yes", "no"} and not (command == "continue" and pending):
        return None
    log.info("turn control=%s pending=%s", command, pending.name if pending else "none")
    messages = list(context.messages) if continue_conversation else []
    heads = list(context.heads) if messages else []
    context.pending_action = None
    ui.user(text, keep_display=continue_conversation)
    ui.pipeline_event("Control", f"{command} · model and router bypassed")
    messages.append({"role": "user", "content": text})
    if command == "no":
        reply = "Cancelled the pending action." if pending else "There is no pending action to cancel."
    elif not pending:
        reply = "What would you like me to confirm?"
    else:
        call = {
            "id": uuid.uuid4().hex,
            "type": "function",
            "function": {"name": pending.name, "arguments": json.dumps(pending.arguments, ensure_ascii=False)},
        }
        messages.append({"role": "assistant", "content": None, "tool_calls": [call]})
        result = _execute_tool_call(call, cfg, ui, messages, context)
        if result is None:
            return ""
        reply = read_aloud(result, ui.data.get("display"))
        if not reply:
            reply = "The action returned no result."
        elif reply.startswith(("{", "[")) or len(reply) > 280 or len(re.split(r"(?<=[.!?])\s+", reply)) > 2:
            reply = "The action returned more detail than I can read aloud. I have kept its result."
    messages.append({"role": "assistant", "content": reply})
    _remember(context, messages, heads)
    ui.assistant(reply)
    return reply




def _model_tool_text(name: str, result: str) -> str:
    text = model_view(name, result)
    if len(text) > _RESULT_LIMIT:
        text = text[: _RESULT_LIMIT - 1] + "…"
    return text


def _execute_tool_call(
    call: dict[str, Any], cfg: Config, ui: ChatUi | None, messages: list[dict[str, Any]], context: ContextStore,
) -> str | None:
    fn = call.get("function") or {}
    name = fn.get("name") or ""
    raw_args = fn.get("arguments") or "{}"
    if ui:
        if ui.cancelled():
            return None
        ui.tool_start(name, raw_args)
        if ui.cancelled():
            return None
    outcome = context.execution.execute(call, cfg, call_tool, lambda: context.should_cancel() or bool(ui and ui.cancelled()), task_id=context.task_id, request_id=context.request_id)
    if outcome is None:
        return None
    result = outcome.text
    if outcome.status != "ok":
        context.turn_status = "unknown" if outcome.status == "unknown" else "failed"
    if ui:
        if ui.cancelled():
            return None
        ui.tool_done(name, result, status=outcome.status)
    model_text = _model_tool_text(name, result)
    if outcome.status == "unknown":
        model_text = "Outcome unknown. Do not automatically retry this action. " + model_text
    elif outcome.status == "error":
        model_text = "Action failed. " + model_text
    messages.append({
        "role": "tool",
        "tool_call_id": call.get("id") or name,
        "content": model_text,
    })
    return result


def wants_followup(reply: str) -> bool:
    """True when the spoken line is waiting for the user's choice."""
    text = " ".join(str(reply).split())
    if text.endswith("?"):
        return True
    return len(text) >= 12 and _FOLLOWUP.search(text) is not None




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


def _list_images(text: str, cfg: Config, ui: ChatUi | None, messages: list[dict[str, Any]], context: ContextStore) -> None:
    if not _asks_for_images(text) or _already_listed(messages):
        return
    call = {"id": "wallpaper_list", "type": "function",
            "function": {"name": "wallpaper_list", "arguments": "{}"}}
    messages.append({"role": "assistant", "content": None, "tool_calls": [call]})
    _execute_tool_call(call, cfg, ui, messages, context)


def _remember(context: ContextStore, messages: list[dict[str, Any]], heads: list[str]) -> None:
    context.remember(messages, heads)


def _call_key(call):
    fn = call["function"]
    return fn["name"], json.dumps(json.loads(fn.get("arguments") or "{}"), sort_keys=True)


def run_turn(
    text: str,
    cfg: Config,
    ui: ChatUi | None = None,
    *,
    continue_conversation: bool = False,
    context: ContextStore,
) -> str:
    if not text.strip():
        return "I did not hear anything."
    started = time.monotonic()
    log.info("turn start continue=%s", continue_conversation)
    log.debug('turn text "%s"', journal.clip(text))
    context.committed_requests.append(text)
    context.request_id = uuid.uuid4().hex
    context.turn_status = "pending"
    try:
        reply = _run_turn(text, cfg, ui, continue_conversation=continue_conversation, context=context)
    except TurnCancelled:
        context.pending_action = None
        context.turn_status = "cancelled"
        log.info("turn cancelled; late inference has no execution authority")
        if ui:
            ui.task_state(context.task_id, context.request_id, context.turn_status)
        return ""
    if context.should_cancel() or (ui and ui.cancelled()):
        context.pending_action = None
        context.turn_status = "cancelled"
    elif context.turn_status == "pending":
        context.turn_status = "answered"
    if ui:
        ui.task_state(context.task_id, context.request_id, context.turn_status)
    log.info("turn done secs=%.2f", time.monotonic() - started)
    log.debug('turn reply "%s"', journal.clip(reply))
    return reply


def _run_turn(text: str, cfg: Config, ui: ChatUi | None, *, continue_conversation: bool, context: ContextStore) -> str:
    text = text.strip()
    command = text.rstrip(".!?…").casefold()
    if command in {"wait", "pause"}:
        context.held = True
        context.turn_status = "held"
        if ui:
            ui.user(text, keep_display=True)
            ui.assistant("Paused. Say resume when you are ready.")
        return "Paused. Say resume when you are ready."
    if command == "resume" and context.held:
        context.held = False
        context.turn_status = "listening"
        if ui:
            ui.user(text, keep_display=True)
            ui.assistant("Ready. Continue your request.")
        return "Ready. Continue your request."
    if context.held and command != "agavai":
        context.turn_status = "held"
        context.draft = " ".join(filter(None, [context.draft, text]))
        if ui:
            ui.partial(context.draft)
        return ""
    if context.draft and command != "agavai":
        text = context.draft + " " + text
        context.draft = ""
    if not text:
        return "I did not hear anything."
    if context.should_cancel() or (ui and ui.cancelled()):
        context.pending_action = None
        return ""
    if ui:
        reply = _handle_control(text, cfg, ui, continue_conversation=continue_conversation, context=context)
        if reply is not None:
            return reply
        # A new committed request replaces any proposal; partials never reach here.
        context.pending_action = None
    if not continue_conversation:
        context.new_task()
    prior_messages = list(context.messages) if continue_conversation else []
    prior_heads = list(context.heads) if prior_messages else []
    if ui:
        ui.user(text, keep_display=bool(prior_messages))
    try:
        cancelled = lambda: context.should_cancel() or bool(ui and ui.cancelled())
        infer = lambda operation: context.inference.call(operation, cancelled)
        decision = decide(text, has_recording=context.source_active)
        if ui:
            ui.pipeline_event("Decision", f"{decision.capability} · {decision.reason}")
        if decision.source:
            if prior_messages and not context.source_active:
                context.new_task()
                if ui:
                    ui.user(text)
            return run_source_turn(text, decision, cfg, ui, context, infer, create_brain, chat, health)
        active_cfg = cfg.small_brain or cfg.llm
        if active_cfg.backend == "needle-cactus" and decision.capability in {"reasoning", "resolve"}:
            tier = language_tier(cfg)
            if tier is None:
                raise LlmError("This request needs language reasoning. Configure a local Qwen brain, or ask for a supported desktop action.")
            active_cfg = tier
            if ui:
                ui.brain(active_cfg, "Decision · language required")
        backend = create_brain(active_cfg, chat=chat, health=health)
        escalated = active_cfg is cfg.large_brain
        rounds = 0
        completed_calls = {}
        selection_changed = False
        # Escalating from a Needle tier that is also the router: that tier's call
        # was the routing attempt, so the next tier must not ask Needle again.
        routing_spent = False
        synthesizing = False

        def escalate(reason):
            nonlocal backend, active_cfg, escalated, rounds, selection_changed, routing_spent
            if escalated or cfg.large_brain is None:
                raise LlmError(reason)
            log.warning("turn escalated from=%s to=%s: %s", active_cfg.model_id, cfg.large_brain.model_id, reason)
            if ui:
                ui.pipeline_event("Fallback", f"{active_cfg.model_id} → {cfg.large_brain.model_id}: {reason}")
            routing_spent = routes_itself(active_cfg, cfg)
            active_cfg = cfg.large_brain
            backend = create_brain(active_cfg, chat=chat, health=health)
            escalated = True
            rounds = 0
            selection_changed = True
            if not infer(backend.ready):
                raise LlmError("The larger model is not running. Run: agavai services sync")

        try:
            if not infer(backend.ready):
                raise LlmError("The local model is not running. Run: agavai services sync")
        except TurnCancelled:
            raise
        except LlmError as exc:
            escalate(str(exc))
        if prior_messages:
            relation_tier = language_tier(cfg) if backend.tool_only else active_cfg
            if relation_tier is None:
                raise LlmError("I need a language model to resolve that follow-up. Say Agavai to start a fresh task.")
            if ui:
                ui.brain(relation_tier, "Context")
            related = continues_conversation(text, prior_messages,
                replace(cfg, llm=relation_tier), context,
                lambda tier, messages, tools: infer(lambda: chat(tier, messages, tools=tools)))
            if cancelled():
                return ""
            if ui:
                ui.pipeline_event("Context", "follow-up" if related else "new task")
            if not related:
                context.new_task()
                prior_messages = []
                prior_heads = []
                if ui:
                    ui.user(text)
                    ui.brain(active_cfg, "Context · new conversation")

        def select_tools():
            if synthesizing or decision.capability == "reasoning":
                return [], _turn_tools([], cfg, ui)
            all_tools = active_cfg.tool_selection == "all" or cfg.router.backend == "none" or routes_itself(active_cfg, cfg)
            if all_tools:
                heads = []
                if ui:
                    detail = "combined with Needle inference" if routes_itself(active_cfg, cfg) else "bypassed · all tools"
                    ui.pipeline_event("Router", detail)
            elif routing_spent:
                heads = _merge_heads(fallback_head_ids(text, cfg), prior_heads)
                if ui:
                    ui.pipeline_event("Router", f"{cfg.router.fallback} fallback after combined Needle · heads: {', '.join(heads) or 'none'}")
            else:
                report = (lambda detail: ui.pipeline_event("Router", detail)) if ui else None
                events = []
                chosen = infer(lambda: select_head_ids(text, cfg, report=events.append))
                if report:
                    for detail in events:
                        report(detail)
                heads = _merge_heads(chosen, prior_heads)
            return heads, _turn_tools(heads, cfg, ui, all_tools=all_tools)

        if decision.capability == "resolve":
            if backend.tool_only:
                raise LlmError("A language model is required to resolve that correction.")
            resolution_messages = context.pack([
                {"role": "system", "content": "Resolve the user's self-correction into one final request. Return JSON with exactly one string field request. Do not call tools or perform actions. If ambiguous return an empty request."},
                *prior_messages,
                {"role": "user", "content": json.dumps({"request": text}, ensure_ascii=False)}], [], active_cfg)
            resolution = infer(lambda: backend.respond(resolution_messages, []))
            try:
                resolved = json.loads(_strip_think(resolution.get("content") or ""))
            except (ValueError, TypeError) as exc:
                raise LlmError("I could not resolve that correction. Please state the complete corrected request.") from exc
            if parse_tool_calls(resolution) or not isinstance(resolved, dict) or not isinstance(resolved.get("request"), str) or not resolved["request"].strip():
                raise LlmError("Please state the complete corrected request before I take any action.")
            text = resolved["request"].strip()
            if ui:
                ui.pipeline_event("Decision", "Resolved final request before tool proposal")
        head_ids, selected = select_tools()
        selection_changed = False
        selected_names = {item["function"]["name"] for item in selected}
        messages: list[dict[str, Any]] = [
            _system_message(selected_names),
            *prior_messages,
            {"role": "user", "content": text},
        ]
        if "wallpaper" in head_ids and "wallpaper_list" in selected_names and _asks_for_images(text):
            _list_images(text, cfg, ui, messages, context)
        retried = False
        for _ in range(active_cfg.max_tool_rounds + (cfg.large_brain.max_tool_rounds + 1 if cfg.large_brain else 0)):
            if cancelled():
                return ""
            if selection_changed:
                head_ids, selected = select_tools()
                selected_names = {item["function"]["name"] for item in selected}
                selection_changed = False
                retried = False
            can_escalate = cfg.large_brain is not None and not escalated
            offered = [*selected, ESCALATE] if can_escalate and not backend.tool_only else selected
            messages[0] = _system_message(selected_names)
            if can_escalate and not backend.tool_only:
                messages[0]["content"] += "\nIf you cannot handle the request, call escalate_to_larger_model alone with a reason."
            if rounds >= active_cfg.max_tool_rounds:
                if not can_escalate:
                    break
                escalate("The model exhausted its tool steps.")
                continue
            rounds += 1
            try:
                if ui:
                    ui.brain(active_cfg, "Brain")
                packed = context.pack(messages, offered, active_cfg)
                if ui and context.compacted_exchanges:
                    ui.pipeline_event("Context budget", f"{context.compacted_exchanges} older exchanges omitted from prompt; source history retained")
                message = infer(lambda: backend.respond(packed, offered))
            except TurnCancelled:
                raise
            except LlmError as exc:
                escalate(str(exc))
                continue
            calls = parse_tool_calls(message)
            content = (message.get("content") or "").strip()
            if cancelled():
                return ""
            escalation_calls = [call for call in calls if (call.get("function") or {}).get("name") == "escalate_to_larger_model"]
            if escalation_calls or message.get("unsupported") or (not calls and not _strip_think(content)):
                if escalation_calls and len(calls) != 1:
                    raise LlmError("Escalation must be requested alone; no action has executed.")
                reason = message.get("unsupported") or "The model could not handle this request."
                if escalation_calls:
                    _validate_call(escalation_calls[0], [ESCALATE])
                    reason = json.loads(escalation_calls[0]["function"]["arguments"])["reason"]
                log.info("brain unsupported model=%s reason=%s tools=%s", active_cfg.model_id, reason,
                         ",".join(tool["function"]["name"] for tool in offered) or "none")
                if not can_escalate:
                    suggestion = "Try asking me to open an app or find a file." if backend.tool_only else "Please try rephrasing it."
                    raise LlmError(f"I could not handle that request. {suggestion}")
                escalate(str(reason))
                messages.append({"role": "system", "content": f"Escalation reason: {reason}. Continue from the recorded history and tool results; do not repeat completed actions."})
                continue
            names = [(call.get("function") or {}).get("name") for call in calls]
            if "request_confirmation" in names:
                if len(calls) != 1 or "request_confirmation" not in selected_names:
                    raise LlmError("A confirmation must be requested alone in an interactive turn.")
                reply = _prepare_confirmation(calls[0], selected_names, ui, context)
                return _finish_with_local_call(calls, "Awaiting user confirmation. No action has executed.", reply, messages, ui, head_ids, context)
            if "show_answer" in names and "show_answer" in selected_names:
                if len(calls) != 1:
                    raise LlmError("An on-screen answer must be shown alone.")
                reply = _show_answer(calls[0], ui)
                return _finish_with_local_call(calls, "Shown on screen.", reply, messages, ui, head_ids, context)
            if not calls:
                if "wallpaper_list" in selected_names and decision.capability == "action" and not synthesizing:
                    _list_images(text, cfg, ui, messages, context)
                reply = read_aloud(_strip_think(content), ui.data.get("display") if ui else None)
                messages.append({"role": "assistant", "content": reply})
                _remember(context, messages, head_ids)
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
            if extra_heads and not retried and decision.capability != "reasoning" and not synthesizing:
                retried = True
                head_ids.extend(extra_heads)
                selected = _turn_tools(head_ids, cfg, ui)
                selected_names = {item["function"]["name"] for item in selected}
                if ui:
                    ui.pipeline_event("Tools", f"Missing-head retry · added: {', '.join(extra_heads)}")
                continue
            for call in calls:
                name = (call.get("function") or {}).get("name") or ""
                if name not in selected_names:
                    raise LlmError(f"The model requested a tool unavailable in this turn: {name}")
                _validate_call(call, selected)
            messages.append(
                {
                    "role": "assistant",
                    "content": content or None,
                    "tool_calls": calls,
                }
            )
            for call in calls:
                key = _call_key(call)
                if key in completed_calls:
                    messages.append({"role": "tool", "tool_call_id": call.get("id"), "content": completed_calls[key]})
                    continue
                result = _execute_tool_call(call, cfg, ui, messages, context)
                if result is None:
                    return ""
                completed_calls[key] = messages[-1]["content"]
            if backend.tool_only:
                results = [completed_calls[_call_key(call)] for call in calls]
                reply = read_aloud(". ".join(results), ui.data.get("display") if ui else None)
                if any(result.startswith(("{", "[")) or len(result) > 280 for result in results):
                    if cfg.large_brain and not escalated and cfg.large_brain.backend == "llama-server":
                        synthesizing = True
                        escalate("The tool result needs language interpretation.")
                        continue
                    reply = "I retrieved the data, but this configuration needs a language model to explain it."
                elif not reply:
                    reply = "The action returned no result."
                messages.append({"role": "assistant", "content": reply})
                _remember(context, messages, head_ids)
                if ui:
                    ui.assistant(reply)
                return reply
        context.turn_status = "incomplete"
        msg = "I ran out of tool steps before finishing."
        log.warning("turn ran out of tool steps after %d rounds", active_cfg.max_tool_rounds)
        if ui:
            ui.error(msg)
        return msg
    except TurnCancelled:
        raise
    except LlmError as exc:
        context.turn_status = "failed"
        log.warning("turn error: %s", exc)
        if ui:
            ui.error(str(exc))
        return str(exc)


def _strip_think(text: str) -> str:
    if "<think>" in text and "</think>" in text:
        pre, _, rest = text.partition("<think>")
        _, _, post = rest.partition("</think>")
        text = (pre + post).strip()
    return text
