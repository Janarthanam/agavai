from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
from unittest.mock import Mock, patch

from behave import given, then, when

from agavai.config import Config
from agavai.harness.events import EventDeliveryError
from agavai.harness.session import listen_session
from features.support.session_replay import quiet_session
from features.support.tool_replay import call


@given("a headless harness with a local scripted language service")
def headless_service(context):
    folder = tempfile.TemporaryDirectory(prefix="agavai-headless-")
    context.add_cleanup(folder.cleanup)
    context.cfg = Config()
    context.runtime_dir = context.cfg.runtime_dir = Path(folder.name)
    context.headless_harness = True
    context.execute_steps("Given an isolated harness with a local scripted language service")


@given("the action service prepares a browser confirmation")
def headless_confirmation(context):
    context.action.respond.return_value = call("request_confirmation", {
        "name": "launch", "arguments": {"target": "browser"}, "question": "Open the browser?"})


@given("the action service proposes a browser launch")
def headless_launch(context):
    context.action.respond.return_value = call("launch", {"target": "browser"})


@given("the language service returns a structured planets answer")
def planets(context):
    context.cfg.small_brain = context.cfg.large_brain
    context.reply_script = [call("show_answer", {"title": "Planets", "markdown": "- Mercury\n- Venus", "summary": "Here are the planets."})]


