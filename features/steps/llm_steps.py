from __future__ import annotations

import json

from behave import then, when

from oma_voice.llm import parse_tool_calls


@when('I parse an OpenAI tool call named "{name}"')
def step_openai(context, name):
    context.calls = parse_tool_calls(
        {
            "tool_calls": [
                {
                    "id": "1",
                    "function": {"name": name, "arguments": '{"target":"browser"}'},
                }
            ]
        }
    )


@when('I parse Qwen XML for tool "{name}" with workspace {n:d}')
def step_xml(context, name, n):
    context.calls = parse_tool_calls(
        {
            "content": f'<tool_call>\n{{"name": "{name}", "arguments": {{"workspace": {n}}}}}\n</tool_call>'
        }
    )


@when('I parse plain assistant text "{text}"')
def step_plain(context, text):
    context.calls = parse_tool_calls({"content": text})


@then('the first parsed tool name should be "{name}"')
def step_name(context, name):
    assert context.calls[0]["function"]["name"] == name


@then("there should be {n:d} parsed tool call")
def step_n1(context, n):
    assert len(context.calls) == n


@then("there should be {n:d} parsed tool calls")
def step_n(context, n):
    assert len(context.calls) == n


@then("the first parsed tool workspace should be {n:d}")
def step_ws(context, n):
    args = json.loads(context.calls[0]["function"]["arguments"])
    assert args["workspace"] == n
