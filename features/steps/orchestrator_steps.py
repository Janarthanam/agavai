from __future__ import annotations
from agavai.harness.context import ContextStore

import json
from copy import deepcopy
from unittest.mock import patch

from features.support.tool_replay import tool_patch
from behave import given, then, when

from agavai.config import Config
from agavai.llm import LlmError
from agavai.harness.engine import CHAT_SYSTEM, CONTEXT_SYSTEM, SYSTEM, _strip_think, run_turn, wants_followup
from agavai.ui import cancel_ui


@given("llama-server is down")
def step_down(context):
    context.health_patch = patch("agavai.harness.engine.health", return_value=False)
    context.health_patch.start()
    context.add_cleanup(context.health_patch.stop)


@given('llama-server will call "{tool}" then reply "{reply}"')
def step_script(context, tool, reply):
    calls = [
        {
            "tool_calls": [
                {
                    "id": "c1",
                    "function": {"name": tool, "arguments": '{"target":"browser"}'},
                }
            ],
            "content": "",
        },
        {"content": reply, "tool_calls": []},
    ]

    def fake_chat(_cfg, _messages, tools=None):
        return calls.pop(0)

    context.health_patch = patch("agavai.harness.engine.health", return_value=True)
    context.chat_patch = patch("agavai.harness.engine.chat", side_effect=fake_chat)
    context.tool_patch = tool_patch(
        "agavai.harness.engine.call_tool", return_value="launched browser"
    )
    context.health_patch.start()
    context.chat_patch.start()
    context.tool_mock = context.tool_patch.start()
    context.add_cleanup(context.health_patch.stop)
    context.add_cleanup(context.chat_patch.stop)
    context.add_cleanup(context.tool_patch.stop)


@given("the router selects no heads")
def step_router_none(context):
    context.router_patch = patch("agavai.harness.engine.select_head_ids", return_value=[])
    context.router_patch.start()
    context.add_cleanup(context.router_patch.stop)


@given('llama-server calls "{first}" then "{second}" then replies "{reply}"')
def step_script_retry(context, first, second, reply):
    scripted = [
        {
            "tool_calls": [{"id": "c1", "function": {"name": first, "arguments": "{}"}}],
            "content": "",
        },
        {
            "tool_calls": [{"id": "c2", "function": {"name": second, "arguments": "{}"}}],
            "content": "",
        },
        {"content": reply, "tool_calls": []},
    ]
    context.offered: list[set[str]] = []
    context.prompts = []

    def fake_chat(_cfg, messages, tools=None):
        context.offered.append({t["function"]["name"] for t in (tools or [])})
        context.prompts.append(messages[0]["content"])
        return scripted.pop(0)

    context.health_patch = patch("agavai.harness.engine.health", return_value=True)
    context.chat_patch = patch("agavai.harness.engine.chat", side_effect=fake_chat)
    context.tool_patch = tool_patch("agavai.harness.engine.call_tool", return_value="ok")
    context.health_patch.start()
    context.chat_patch.start()
    context.tool_mock = context.tool_patch.start()
    context.add_cleanup(context.health_patch.stop)
    context.add_cleanup(context.chat_patch.stop)
    context.add_cleanup(context.tool_patch.stop)