@when("a separate headless process asks the language service")
def isolated_process(context):
    source = '''
import json
from pathlib import Path
import sys
sys.modules["agavai.ui"] = None
from agavai.config import Config, LlmConfig
from agavai.harness import Harness
from agavai.harness.session import listen_session
cfg = Config()
cfg.runtime_dir = Path(sys.argv[2])
cfg.small_brain = LlmConfig(port=int(sys.argv[1]), timeout_secs=5)
events = []
harness = Harness(cfg, on_event=events.append)
result = harness.run_turn("explain gravity")
assert sys.modules["agavai.ui"] is None
print(json.dumps({"reply": result.speech_text, "result": result.to_dict(), "events": [event.to_dict() for event in events]}))
'''
    result = subprocess.run([sys.executable, "-c", source, str(context.cfg.large_brain.port), str(context.runtime_dir)],
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    context.child_result = json.loads(result.stdout)


@then("that process publishes serializable ordered events without importing the UI")
def isolated_events(context):
    events = context.child_result["events"]
    assert events[0]["kind"] == "session_started"
    assert events[-1]["kind"] == "task_status" and events[-1]["data"]["status"] == "answered"
    assert any(event["kind"] == "reply" for event in events)
    assert [event["sequence"] for event in events] == list(range(1, len(events)+1))
    assert all(event["schema_version"] == 1 for event in events)
    assert len({event["session_id"] for event in events}) == 1
    assert context.child_result["reply"]
    assert events[-1]["data"]["result"] == context.child_result["result"]
    assert context.requests, "The subprocess must use the real HTTP model transport."


@then("no headless UI snapshot was created")
def no_snapshot(context):
    assert not (context.runtime_dir / "ui.json").exists()


@then('the headless task status is "{status}"')
def headless_status(context, status):
    events = [event for event in context.harness_events if event.kind == "task_status"]
    assert events[-1].data["status"] == status, events


@then("the collector received one complete browser outcome")
def browser_outcome(context):
    completed = [event for event in context.harness_events if event.kind == "tool_completed"]
    assert len(completed) == 1 and completed[0].data["name"] == "launch", completed
    record = context.harness.context.execution.records[0]
    assert completed[0].data["result"] == record["result"] and completed[0].data["status"] == record["status"] == "ok"
    assert completed[0].task_id == record["task_id"] and completed[0].request_id == record["request_id"]
    started = next(event for event in context.harness_events if event.kind == "tool_started")
    assert started.data["call_id"] == completed[0].data["call_id"] == record["id"]
    assert started.data["arguments"] == record["arguments"]


@then("harness events have ordered session and request identity")
def event_identity(context):
    events = context.harness_events
    assert [event.sequence for event in events] == list(range(1, len(events)+1))
    assert all(event.session_id == context.harness.context.session_id for event in events)
    committed = [event for event in events if event.kind == "request_committed"]
    assert len(committed) == 2 and len({event.request_id for event in committed}) == 2
    assert all(event.request_id for event in events[1:])
    for previous, event in zip(events, events[1:]):
        if event.task_id != previous.task_id:
            assert event.kind == "task_started" and event.data["previous_task_id"] == previous.task_id
    confirmations = [event for event in events if event.kind == "confirmation_requested"]
    assert len(confirmations) == 1 and confirmations[0].data == {
        "name": "launch", "arguments": {"target": "browser"}, "question": "Open the browser?"}
    json.dumps([event.to_dict() for event in events])


@then("the collector received the complete planets answer")
def complete_answer(context):
    answers = [event.data for event in context.harness_events if event.kind == "answer"]
    assert answers == [{"title": "Planets", "markdown": "- Mercury\n- Venus"}], answers
    assert context.reply == "Here are the planets."


@then("the new request moves to its own task in the event stream")
def new_task_events(context):
    events = context.harness_events
    committed = [event for event in events if event.kind == "request_committed"][-1]
    selected = [event for event in events if event.kind == "task_started"][-1]
    completed = [event for event in events if event.kind == "tool_completed"][-1]
    assert selected.sequence > committed.sequence
    assert selected.data["previous_task_id"] == committed.task_id != selected.task_id
    assert selected.task_id == completed.task_id == context.harness.context.task_id
    assert committed.request_id == selected.request_id == completed.request_id
    assert context.harness.context.archived_tasks[-1]["id"] == committed.task_id


@then("the collector observed a source revision change and stale derived output")
def source_revisions(context):
    sources = [event.data["source"] for event in context.harness_events if event.kind == "source_changed"]
    assert len(sources) == 2 and sources[0]["revision"] != sources[1]["revision"]
    assert not sources[0]["derived_stale"] and sources[1]["derived_stale"]


@when("the request is cancelled while that desktop action runs")
def cancel_action(context):
    cancelled = threading.Event()
    context.harness.should_cancel = cancelled.is_set
    def desktop(*args, **kwargs):
        cancelled.set()
        return Mock(returncode=0, stdout="", stderr="")
    with patch("agavai.tools._run", side_effect=desktop):
        context.execute_steps('When the harness receives "open the browser"')


@then("the cancelled request published no reply")
def no_cancelled_reply(context):
    assert context.reply == ""
    assert not any(event.kind == "reply" for event in context.harness_events)
    assert context.harness_events[-1].kind == "task_status"


@given("the collector changes action event payloads")
def mutate_collector(context):
    collect = context.harness.output.sink
    def changed(event):
        if event.kind == "tool_started":
            event.data["name"] = "set_volume"
            event.data["arguments"] = '{"action":"raise"}'
        elif event.kind == "confirmation_requested":
            event.data["arguments"]["target"] = "terminal"
        collect(event)
    context.harness.output.sink = changed


@then("only the originally proposed browser launch was dispatched")
def original_launch(context):
    assert context.desktop_calls == [("launch", {"target": "browser"})], context.desktop_calls


@given('the collector rejects "{kind}" events')
def failed_collector(context, kind):
    collect = context.harness.output.sink
    def rejected(event):
        if event.kind == kind:
            raise ValueError("event consumer unavailable")
        collect(event)
    context.harness.output.sink = rejected


@when('the headless harness attempts "{text}"')
def failed_request(context, text):
    try:
        context.harness.run_turn(text)
    except EventDeliveryError as exc:
        context.consumer_error = exc
    else:
        raise AssertionError("The consumer failure must reach the caller.")


@then("the consumer failure reaches its caller")
def consumer_error(context):
    assert str(context.consumer_error.__cause__) == "event consumer unavailable"
    assert not context.harness.context.execution.records


@then("the collector observed recording lifecycle events")
def recording_events(context):
    kinds = [event.kind for event in context.harness_events]
    assert "recording" in kinds and "recording_ended" in kinds and "display" in kinds


@when('the headless caller cancels during "{mode}" capture')
def cancel_capture(context, mode):
    cancelled = threading.Event()
    context.harness.should_cancel = cancelled.is_set
    class Stream:
        closed = False
        def events(self, **kwargs):
            yield "interim", "uncommitted words"
            cancelled.set()
            assert kwargs["should_cancel"]() and kwargs["should_stop"]()
        def record(self, on_audio, should_stop):
            on_audio(b"\x01\x00" * 1600)
            yield {"kind": "eou", "text": "Retained speech", "start_ms": 0, "end_ms": 100}
            cancelled.set()
            assert should_stop()
        def close(self):
            self.closed = True
    context.capture_stream = Stream()
    with quiet_session(), patch("agavai.harness.session.open_stream", return_value=context.capture_stream):
        context.listen_result = listen_session(context.cfg, harness=context.harness, record=mode == "recording")
    if mode == "recording":
        folder = context.harness.context.recording
        assert folder and "Retained speech" in (folder / "transcript.md").read_text()


@then("headless capture closes without committing a model request")
def capture_closed(context):
    assert context.listen_result == 0 and context.capture_stream.closed
    assert not context.requests and not context.desktop_calls
    assert not any(event.kind == "request_committed" for event in context.harness_events)
