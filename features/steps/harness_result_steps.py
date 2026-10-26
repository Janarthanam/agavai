from __future__ import annotations

from contextlib import redirect_stdout
import io
import json
import subprocess
import threading
from unittest.mock import Mock, patch

from behave import given, then, when

from agavai.__main__ import main
from agavai.harness import TurnResult
from agavai.harness.session import listen_session
from features.support.session_replay import quiet_session


@then('the turn result status is "{status}"')
def result_status(context, status):
    assert isinstance(context.turn_result, TurnResult)
    assert context.turn_result.status == status, context.turn_result


@then("the returned result agrees with its final event and durable trace")
def result_agreement(context):
    result = context.turn_result
    events = [e for e in context.harness_events if e.request_id == result.request_id]
    assert events[0].kind == "request_committed"
    assert events[-1].kind == "task_status"
    assert events[-1].data == {"status": result.status, "result": result.to_dict()}
    assert events[0].sequence == result.first_event_sequence
    assert events[-1].sequence == result.last_event_sequence
    assert (events[-1].session_id, events[-1].task_id) == (result.session_id, result.task_id)
    durable_agreement(context)


@then("the returned result agrees with its durable trace")
def durable_agreement(context):
    result = context.turn_result
    saved = context.harness.repository.inspect(result.session_id)
    event = next(e for e in saved["events"] if e["sequence"] == result.last_event_sequence)
    assert event["kind"] == "task_status"
    assert event["data"] == {"status": result.status, "result": result.to_dict()}
    turn = next(t for t in saved["turns"] if t["request_id"] == result.request_id)
    assert (turn["task_id"], turn["status"]) == (result.task_id, result.status)
    executions = [r for r in saved["executions"] if r["request_id"] == result.request_id]
    assert result.to_dict()["executions"] == [
        {"call_id": r["call_id"], **{k: r[k] for k in ("name", "arguments", "status", "result")}}
        for r in executions]
    assert json.loads(json.dumps(result.to_dict())) == result.to_dict()


@then("the turn result contains {number:d} executions")
def execution_count(context, number):
    assert len(context.turn_result.executions) == number, context.turn_result.executions


@then('the returned execution status is "{status}"')
def execution_status(context, status):
    assert len(context.turn_result.executions) == 1
    assert context.turn_result.executions[0].status == status


@given("the result client cancels as the desktop launch completes")
def client_cancel(context):
    cancelled = threading.Event()
    context.harness.should_cancel = cancelled.is_set
    def desktop(*args, **kwargs):
        cancelled.set()
        snapshot = context.runtime_dir / "ui.json"
        if snapshot.exists():
            sid = json.loads(snapshot.read_text())["session_id"]
            (context.runtime_dir / "dismissed-session").write_text(sid)
        return Mock(returncode=0, stdout="", stderr="")
    boundary = patch("agavai.tools._run", side_effect=desktop)
    boundary.start()
    context.add_cleanup(boundary.stop)


@then("the result client retains a cancelled turn with a successful execution")
def cancelled_client_result(context):
    saved = context.harness.repository.inspect(context.client_session_id)
    event = next(e for e in reversed(saved["events"]) if e["kind"] == "task_status")
    result = event["data"]["result"]
    assert result["status"] == "cancelled" and result["speech_text"] is None
    assert len(result["executions"]) == 1 and result["executions"][0]["status"] == "ok"
    assert len(context.desktop_calls) == 1


@given("the result client has no event sink")
def without_sink(context):
    context.harness.output.sink = None
    context.cfg.small_brain = context.cfg.large_brain


@then("the turn result contains the raw planets answer and its spoken summary")
def planets_result(context):
    assert context.turn_result.content == {"kind": "answer", "title": "Planets", "text": "- Mercury\n- Venus"}
    assert context.turn_result.speech_text == "Here are the planets."


@then("the turn result contains a recording answer")
def source_result(context):
    assert context.turn_result.content["kind"] == "answer"
    assert "Kubeflow" in context.turn_result.content["text"]
    assert context.turn_result.speech_text


@when("the result client remembers this outcome")
def remember_result(context):
    context.previous_result = context.turn_result
    context.previous_result_data = context.turn_result.to_dict()
    context.previous_sequence = context.harness.output.sequence


@then("the previous result remains unchanged")
def previous_unchanged(context):
    assert context.previous_result.to_dict() == context.previous_result_data


