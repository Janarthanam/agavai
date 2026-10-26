from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
from unittest.mock import Mock, patch

from behave import given, then, when

from agavai.brain import create_brain
from agavai.config import LlmConfig
from agavai.harness import Harness
from agavai.harness.engine import CONTEXT_SYSTEM
from agavai.harness.session import listen_session, request_recording
from agavai.recording import Recorder, correct, line_text
from agavai.tools import execute_tool
from features.support.tool_replay import call
from features.support.session_replay import quiet_session


@given("an isolated harness with a local scripted language service")
def harness_service(context):
    context.requests, context.desktop_calls, context.reply_script = [], [], []
    context.relation = "follow_up"
    context.model_waiting, context.model_release = threading.Event(), threading.Event()
    context.slow = False

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def send(self, body):
            data = json.dumps(body).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            self.send({"status": "ok"})

        def do_POST(self):
            data = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            context.requests.append(data)
            system = data["messages"][0]["content"]
            if system == CONTEXT_SYSTEM:
                message = {"content": context.relation}
            elif "Resolve the user's self-correction" in system:
                message = {"content": json.dumps({"request": context.resolved_request})}
            elif context.reply_script:
                message = context.reply_script.pop(0)
            else:
                message = {"content": "Kubeflow is used for training. The source details are on the canvas."}
            if context.slow and system != CONTEXT_SYSTEM:
                context.model_waiting.set()
                context.model_release.wait(3)
            self.send({"choices": [{"message": message}]})

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    def cleanup():
        context.model_release.set()
        server.shutdown()
        server.server_close()
    context.add_cleanup(cleanup)
    cfg = context.cfg
    cfg.router.backend = cfg.router.fallback = "keyword"
    cfg.large_brain = LlmConfig(port=server.server_port, max_tokens=256, timeout_secs=5)
    cfg.small_brain = LlmConfig(backend="needle-cactus", model_id="action-replay")
    cfg.recordings.dir = context.runtime_dir / "recordings"
    context.harness_events = []
    def collect(event):
        context.harness_events.append(event)
        if not getattr(context, "headless_harness", False):
            context.ui.on_harness_event(event)
    cancel = None if getattr(context, "headless_harness", False) else context.ui.cancelled
    context.harness = Harness(cfg, on_event=collect, should_cancel=cancel)
    if not getattr(context, "headless_harness", False):
        assert context.ui.data["session_id"] == context.harness.context.session_id
    context.action = Mock(tool_only=True)
    context.action.ready.return_value = True
    context.action.respond.return_value = {"unsupported": "no match"}
    def brain(tier, **kwargs):
        return context.action if tier.backend == "needle-cactus" else create_brain(tier, **kwargs)
    def desktop(name, args, cfg):
        context.desktop_calls.append((name, json.loads(args) if isinstance(args, str) else args))
        return execute_tool(name, args, cfg)
    patches = [
        patch("agavai.harness.engine.create_brain", side_effect=brain),
        patch("agavai.harness.engine.call_tool", side_effect=desktop),
        patch("agavai.tools._run", return_value=Mock(returncode=0, stdout="", stderr="")),
        patch("agavai.tools.shutil.which", return_value="/replay/bin"),
    ]
    for item in patches:
        item.start()
        context.add_cleanup(item.stop)


def recording(context, words, offset=0):
    rec = Recorder(context.cfg, now=datetime(2026, 10, 25, 10, 0) + timedelta(minutes=offset))
    rec.audio(b"\x01\x00" * 1600)
    for i, text in enumerate(words):
        rec.add_line(text, i * 20, (i+1) * 20)
    with patch("agavai.recording._encode", return_value="Replay keeps uncompressed audio."):
        context.recording_folder = rec.finish()


@given('a saved harness recording with "{text}"')
def saved_recording(context, text):
    recording(context, [text])
    context.harness.context.recording = context.recording_folder
    context.harness.context.source_active = True


@given('line 1 is corrected to "{text}"')
def saved_correction(context, text):
    correct(context.recording_folder, 1, text)


