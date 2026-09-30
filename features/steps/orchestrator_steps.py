from __future__ import annotations

from unittest.mock import patch

from behave import given, then, when

from agavai.config import Config
from agavai.orchestrator import _strip_think, run_turn


@given("llama-server is down")
def step_down(context):
    context.health_patch = patch("agavai.orchestrator.health", return_value=False)
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

    context.health_patch = patch("agavai.orchestrator.health", return_value=True)
    context.chat_patch = patch("agavai.orchestrator.chat", side_effect=fake_chat)
    context.tool_patch = patch(
        "agavai.orchestrator.call_tool", return_value="launched browser"
    )
    context.health_patch.start()
    context.chat_patch.start()
    context.tool_mock = context.tool_patch.start()
    context.add_cleanup(context.health_patch.stop)
    context.add_cleanup(context.chat_patch.stop)
    context.add_cleanup(context.tool_patch.stop)


@given("the router selects no heads")
def step_router_none(context):
    context.router_patch = patch("agavai.orchestrator.select_head_ids", return_value=[])
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

    def fake_chat(_cfg, _messages, tools=None):
        context.offered.append({t["function"]["name"] for t in (tools or [])})
        return scripted.pop(0)

    context.health_patch = patch("agavai.orchestrator.health", return_value=True)
    context.chat_patch = patch("agavai.orchestrator.chat", side_effect=fake_chat)
    context.tool_patch = patch("agavai.orchestrator.call_tool", return_value="ok")
    context.health_patch.start()
    context.chat_patch.start()
    context.tool_mock = context.tool_patch.start()
    context.add_cleanup(context.health_patch.stop)
    context.add_cleanup(context.chat_patch.stop)
    context.add_cleanup(context.tool_patch.stop)


@when('I run a turn with text "{text}"')
def step_turn(context, text):
    context.reply = run_turn(text, Config())


@then('the spoken reply should be "{text}"')
def step_reply_eq(context, text):
    assert context.reply == text, context.reply


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
