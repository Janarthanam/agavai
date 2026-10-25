from __future__ import annotations

import json
from unittest.mock import Mock, patch

from behave import given, then, when

from agavai.config import Config, LlmConfig
from agavai.heads import schemas_for_heads
from agavai.router import select_head_ids
from agavai.tools import wallpaper_set


@given("the keyword router")
def step_kw(context):
    context.cfg = Config()
    context.cfg.router.backend = "keyword"
    context.cfg.router.fallback = "keyword"


@given("router backend jev with no api key")
def step_no_key(context):
    context.cfg = Config()
    context.cfg.router.backend = "jev"
    context.cfg.router.fallback = "keyword"
    context.key_patch = patch.dict("os.environ", {"OPENROUTER_API_KEY": ""}, clear=False)
    context.key_patch.start()
    context.add_cleanup(context.key_patch.stop)


@given('a Jev response choosing head "{head}"')
def step_jev(context, head):
    context.cfg = Config()
    context.cfg.router.backend = "jev"
    payload = {
        "answers": {
            "head": {"type": "choice", "choice": head},
        }
    }
    body = json.dumps(payload).encode()

    class Resp:
        def read(self):
            return body

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    context.urlopen = patch("agavai.router.urllib.request.urlopen", return_value=Resp())
    context.urlopen.start()
    context.add_cleanup(context.urlopen.stop)
    context.key = patch("agavai.router._api_key", return_value="sk-test")
    context.key.start()
    context.add_cleanup(context.key.stop)


@when('I route the utterance "{text}"')
def step_route(context, text):
    context.heads = select_head_ids(text, context.cfg)
    context.schemas = schemas_for_heads(context.heads, limit=context.cfg.router.max_tools)
    context.names = [s["function"]["name"] for s in context.schemas]


@when('I set wallpaper to "{name}"')
def step_wp(context, name):
    context.tool_result = wallpaper_set({"name": name}, Config())


@then('the selected heads should include "{head}"')
def step_head_in(context, head):
    assert head in context.heads, context.heads


@then('the selected tool names should include "{name}"')
def step_name_in(context, name):
    assert name in context.names, context.names


@then('the selected tool names should not include "{name}"')
def step_name_out(context, name):
    assert name not in context.names, context.names


@then("there should be {n:d} selected heads")
def step_n(context, n):
    assert len(context.heads) == n, context.heads


@given('a Needle router returning "{outcome}" with "{fallback}" fallback')
def step_needle_router(context, outcome, fallback):
    context.cfg = Config()
    context.cfg.router.backend = "needle-cactus"
    context.cfg.router.fallback = fallback
    context.cfg.router.needle = LlmConfig(backend="needle-cactus", model_id="needle3")
    context.needle_router = Mock()
    names = {"volume": ["set_volume"], "agents": ["list_agents"],
             "multiple": ["set_volume", "mute_microphone", "launch", "list_agents"],
             "unknown": ["run_shell"], "empty": []}
    if outcome == "error":
        context.needle_router.respond.side_effect = TimeoutError("worker timed out")
    elif outcome == "malformed":
        context.needle_router.respond.return_value = {"tool_calls": ["bad call"]}
    else:
        context.needle_router.respond.return_value = {"tool_calls": [
            {"function": {"name": name, "arguments": '{"percent": 1}'}} for name in names[outcome]
        ]}
    factory = patch("agavai.router.create_brain", return_value=context.needle_router)
    factory.start()
    context.add_cleanup(factory.stop)


@then('Needle was offered every registered tool for selection only')
def step_needle_offers(context):
    from agavai.heads import TOOL_TO_HEAD
    from agavai.tools import OPENAPI_TOOLS
    context.needle_router.respond.assert_called_once()
    messages, tools = context.needle_router.respond.call_args.args
    assert tools == OPENAPI_TOOLS
    assert messages[-1]["content"] == "increase playback level"
    assert set(TOOL_TO_HEAD) == {tool["function"]["name"] for tool in OPENAPI_TOOLS}