@given('a saved harness recording with repeated "{text}"')
def repeated(context, text):
    recording(context, [text, text])
    context.harness.context.recording = context.recording_folder
    context.harness.context.source_active = True


@given("two saved harness recordings")
def two_recordings(context):
    recording(context, ["First recording"])
    recording(context, ["Second recording"], 1)


@given("a saved harness recording spanning several source parts")
def long_recording(context):
    context.cfg.large_brain.ctx_size = 3000
    recording(context, ["part-start " + "information " * 250 + " part-end"])


@given("a saved harness recording exceeding the source budget")
def excessive_recording(context):
    context.cfg.large_brain.ctx_size = 3000
    recording(context, ["information " * 2000])


@when('the harness receives "{text}"')
def harness_turn(context, text):
    context.turn_result = context.harness.run_turn(text, continue_conversation=bool(context.harness.context.committed_requests))
    context.reply = context.turn_result.speech_text or ""


@then('the language service received "{text}"')
def source_reached(context, text):
    assert text in json.dumps(context.requests, ensure_ascii=False)
    if context.harness.context.recording:
        assert not any(req.get("tools") for req in context.requests)


@then("no harness desktop action was dispatched")
def no_dispatch(context):
    assert not context.desktop_calls, context.desktop_calls


@then("the harness answer has a current recording revision")
def current_source(context):
    source = context.ui.data["source"]
    assert source["revision"] == context.harness.context.source_revision
    assert not source["derived_stale"]
    assert context.harness.context.derived_revision == source["revision"]


@then('the harness response excludes "{text}"')
def excludes(context, text):
    assert text not in context.reply


@then('the harness response contains "{text}"')
def includes(context, text):
    assert text in context.reply, context.reply


def meta(context):
    return json.loads((context.recording_folder / "recording.json").read_text())


@then('saved heard words contain "{text}"')
def heard(context, text):
    assert text in json.dumps([s.get("live") for s in meta(context)["segments"]])


@then('effective saved words contain "{text}"')
def effective(context, text):
    assert text in " ".join(line_text(s) for s in meta(context)["segments"])


@then("the harness answer is marked stale")
def stale(context):
    assert context.ui.data["source"]["derived_stale"]
    assert context.harness.context.derived_revision != context.harness.context.source_revision


@then("the harness language service received no request")
def no_model_request(context):
    assert not context.requests, context.requests


@then("every source part reached the language service")
def all_parts(context):
    assert len(context.requests) > 2
    joined = "\n".join(req["messages"][-1]["content"] for req in context.requests[:-1])
    assert "part-start" in joined and "part-end" in joined
    assert all(not req.get("tools") for req in context.requests)


@given("the action service proposes reading the screen")
def screen_proposal(context):
    context.action.respond.return_value = call("screen_context", {})


@given("the harness screen data contains an error message")
def screen_data(context):
    boundary = patch.dict("agavai.tools.DISPATCH", {"screen_context": lambda args, cfg: '{"text":"An error message is visible"}'})
    boundary.start()
    context.add_cleanup(boundary.stop)


@then("one screen read was recorded as successful")
def screen_ok(context):
    reads = [r for r in context.harness.context.execution.records if r["name"] == "screen_context"]
    assert len(reads) == 1 and reads[0]["status"] == "ok", reads
    assert context.ui.data["turns"][-1]["tools"][0]["status"] == "ok"


@given("the language service resolves a ten minute reminder")
def ten_minutes(context):
    context.resolved_request = "remind me in ten minutes to call the bank"
    context.reply_script = [call("reminder", {"minutes": 10, "message": "call the bank"}),
                            {"content": "Reminder set for ten minutes."}]


@given("the language service cannot resolve the correction")
def no_resolution(context):
    context.resolved_request = ""


@then("only a ten minute reminder was dispatched")
def ten_only(context):
    assert context.desktop_calls == [("reminder", {"minutes": 10, "message": "call the bank"})]


@then('the raw committed request contains "{text}"')
def raw_request(context, text):
    assert text in context.harness.context.committed_requests[0]


