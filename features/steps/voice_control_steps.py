from __future__ import annotations

import json
import os
import signal
import subprocess
from copy import deepcopy
from dataclasses import replace
from unittest.mock import Mock, patch

from behave import given, then, when

from agavai.__main__ import listen_session
from agavai.orchestrator import CONTEXT_SYSTEM, run_turn
from agavai.router import select_head_ids
from agavai.tools import call_tool
from agavai.ui import cancel_ui


def _confirmation(raw):
    return {"content": "", "tool_calls": [{
        "id": "proposal", "type": "function",
        "function": {"name": "request_confirmation", "arguments": raw},
    }]}


def _browser_proposal():
    return _confirmation(json.dumps({"name": "launch", "arguments": {"target": "browser"}, "question": "Open the browser?"}))


@given("control turn dependencies are recorded")
def dependencies(context):
    context.control_responses = []
    context.control_requests = []

    def chat(cfg, messages, tools=None):
        context.control_requests.append((deepcopy(messages), deepcopy(tools)))
        if messages[0]["content"] == CONTEXT_SYSTEM:
            return {"content": "follow_up"}
        if getattr(context, "cancel_control_inference", False):
            cancel_ui(context.cfg)
        return context.control_responses.pop(0) if context.control_responses else {"content": "Normal answer."}

    mocks = {
        "control_health": patch("agavai.orchestrator.health", return_value=True),
        "control_chat": patch("agavai.orchestrator.chat", side_effect=chat),
        "control_router": patch("agavai.orchestrator.select_head_ids", wraps=select_head_ids),
        "control_tool": patch("agavai.orchestrator.call_tool", wraps=call_tool),
        "control_desktop": patch("agavai.tools._run", return_value=subprocess.CompletedProcess([], 0, "", "")),
        "control_which": patch("agavai.tools.shutil.which", return_value="/mock/desktop-command"),
        "control_wallpapers": patch("agavai.tools._list_wallpaper_files", return_value=[]),
    }
    for name, patched in mocks.items():
        setattr(context, name, patched.start())
        context.add_cleanup(patched.stop)


@given("a browser launch is awaiting confirmation")
def pending_browser(context):
    context.control_responses.append(_browser_proposal())
    context.reply = run_turn("open the browser but confirm first", context.cfg, context.ui)
    assert context.reply == "Open the browser?", context.reply
    assert context.ui.pending_action.name == "launch"
    assert context.ui.pending_action.arguments == {"target": "browser"}
    context.control_desktop.assert_not_called()
    context.control_tool.assert_not_called()
    for mock in (context.control_chat, context.control_health, context.control_router):
        mock.reset_mock()
    context.control_requests.clear()


@given("the control model is unavailable")
def unavailable(context):
    context.control_health.return_value = False


@given("prior control results are on the canvas")
def canvas(context):
    context.control_canvas = {"kind": "files", "title": "Images", "items": []}
    context.ui.display(context.control_canvas)
    context.control_canvas = deepcopy(context.ui.data["display"])


@given("the control desktop command fails")
def command_fails(context):
    context.control_desktop.return_value = subprocess.CompletedProcess([], 1, "", "launch failed")


@given('a control proposal for "{name}" with arguments "{arguments}"')
def proposal(context, name, arguments):
    context.control_responses.append(_confirmation(json.dumps({"name": name, "arguments": json.loads(arguments), "question": "Run the action?"})))


@given('a malformed control proposal "{raw}"')
def malformed(context, raw):
    context.control_responses.append(_confirmation(raw))


@given("a control confirmation and launch are returned together")
def combined(context):
    response = _browser_proposal()
    response["tool_calls"].append({"id": "launch", "function": {"name": "launch", "arguments": '{"target":"browser"}'}})
    context.control_responses.append(response)


@given("the control model asks only in prose")
def prose(context):
    context.control_responses.append({"content": "Open the browser?"})


@given("a browser confirmation will be cancelled during inference")
def cancel_inference(context):
    context.control_responses.append(_browser_proposal())
    context.cancel_control_inference = True


@when("the control session is dismissed")
def dismiss(context):
    cancel_ui(context.cfg)


@given("the control session will be dismissed at action start")
def cancel_at_start(context):
    original = context.ui.tool_start

    def start(name, arguments):
        original(name, arguments)
        cancel_ui(context.cfg)

    patched = patch.object(context.ui, "tool_start", side_effect=start)
    patched.start()
    context.add_cleanup(patched.stop)


@given("the control session will be dismissed during execution")
def cancel_during_execution(context):
    def execute(argv, timeout=15):
        cancel_ui(context.cfg)
        return subprocess.CompletedProcess(argv, 0, "", "")

    context.control_desktop.side_effect = execute


@given("the control schema budget is one")
def one_schema(context):
    context.cfg.router.max_tools = 1


@given('the confirmed control tool returns "{result}"')
def local_result(context, result):
    context.control_tool.return_value = result


@given('the confirmed control tool returns ""')
def empty_local_result(context):
    local_result(context, "")


@when("a control request is made without a chat UI")
def no_ui(context):
    context.reply = run_turn("open the browser but confirm first", context.cfg)


@when("the control proposal belongs to another session")
def stale(context):
    context.ui.pending_action = replace(context.ui.pending_action, session_id="stale")


