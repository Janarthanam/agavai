from __future__ import annotations

import json
from unittest.mock import patch

from behave import then, when

from agavai.config import LlmConfig
from agavai.llm import chat, parse_tool_calls


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


def _send(context, cfg):
    sent = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return False

        def read(self):
            return json.dumps({"choices": [{"message": {"content": "ok"}}]}).encode()

    def fake_urlopen(req, timeout):
        sent.update(json.loads(req.data))
        return Response()

    with patch("agavai.llm.urllib.request.urlopen", side_effect=fake_urlopen):
        chat(cfg, [{"role": "user", "content": "hi"}], tools=[])
    context.sent = sent


@when("I send a chat request with default sampling")
def step_default_sampling(context):
    _send(context, LlmConfig())


@when("I send a chat request with seed {seed:d} and the prompt cache off")
def step_pinned_sampling(context, seed):
    _send(context, LlmConfig(seed=seed, cache_prompt=False))


@then('the request should not contain "{key}"')
def step_absent(context, key):
    assert key not in context.sent, context.sent


@then('the request "{key}" should be {value:d}')
def step_int_value(context, key, value):
    assert context.sent[key] == value, context.sent


@then('the request "{key}" should be false')
def step_false_value(context, key):
    assert context.sent[key] is False, context.sent