@then('the harness holds "{text}"')
def held_draft(context, text):
    assert context.harness.context.held and context.harness.context.draft == text


@then('the resumed harness retains "{text}"')
def retained_draft(context, text):
    assert not context.harness.context.held and context.harness.context.draft == text


@given("a long harness conversation with completed screen reads")
def long_conversation(context):
    screen_proposal(context)
    screen_data(context)
    for _ in range(12):
        context.harness.run_turn("read the screen " + "details " * 110, continue_conversation=True)
    context.before_history = deepcopy(context.harness.context.messages)
    context.before_records = deepcopy(context.harness.context.execution.records)
    context.cfg.large_brain.ctx_size = 3000
    context.cfg.small_brain = context.cfg.large_brain
    context.compaction_start = len(context.requests)


@then("the model received complete exchanges within its byte budget")
def packed_exchanges(context):
    for request in context.requests[context.compaction_start:]:
        limit = (3000 - request["max_tokens"]) * 2
        assert len(json.dumps(request["messages"]).encode()) + len(json.dumps(request.get("tools", [])).encode()) <= limit
    request = context.requests[-1]
    messages = request["messages"]
    ids = {c["id"] for m in messages for c in m.get("tool_calls") or []}
    assert all(m["tool_call_id"] in ids for m in messages if m["role"] == "tool")
    assert len(json.dumps(messages).encode()) + len(json.dumps(request.get("tools", [])).encode()) <= (3000-256)*2
    assert context.harness.context.compacted_exchanges > 0


@then("original harness exchanges and outcomes are retained")
def original_history(context):
    assert context.harness.context.messages[:len(context.before_history)] == context.before_history
    assert context.harness.context.execution.records == context.before_records


@given("a completed harness screen task and an unrelated request")
def unrelated(context):
    screen_proposal(context)
    screen_data(context)
    harness_turn(context, "read the screen")
    context.relation = "new_conversation"
    context.action.respond.return_value = call("launch", {"target": "browser"})


@then("the new action prompt excludes the screen task")
def fresh_prompt(context):
    messages = context.action.respond.call_args.args[0]
    assert "read the screen" not in json.dumps(messages)
    assert "error message" not in json.dumps(messages)


@then("the previous task is archived")
def archived(context):
    assert context.harness.context.archived_tasks


@given("a language request waiting to propose a browser launch")
def waiting_request(context):
    context.cfg.small_brain = context.cfg.large_brain
    context.reply_script = [call("launch", {"target": "browser"})]
    context.slow = True


@when("the harness request is cancelled during inference")
def cancel_inference(context):
    cancelled = threading.Event()
    context.harness.should_cancel = cancelled.is_set
    def cancel():
        assert context.model_waiting.wait(2)
        cancelled.set()
    thread = threading.Thread(target=cancel)
    thread.start()
    context.turn_result = context.harness.run_turn("open the browser")
    context.reply = context.turn_result.speech_text or ""
    thread.join(2)
    context.events_at_cancel = deepcopy(context.harness_events)
    if not getattr(context, "headless_harness", False):
        context.snapshot_at_cancel = context.ui.path.read_text()


@then("late inference cannot change the native snapshot")
@then("late inference cannot publish another harness event")
def late_no_write(context):
    context.model_release.set()
    context.harness.context.inference.running.join(2)
    assert context.harness_events == context.events_at_cancel
    if not getattr(context, "headless_harness", False):
        assert context.ui.path.read_text() == context.snapshot_at_cancel
    assert context.reply == ""


@then("another request cannot queue behind the abandoned inference")
def no_queued_inference(context):
    context.model_release.clear()
    context.model_waiting.clear()
    cancelled = threading.Event()
    context.harness.should_cancel = cancelled.is_set
    def cancel():
        context.model_waiting.wait(2)
        cancelled.set()
    threading.Thread(target=cancel).start()
    context.harness.run_turn("open the browser")
    context.harness.should_cancel = lambda: False
    context.turn_result = context.harness.run_turn("open the browser")
    context.reply = context.turn_result.speech_text or ""
    assert "still stopping" in context.reply
    context.model_release.set()
    context.harness.context.inference.running.join(2)