@given('llama-server calls "{tool}" with a notes folder, image, and file, then reads their paths')
def step_named_listing(context, tool):
    folder = context.runtime_dir / "Notes"
    folder.mkdir()
    image = context.runtime_dir / "ship-at-sea.jpg"
    image.write_bytes(b"")
    notes = context.runtime_dir / "notes.md"
    notes.write_text("hello", encoding="utf-8")
    context.notes_path = str(notes)
    payload = json.dumps([
        {"path": str(folder)},
        {"name": "ship at sea", "path": str(image)},
        str(notes),
    ])
    reply = f"Here are {folder}/, {image}, and {notes}."
    scripted = [
        {"tool_calls": [{"id": "c1", "function": {"name": tool, "arguments": '{"query":"notes"}'}}], "content": ""},
        {"content": reply, "tool_calls": []},
    ]

    def fake_chat(_cfg, messages, tools=None):
        context.seen_messages = messages
        return scripted.pop(0)

    context.health_patch = patch("agavai.harness.engine.health", return_value=True)
    context.router_patch = patch("agavai.harness.engine.select_head_ids", return_value=["files"])
    context.chat_patch = patch("agavai.harness.engine.chat", side_effect=fake_chat)
    context.tool_patch = tool_patch("agavai.harness.engine.call_tool", return_value=payload)
    context.health_patch.start()
    context.router_patch.start()
    context.chat_patch.start()
    context.tool_mock = context.tool_patch.start()
    context.add_cleanup(context.health_patch.stop)
    context.add_cleanup(context.router_patch.stop)
    context.add_cleanup(context.chat_patch.stop)
    context.add_cleanup(context.tool_patch.stop)


@given("wallpaper listing returns a ship image")
def step_ship_listing(context):
    payload = '[{"name":"Ship At Sea","path":"/tmp/ship-at-sea.jpg"}]'

    def fake(name, raw, cfg):
        return payload

    context.tool_patch = tool_patch("agavai.harness.engine.call_tool", side_effect=fake)
    context.tool_mock = context.tool_patch.start()
    context.add_cleanup(context.tool_patch.stop)


@given("the chat UI uses the keyword router")
def step_keyword_ui(context):
    context.cfg.router.backend = "keyword"
    context.cfg.router.fallback = "keyword"


@given('llama-server replies "{reply}"')
def step_reply_only(context, reply):
    context.context_requests = []
    context.action_requests = []
    context.prompts = []

    def fake_chat(cfg, messages, tools=None):
        if messages[0]["content"] == CONTEXT_SYSTEM:
            assert not tools
            assert cfg.temperature == 0 and cfg.max_tokens == 16
            context.context_requests.append({**json.loads(messages[-1]["content"]), "conversation": messages[1:-1]})
            if getattr(context, "dismiss_during_context", False):
                cancel_ui(context.cfg)
            if getattr(context, "context_error", None):
                raise context.context_error
            return {"content": context.context_response, "tool_calls": getattr(context, "context_tool_calls", [])}
        context.action_requests.append(deepcopy(context.ui.data))
        context.seen_messages = messages
        context.prompts.append(messages[0]["content"])
        context.model_tools = {item["function"]["name"] for item in (tools or [])}
        return {"content": reply, "tool_calls": []}

    context.health_patch = patch("agavai.harness.engine.health", return_value=True)
    context.chat_patch = patch("agavai.harness.engine.chat", side_effect=fake_chat)
    context.health_patch.start()
    context.chat_patch.start()
    context.add_cleanup(context.health_patch.stop)
    context.add_cleanup(context.chat_patch.stop)


@given('the context response is "{response}"')
def step_context_response(context, response):
    context.context_response = response


@given("the context response is empty")
def step_context_empty(context):
    step_context_response(context, "")


@given("the context response contains a tool call")
def step_context_tool_call(context):
    context.context_response = "follow_up"
    context.context_tool_calls = [{"id": "c1", "function": {"name": "wallpaper_set", "arguments": '{"name":"Ship At Sea"}'}}]


@given('the context model fails with "{error}"')
def step_context_error(context, error):
    context.context_error = LlmError(error)


@given("the session is dismissed during the context decision")
def step_context_dismiss(context):
    context.dismiss_during_context = True


@when('I run a turn with text "{text}"')
def step_turn(context, text):
    context.turn_result = run_turn(text, Config(), context=ContextStore())
    context.reply = context.turn_result.speech_text or ""


@when('I run a turn with text "{text}" on the chat UI')
def step_turn_ui(context, text):
    context.before_turn = deepcopy(context.ui.data)
    context.turn_result = run_turn(text, context.cfg, context.harness.output, context=context.harness.context)
    context.reply = context.turn_result.speech_text or ""


