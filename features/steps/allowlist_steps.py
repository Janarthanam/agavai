from __future__ import annotations

from unittest.mock import MagicMock, patch

from behave import given, then, when

from oma_voice.config import Config
from oma_voice.tools import call_tool, launch, play_url, to_workspace


@when('I call the tool "{name}" with empty arguments')
def step_call_empty(context, name):
    context.tool_result = call_tool(name, {}, Config())


@when('I call the tool "{name}" with query "{query}"')
def step_call_query(context, name, query):
    context.tool_result = call_tool(name, {"query": query}, Config())


@when('I launch target "{target}"')
def step_launch(context, target):
    context.tool_result = launch({"target": target}, Config())


@given('the launch binary "{binary}" is on PATH')
def step_launch_on_path(context, binary):
    context.launch_binary = binary
    run = MagicMock()
    run.returncode = 0
    run.stdout = ""
    run.stderr = ""
    which = patch("oma_voice.tools.shutil.which", return_value=f"/usr/bin/{binary}")
    run_p = patch("oma_voice.tools._run", return_value=run)
    context.which_cm = which
    context.run_cm = run_p
    context.run_mock = run_p.start()
    which.start()

    def cleanup():
        which.stop()
        run_p.stop()

    context.add_cleanup(cleanup)


@when("I switch to workspace {n:d}")
def step_workspace(context, n):
    context.tool_result = to_workspace({"workspace": n}, Config())


@when('I play url "{url}"')
def step_play(context, url):
    context.tool_result = play_url({"url": url}, Config())


@then('the tool result should contain "{text}"')
def step_result_contains(context, text):
    assert text in context.tool_result, context.tool_result


@then('the tool result should be "{text}"')
def step_result_eq(context, text):
    assert context.tool_result == text, context.tool_result


@then('the launched program should be "{binary}"')
def step_launched_bin(context, binary):
    argv = context.run_mock.call_args[0][0]
    assert argv[0] == binary, argv