@when("a control request combines two tool heads")
def budget(context):
    context.control_router.side_effect = lambda text, cfg: ["wallpaper", "system"]
    context.reply = run_turn("show wallpaper and system settings", context.cfg, context.ui)


@when("a real control listen loop receives")
def voice_loop(context):
    context.control_responses.append(_browser_proposal())
    sequences = [[]]
    for row in context.table:
        if row["kind"] == "enter":
            sequences[-1].append(lambda: os.kill(os.getpid(), signal.SIGTERM))
        else:
            sequences[-1].append((row["kind"], row["text"]))
        if row["kind"] in {"eou", "enter"}:
            sequences.append([])
    sequences.append([])
    context.control_capture_snapshots = []

    def events(on_level, should_stop=None):
        context.control_capture_snapshots.append(deepcopy(context.ui.data))
        for event in sequences.pop(0) if sequences else []:
            if callable(event):
                event()
            else:
                yield event

    stream = Mock()
    stream.events.side_effect = events
    with patch("agavai.__main__.prepare_listen"), patch("agavai.__main__.hide_listen"), patch("agavai.__main__.finish"), patch("agavai.__main__.cue_listen"), patch("agavai.__main__.cue_think") as think, patch("agavai.__main__._publish_pid"), patch("agavai.__main__.open_stream", return_value=stream), patch("agavai.tts.sweep_playback_wavs"), patch("agavai.tts._interruptible_speak", return_value="kokoro") as playback:
        context.listen_result = listen_session(context.cfg, context.ui)
        context.control_playback = playback.call_args_list
        context.control_think_count = think.call_count


@then("no control inference or routing happened")
def no_inference(context):
    context.control_health.assert_not_called()
    context.control_chat.assert_not_called()
    context.control_router.assert_not_called()


@then("no control desktop action happened")
def no_desktop(context):
    context.control_desktop.assert_not_called()


@then("the prepared browser launch executed once")
def launch_once(context):
    context.control_desktop.assert_called_once()
    assert context.control_desktop.call_args.args[0] == ["omarchy-launch-browser"], context.control_desktop.call_args
    context.control_tool.assert_called_once_with("launch", '{"target": "browser"}', context.cfg)


@then("there is no pending control action")
def no_pending(context):
    assert context.ui.pending_action is None, context.ui.pending_action


@then("a control action remains pending")
def still_pending(context):
    assert context.ui.pending_action is not None


@then("the control history contains the actual tool result")
def history(context):
    messages = context.ui.model_messages
    result = next(message for message in messages if message.get("role") == "tool" and message.get("content") == "launched browser")
    call = next(call for message in messages for call in message.get("tool_calls", []) if call["id"] == result["tool_call_id"])
    assert call["function"]["name"] == "launch"
    assert json.loads(call["function"]["arguments"]) == {"target": "browser"}
    assert messages[-1] == {"role": "assistant", "content": "launched browser"}


@then('the control action model received "{text}"')
def model_received(context, text):
    action = [messages for messages, tools in context.control_requests if messages[0]["content"] != CONTEXT_SYSTEM]
    assert action, "No action request"
    users = [message for message in action[-1] if message.get("role") == "user"]
    assert users[-1] == {"role": "user", "content": text}, users


@then("the control context decision happened once")
def context_once(context):
    assert sum(messages[0]["content"] == CONTEXT_SYSTEM for messages, tools in context.control_requests) == 1


@then("the prior control conversation was retained")
def conversation_retained(context):
    assert any(message.get("content") == "open the browser but confirm first" for message in context.ui.model_messages)


@then("the control conversation is empty")
def empty_conversation(context):
    assert not context.ui.model_messages and not context.ui.model_heads
    assert not context.ui.data["turns"]
    for key in ("display", "answer_html", "completion", "error"):
        assert key not in context.ui.data, context.ui.data
    assert context.ui.data["transcript"] == {"text": "", "final": False}


@then("the control schemas stay within the configured budget")
def schemas(context):
    tools = context.control_requests[-1][1]
    assert len(tools) <= context.cfg.router.max_tools
    confirmation = next(tool for tool in tools if tool["function"]["name"] == "request_confirmation")
    names = confirmation["function"]["parameters"]["properties"]["name"]["enum"]
    assert set(names) == {tool["function"]["name"] for tool in tools if tool != confirmation}


@then("only the proposal needed control inference")
def one_inference(context):
    assert len(context.control_requests) == 1, context.control_requests
    assert context.control_router.call_count == 1
    assert context.control_health.call_count == 1


@then("the control reset reopened a blank conversation")
def reset_capture(context):
    before = context.control_capture_snapshots[1]
    after = context.control_capture_snapshots[2]
    assert before["turns"]
    assert after["phase"] == "listening" and not after["turns"]
    assert before["session_id"] == after["session_id"]
    for key in ("display", "answer_html", "completion", "error"):
        assert key not in after, after
    assert all(messages[0]["content"] != CONTEXT_SYSTEM for messages, tools in context.control_requests)


@then("only the proposal and next request played replies")
def reset_silent(context):
    assert [call.args[0] for call in context.control_playback] == ["Open the browser?", "Normal answer."]
    assert context.control_think_count == 2