@when('I continue the turn with text "{text}"')
def step_continue(context, text):
    context.before_turn = deepcopy(context.ui.data)
    context.before_messages = deepcopy(context.harness.context.messages)
    context.before_heads = list(context.harness.context.heads)
    context.context_requests = []
    context.action_requests = []
    context.turn_result = run_turn(text, context.cfg, context.harness.output, context=context.harness.context, continue_conversation=True)
    context.reply = context.turn_result.speech_text or ""


@then('the spoken reply should be "{text}"')
def step_reply_eq(context, text):
    assert context.reply == text, context.reply


@then("no spoken reply is produced")
def step_no_reply(context):
    assert context.reply == "", context.reply


@then('the spoken reply should contain "{text}"')
def step_reply_in(context, text):
    assert text in context.reply, context.reply


@then('the tool "{name}" should have been called once')
def step_called(context, name):
    context.tool_mock.assert_called_once()
    assert context.tool_mock.call_args[0][0] == name


@then('the model should have been offered "{name}" only after the retry')
def step_offered(context, name):
    offered = context.offered
    assert offered, offered
    assert name not in offered[0], offered
    assert any(name in names for names in offered[1:]), offered


@then('stripping think tags from "{raw}" yields "{want}"')
def step_strip(context, raw, want):
    assert _strip_think(raw) == want


@then('a follow-up is expected for "{text}"')
def step_follow_yes(context, text):
    assert wants_followup(text), text


@then('a follow-up is not expected for "{text}"')
def step_follow_no(context, text):
    assert not wants_followup(text), text


@then("the model tool text should not contain the notes path")
def step_no_path(context):
    tool_text = " ".join(
        str(message.get("content") or "")
        for message in context.seen_messages
        if message.get("role") == "tool"
    )
    assert context.notes_path not in tool_text, tool_text
    assert '"kind": "folder"' in tool_text, tool_text
    assert "ship at sea" in tool_text, tool_text
    assert '"name": "notes"' in tool_text, tool_text
    assert "notes.md" not in tool_text, tool_text


@then('the model messages included "{text}"')
def step_messages(context, text):
    blob = " ".join(str(message.get("content") or "") for message in context.seen_messages)
    assert text in blob, context.seen_messages


@then('the follow-up model was offered "{name}"')
def step_offered_now(context, name):
    assert name in context.model_tools, context.model_tools


@then('the model messages excluded "{text}"')
def step_messages_excluded(context, text):
    assert text not in json.dumps(context.seen_messages), context.seen_messages
    assert text not in json.dumps(context.harness.context.messages), context.harness.context.messages


@then('the new answer uses head "{head}"')
def step_new_head(context, head):
    assert context.harness.context.heads == ([] if head == "none" else [head]), context.harness.context.heads
    if head != "wallpaper":
        assert "wallpaper_set" not in context.model_tools, context.model_tools


@then("no context decision was requested")
def step_no_context(context):
    assert not context.context_requests, context.context_requests


@then("no action answer was requested")
def step_no_action_answer(context):
    assert not context.action_requests, context.action_requests


@then('the context decision used the earlier results and "{request}"')
def step_context_input(context, request):
    assert len(context.context_requests) == 1, context.context_requests
    decision = context.context_requests[0]
    assert decision["request"] == request, decision
    assert decision["conversation"] == context.before_messages, decision
    assert "Ship At Sea" in json.dumps(decision["conversation"]), decision
    assert context.cfg.llm.max_tokens == 512 and context.cfg.llm.temperature == 0.2


@then("the new answer started with a blank conversation canvas")
def step_blank_answer(context):
    assert len(context.action_requests) == 1, context.action_requests
    snapshot = context.action_requests[0]
    for key in ("display", "answer_html", "completion", "error"):
        assert key not in snapshot, snapshot
    assert len(snapshot["turns"]) == 1, snapshot["turns"]
    assert snapshot["turns"][0]["tools"] == [], snapshot["turns"]
    assert snapshot["turns"][0]["assistant"] == "", snapshot["turns"]
    assert snapshot["transcript"]["final"]
    assert snapshot["phase"] == "thinking"