@when("the result client submits blank input")
def blank_input(context):
    context.pending_before_blank = context.harness.context.pending_action
    context.checkpoint_before_blank = context.harness.context.checkpoint()
    context.turn_result = context.harness.run_turn("   ", continue_conversation=True)


@then("the blank result requests input without committing a turn")
def blank_result(context):
    result = context.turn_result
    assert result.status == "needs_input" and result.speech_text == "I did not hear anything."
    assert result.request_id is result.first_event_sequence is result.last_event_sequence is None
    assert result.content is None and not result.executions
    assert context.harness.output.sequence == context.previous_sequence
    assert context.harness.context.pending_action is context.pending_before_blank
    assert context.harness.context.checkpoint() == context.checkpoint_before_blank


@then("the turn result has no speech or content")
def silent_result(context):
    assert context.turn_result.speech_text is None
    assert context.turn_result.content is None


@given('the desktop launch ends with "{outcome}"')
def launch_outcome(context, outcome):
    kwargs = {"return_value": Mock(returncode=1, stdout="", stderr="launch refused")}
    if outcome == "unknown":
        kwargs = {"side_effect": subprocess.TimeoutExpired("launch", 20)}
    boundary = patch("agavai.tools._run", **kwargs)
    boundary.start()
    context.add_cleanup(boundary.stop)


@given("the action model exhausts its tool rounds")
def exhausted(context):
    context.execute_steps("Given the action service proposes a browser launch")
    context.cfg.small_brain = context.cfg.large_brain
    context.cfg.small_brain.max_tool_rounds = 1
    context.cfg.large_brain = None
    context.reply_script = [context.action.respond.return_value]


@given("the collector changes finalized result payloads")
def mutate_result_event(context):
    collect = context.harness.output.sink
    def changed(event):
        if event.kind == "task_status":
            event.data["result"]["content"]["text"] = "consumer changed this"
            event.data["result"]["status"] = "failed"
        collect(event)
    context.harness.output.sink = changed


@when("the result client modifies returned content")
def mutate_result(context):
    context.turn_result.content["text"] = "caller changed this"
    detached = context.turn_result.to_dict()
    detached["content"]["title"] = "another change"
    assert context.turn_result.content["title"] == "Planets"


@then("the harness output and durable answer remain unchanged")
def detached_result(context):
    expected = {"kind": "answer", "title": "Planets", "text": "- Mercury\n- Venus"}
    assert context.harness.output.current_result == expected
    saved = context.harness.repository.inspect(context.harness.context.session_id)
    assert saved["events"][-1]["data"]["result"]["content"] == expected


@then("the resumed result advances the trace without changing the previous result")
def resumed_result(context):
    previous_unchanged(context)
    assert context.turn_result.session_id == context.previous_result.session_id
    assert context.turn_result.request_id != context.previous_result.request_id
    assert context.turn_result.first_event_sequence > context.previous_result.last_event_sequence


@when('the voice result client receives "{text}"')
def voice_result_client(context, text):
    class Stream:
        captures = 0
        def events(self, **kwargs):
            self.captures += 1
            if self.captures == 1:
                yield "eou", text
        def close(self):
            pass
    with quiet_session(), patch("agavai.harness.session.open_stream", return_value=Stream()), \
            patch("agavai.tts._interruptible_speak", return_value="completed") as speech:
        assert listen_session(context.cfg, harness=context.harness) == 0
    context.client_speech = [call.args[0] for call in speech.call_args_list]
    context.client_session_id = context.harness.context.session_id


@when('the typed result client asks "{text}"')
def typed_result_client(context, text):
    output = io.StringIO()
    with redirect_stdout(output), patch("agavai.__main__.load_config", return_value=context.cfg), \
            patch("agavai.__main__.write_card"), patch("agavai.__main__.cue_think"), \
            patch("agavai.ui.summon_overlay"), patch("agavai.__main__.speak", return_value="espeak") as speech:
        assert main(["ask", text]) == 0
    context.client_speech = [call.args[0] for call in speech.call_args_list]
    context.client_printed = output.getvalue().strip()
    context.client_session_id = json.loads((context.runtime_dir / "ui.json").read_text())["session_id"]


@then('the result client speaks "{speech}"')
def client_speech(context, speech):
    assert context.client_speech == ([speech] if speech else []), context.client_speech


@then('the typed result client prints "{speech}"')
def client_printed(context, speech):
    assert context.client_printed == speech


@then('the result client speaks ""')
def client_silent(context):
    client_speech(context, "")


@then('the typed result client prints ""')
def client_printed_nothing(context):
    client_printed(context, "")
