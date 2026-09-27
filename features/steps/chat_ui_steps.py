from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from behave import given, then, when

from agavai.config import Config
from agavai.ui import ChatUi


@given("a chat UI in a temp runtime dir")
def step_ui(context):
    tmp = Path(tempfile.mkdtemp())
    cfg = Config()
    cfg.runtime_dir = tmp
    context.runtime_dir = tmp
    context.summon = patch("agavai.ui.summon_overlay")
    context.summon.start()
    context.add_cleanup(context.summon.stop)
    context.ui = ChatUi(cfg)
    context.cfg = cfg


@when("the UI starts listening")
def step_listen(context):
    context.ui.listening()


@when('the user says "{text}"')
def step_user(context, text):
    context.ui.user(text)


@when('the UI starts tool "{name}" with "{args}"')
def step_tool_start(context, name, args):
    context.ui.tool_start(name, args)


@when('the UI finishes tool "{name}" with "{result}"')
def step_tool_done(context, name, result):
    context.ui.tool_done(name, result)


@when('the assistant says "{text}"')
def step_asst(context, text):
    context.ui.assistant(text)


@when("the UI goes idle")
def step_idle(context):
    context.ui.idle()


@when("I open a second chat UI on the same runtime dir")
def step_second(context):
    context.ui = ChatUi(context.cfg)


@then('the snapshot phase should be "{phase}"')
def step_phase(context, phase):
    data = json.loads((context.runtime_dir / "ui.json").read_text())
    context.snapshot = data
    assert data["phase"] == phase, data["phase"]


@then('the last user line should be "{text}"')
def step_user_line(context, text):
    data = json.loads((context.runtime_dir / "ui.json").read_text())
    assert data["turns"][-1]["user"] == text


@then("the last turn should have {n:d} tools")
def step_n_tools(context, n):
    data = json.loads((context.runtime_dir / "ui.json").read_text())
    assert len(data["turns"][-1]["tools"]) == n


@then('tool {n:d} should be "{name}" with status "{status}"')
def step_tool_n(context, n, name, status):
    data = json.loads((context.runtime_dir / "ui.json").read_text())
    tool = data["turns"][-1]["tools"][n - 1]
    assert tool["name"] == name, tool
    assert tool["status"] == status, tool


@then('the last assistant line should contain "{text}"')
def step_asst_line(context, text):
    data = json.loads((context.runtime_dir / "ui.json").read_text())
    assert text in data["turns"][-1]["assistant"]
