from __future__ import annotations

import json
from unittest.mock import patch

from behave import given, then, when

from agavai.config import Config
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
