from __future__ import annotations

from unittest.mock import MagicMock, patch

from behave import given, then, when

from agavai.config import Config
from agavai.tools import (
    bluetooth,
    open_app,
    screenshot,
    send_notification,
    set_brightness,
    set_volume,
    workspace_step,
)


@given("omarchy commands succeed")
def step_ok(context):
    run = MagicMock()
    run.returncode = 0
    run.stdout = "ok"
    run.stderr = ""
    p = patch("agavai.tools._run", return_value=run)
    context.run_mock = p.start()
    context.add_cleanup(p.stop)


@when('I set volume action "{action}"')
def step_vol(context, action):
    context.tool_result = set_volume({"action": action}, Config())


@when('I set brightness action "{action}"')
def step_bright(context, action):
    context.tool_result = set_brightness({"action": action}, Config())


@when('I set bluetooth action "{action}"')
def step_bt(context, action):
    context.tool_result = bluetooth({"action": action}, Config())


@when('I take a screenshot with mode "{mode}"')
def step_shot(context, mode):
    context.tool_result = screenshot({"mode": mode}, Config())


@when("I send a notification with no headline")
def step_note_empty(context):
    context.tool_result = send_notification({"headline": ""}, Config())


@when('I send a notification with headline "{headline}"')
def step_note(context, headline):
    context.tool_result = send_notification({"headline": headline}, Config())


@when('I open app "{name}"')
def step_open(context, name):
    context.tool_result = open_app({"name": name}, Config())


@when('I step workspace "{direction}"')
def step_ws(context, direction):
    context.tool_result = workspace_step({"direction": direction}, Config())


@then('the last omarchy argv should include "{token}"')
def step_argv(context, token):
    argv = context.run_mock.call_args[0][0]
    assert token in argv, argv