@when("a recording shortcut arrives during model inference")
def record_during_model(context):
    import agavai.harness.session as session
    context.record_started_while_waiting = False
    class Stream:
        captures = 0
        def events(self, **kwargs):
            self.captures += 1
            if self.captures == 1:
                yield "eou", "open the browser"
        def record(self, on_audio, should_stop):
            context.record_started_while_waiting = not context.model_release.is_set()
            context.model_release.set()
            on_audio(b"\x01\x00" * 1600)
            yield {"kind": "eou", "text": "Recorded during inference", "start_ms": 0, "end_ms": 100}
            yield {"kind": "eou", "text": "Agavai stop", "start_ms": 100, "end_ms": 110}
        def close(self):
            pass
    stream = Stream()
    def shortcut():
        assert context.model_waiting.wait(2)
        request_recording(context.cfg, "toggle")
    thread = threading.Thread(target=shortcut)
    thread.start()
    with quiet_session(), patch.object(session, "open_stream", return_value=stream):
        listen_session(context.cfg, harness=context.harness)
    thread.join(2)
    context.harness.context.inference.running.join(2)


@then("recording starts before that language request finishes")
def recording_while_waiting(context):
    assert context.record_started_while_waiting


@then("the saved recording is bound to the harness")
def saved_bound(context):
    folder = context.harness.context.recording
    assert folder and (folder / "recording.json").is_file()
    assert "Recorded during inference" in (folder / "transcript.md").read_text()


@given("the action service proposes the same browser launch twice")
def duplicate_launch(context):
    proposal = call("launch", {"target": "browser"})
    other = deepcopy(proposal["tool_calls"][0])
    other["id"] = "second-proposal"
    proposal["tool_calls"].append(other)
    context.action.respond.return_value = proposal


@given("the harness desktop command times out")
def command_timeout(context):
    import subprocess
    timeout = patch("agavai.tools._run", side_effect=subprocess.TimeoutExpired("launch", 20))
    timeout.start()
    context.add_cleanup(timeout.stop)


@then("exactly one unknown launch outcome is retained")
def unknown_launch(context):
    records = context.harness.context.execution.records
    assert len(records) == 1 and records[0]["name"] == "launch" and records[0]["status"] == "unknown", records
    assert len(context.desktop_calls) == 1


@then('the native task status is "{status}"')
def task_status(context, status):
    assert context.ui.data["task"]["status"] == status


@given("the language service proposes a screen read for a reasoning request")
def bad_reasoning_action(context):
    context.reply_script = [call("screen_context", {})]


@when("the recording changes while the language model reads it")
def changed_source(context):
    context.slow = True
    def edit():
        assert context.model_waiting.wait(2)
        correct(context.recording_folder, 1, "We use Kubeflow for training.")
        context.model_release.set()
    thread = threading.Thread(target=edit)
    thread.start()
    harness_turn(context, "summarize the last recording")
    thread.join(2)


@when("a newer recording arrives while the language model reads the last one")
def newer_source(context):
    context.original_source = context.recording_folder
    context.slow = True
    def save_new():
        assert context.model_waiting.wait(2)
        recording(context, ["A different meeting"], 1)
        context.model_release.set()
    thread = threading.Thread(target=save_new)
    thread.start()
    harness_turn(context, "summarize the last recording")
    thread.join(2)


@then("the answer still identifies the original recording")
def pinned_source(context):
    assert context.harness.context.recording == context.original_source
    assert context.ui.data["source"]["path"] == str(context.original_source)
    assert context.recording_folder != context.original_source


@when("another editor changes the line before the voice correction is saved")
def correction_race(context):
    def concurrent_edit(folder, line_id, text, *, expected_text):
        correct(folder, line_id, "We now use PyTorch.")
        correct(folder, line_id, text, expected_text=expected_text)
    with patch("agavai.harness.sources.correct", side_effect=concurrent_edit):
        harness_turn(context, "replace cube flow with Kubeflow in the transcript")
