from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from behave import given, then, when

from agavai.config import Config
from agavai.harness import Harness
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
    context.harness = Harness(cfg, on_event=context.ui.on_harness_event, should_cancel=context.ui.cancelled)


@when("the UI starts listening")
def step_listen(context):
    context.harness = Harness(context.cfg, on_event=context.ui.on_harness_event, should_cancel=context.ui.cancelled)
    context.ui.listening()


@when("the UI listens for a follow-up")
def step_follow(context):
    context.ui.continue_listening()


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
    context.harness.close()
    context.ui = ChatUi(context.cfg)
    context.harness = Harness(context.cfg, on_event=context.ui.on_harness_event, should_cancel=context.ui.cancelled)
    context.add_cleanup(context.harness.close)


@when("I resume the saved session in a second chat UI")
def step_resume_ui(context):
    sid = context.harness.context.session_id
    context.harness.close()
    context.ui = ChatUi(context.cfg)
    context.harness = Harness(context.cfg, on_event=context.ui.on_harness_event, should_cancel=context.ui.cancelled, session_id=sid)
    context.add_cleanup(context.harness.close)


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


@then('the completion is "{title}" with "{detail}"')
def step_completion(context, title, detail):
    data = json.loads((context.runtime_dir / "ui.json").read_text())
    assert data["completion"]["title"] == title, data.get("completion")
    assert detail in data["completion"]["detail"], data.get("completion")


@then("there is no completion")
def step_no_completion(context):
    data = json.loads((context.runtime_dir / "ui.json").read_text())
    assert "completion" not in data, data.get("completion")


@then('the last assistant line should contain "{text}"')
def step_asst_line(context, text):
    data = json.loads((context.runtime_dir / "ui.json").read_text())
    assert text in data["turns"][-1]["assistant"]


@when('the UI reports tool "{name}" failed with "{result}"')
def failed_tool(context, name, result):
    context.ui.tool_done(name, result, status="error")