@then("the earlier canvas and conversation were retained")
def step_retained_conversation(context):
    snapshot = context.action_requests[0]
    assert snapshot["display"] == context.before_turn["display"]
    assert snapshot["turns"][:-1] == context.before_turn["turns"]
    assert context.seen_messages[1:-1] == context.before_messages, context.seen_messages
    assert all(message.get("content") != CONTEXT_SYSTEM for message in context.harness.context.messages)


@then("the earlier canvas and model history were retained")
def step_retained_history(context):
    snapshot = json.loads((context.runtime_dir / "ui.json").read_text())
    assert snapshot["display"] == context.before_turn["display"]
    assert context.harness.context.messages == context.before_messages
    assert context.harness.context.heads == context.before_heads


@then("the listening session identity was retained")
def step_same_session(context):
    snapshot = json.loads((context.runtime_dir / "ui.json").read_text())
    assert snapshot["session_id"] == context.before_turn["session_id"]


@then("the conversation snapshot was unchanged")
def step_same_snapshot(context):
    assert context.ui.data == context.before_turn


@given("llama-server shows this answer")
def step_show_answer(context):
    context.model_rounds = 0
    context.prompts = []
    call = {"id": "a1", "function": {"name": "show_answer", "arguments": context.text}}

    def fake_chat(_cfg, messages, tools=None):
        context.model_rounds += 1
        context.prompts.append(messages[0]["content"])
        context.model_tools = {item["function"]["name"] for item in (tools or [])}
        return {"content": "", "tool_calls": [call]} if context.model_rounds == 1 else {"content": "Here are the planets in a second round.", "tool_calls": []}

    context.health_patch = patch("agavai.harness.engine.health", return_value=True)
    context.chat_patch = patch("agavai.harness.engine.chat", side_effect=fake_chat)
    context.health_patch.start()
    context.chat_patch.start()
    context.add_cleanup(context.health_patch.stop)
    context.add_cleanup(context.chat_patch.stop)


@then('the canvas shows the answer "{title}" with "{html}"')
def step_canvas_answer(context, title, html):
    display = context.ui.data.get("display") or {}
    assert display.get("kind") == "answer" and display.get("title") == title, display
    assert html in display.get("html", ""), display


@then("the canvas is empty")
def step_canvas_empty(context):
    assert "display" not in context.ui.data, context.ui.data.get("display")


@then('the model was asked once and offered only "{name}"')
def step_one_round(context, name):
    assert context.model_rounds == 1, context.model_rounds
    assert context.model_tools == {name}, context.model_tools


@then('the model was offered "{name}"')
def step_model_offered(context, name):
    assert name in context.model_tools, context.model_tools


@then('the model was not offered "{name}"')
def step_model_not_offered(context, name):
    assert name not in context.model_tools, context.model_tools


@then("the remembered conversation keeps the shown Markdown")
def step_remembered_answer(context):
    calls = [call for message in context.harness.context.messages for call in message.get("tool_calls") or []]
    assert any("Venus" in call["function"]["arguments"] for call in calls), context.harness.context.messages


_INSTRUCTIONS = {"chat": CHAT_SYSTEM, "desktop": SYSTEM}


def _instruction_kind(prompt):
    kinds = [kind for kind, template in _INSTRUCTIONS.items() if prompt.startswith(template.split("{now}")[0])]
    assert len(kinds) == 1, prompt
    return kinds[0]


@then("the model was given the {kinds}")
def step_model_instructions(context, kinds):
    """Kinds read like 'chat instructions, then the desktop instructions'; repeated rounds count once."""
    expected = [kind.removesuffix(" instructions") for kind in kinds.split(", then the ")]
    given = []
    for prompt in context.prompts:
        kind = _instruction_kind(prompt)
        if not given or given[-1] != kind:
            given.append(kind)
    assert given == expected, given
