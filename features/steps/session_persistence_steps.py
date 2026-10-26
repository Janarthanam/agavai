from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

from behave import given, when, then

from agavai.harness import Harness
from agavai.harness.session import _cancel_path, listen_session
from agavai.harness.storage import SessionRepository
from agavai.ui import ChatUi
from features.support.session_replay import quiet_session
from features.support.tool_replay import call


def child(context, text, *, sid="", mode="turn"):
    return subprocess.run([sys.executable, "features/support/persistent_process.py", str(context.cfg.large_brain.port),
                           str(context.runtime_dir), mode, sid, text], capture_output=True, text=True, timeout=15)


def repository(context):
    return SessionRepository(context.cfg.sessions.dir)


def child_sid(context):
    return (context.runtime_dir / "child-session").read_text()


def cli(context, *args):
    config = context.runtime_dir / "sessions-config.toml"
    config.write_text(f'[sessions]\ndir = {json.dumps(str(context.cfg.sessions.dir))}\n')
    env = {**os.environ, "AGAVAI_CONFIG": str(config), "XDG_RUNTIME_DIR": str(context.runtime_dir / "cli")}
    return subprocess.run([sys.executable, "-m", "agavai", "session", *args], env=env,
                           capture_output=True, text=True, timeout=10)


@when('a separate persistent process asks "{text}"')
def first_process(context, text):
    result = child(context, text)
    assert result.returncode == 0, result.stderr
    context.child_result = json.loads(result.stdout)


@when('another process continues that session with "{text}"')
def next_process(context, text):
    context.requests.clear()
    result = child(context, text, sid=child_sid(context))
    assert result.returncode == 0, result.stderr
    context.child_result = json.loads(result.stdout)


@then('the resumed model request includes "{text}"')
def previous_request(context, text):
    assert text in json.dumps(context.requests), context.requests


@then("the session ledger contains both turns and ordered lifecycle events")
def durable_order(context):
    data = repository(context).inspect(child_sid(context))
    assert [t["input"] for t in data["turns"]] == ["explain gravity", "explain that again"]
    assert all(t["status"] == "answered" and t["audio"] is None for t in data["turns"])
    events = data["events"]
    assert [e["sequence"] for e in events] == list(range(1, len(events) + 1))
    assert any(e["kind"] == "session_resumed" for e in events)
    assert len({t["request_id"] for t in data["turns"]}) == 2
    assert data["status"] == "closed"
    assert json.loads(cli(context, "list").stdout)


@then("session inspection includes the effective configuration fingerprint")
def config_fingerprint(context):
    data = json.loads(cli(context, "show", child_sid(context)).stdout)
    assert data["config"]["effective"]["primary"]["backend"] == "llama-server"
    assert data["config"]["effective"]["sessions"]["save_audio"] is True
    assert len(data["config"]["sha256"]) == 64 and data["config"]["version"]


@then("durable executions match the full harness outcomes")
def full_outcome(context):
    data = repository(context).inspect(context.harness.context.session_id)
    executions = data["executions"]
    expected = context.harness.context.execution.records
    assert len(executions) == len(expected) == 1
    for key in ("status", "result", "arguments", "task_id", "request_id"):
        assert executions[0][key] == expected[0][key]
    events = data["events"]
    assert next(e["sequence"] for e in events if e["kind"] == "tool_completed") < next(e["sequence"] for e in events if e["kind"] == "reply")


@when("a separate process dies while launching a browser")
def crash_action(context):
    context.reply_script = [call("launch", {"target": "browser"})]
    result = child(context, "open the browser", mode="crash")
    assert result.returncode == 73, result.stderr
    assert (context.runtime_dir / "side-effect").read_text() == "browser launched"


@then("inspection reports an interrupted turn and unknown action")
def unknown_action(context):
    data = json.loads(cli(context, "show", child_sid(context)).stdout)
    assert data["turns"][-1]["status"] == "interrupted"
    assert data["executions"][-1]["status"] == "unknown"


@then("no old action is replayed and a fresh instruction is required")
def no_replay(context):
    assert "fresh instruction" in context.child_result["reply"]
    assert not context.requests
    data = repository(context).inspect(child_sid(context))
    assert len(data["executions"]) == 1 and data["executions"][0]["status"] == "unknown"
    messages = data["checkpoint"]["messages"]
    assert any(m["role"] == "tool" and "unknown" in m["content"] for m in messages)


@when("the harness closes and resumes its session")
def reopen(context):
    sid = context.harness.context.session_id
    context.harness.close()
    context.harness = Harness(context.cfg, on_event=context.harness_events.append, session_id=sid)
    context.add_cleanup(context.harness.close)


@when("another process tries to resume the active harness session")
def concurrent(context):
    context.resume_result = child(context, "hello", sid=context.harness.context.session_id)


@then("session resume is rejected as already active")
def locked(context):
    assert context.resume_result.returncode != 0 and "active in another process" in context.resume_result.stderr


@when("the native adapter resumes that saved session")
def native_resume(context):
    sid = context.harness.context.session_id
    context.harness.close()
    context.ui = ChatUi(context.cfg)
    context.harness = Harness(context.cfg, on_event=context.ui.on_harness_event, session_id=sid)
    context.add_cleanup(context.harness.close)


@then("the native snapshot identifies a resumed durable session with its prior answer")
def restored_ui(context):
    data = json.loads((context.runtime_dir / "ui.json").read_text())
    assert data["session"] == {"id": context.harness.context.session_id, "persistent": True, "resumed": True, "directory": str(context.cfg.sessions.dir)}
    assert data["turns"][-1]["user"] == "explain gravity"
    assert data["turns"][-1]["assistant"]
    assert data["sessions"]


@given("persistence is disabled for the next harness")
def disabled(context):
    context.cfg.sessions.enabled = False


@when('a new harness session receives "{text}"')
def isolated(context, text):
    context.previous_sid = context.harness.context.session_id
    context.harness.close()
    context.harness = Harness(context.cfg)
    context.add_cleanup(context.harness.close)
    context.harness.run_turn(text)


@then("the new session has no gravity context")
def isolation(context):
    assert "gravity" not in json.dumps(context.harness.context.checkpoint())
    assert context.previous_sid != context.harness.context.session_id


@then("the temporary session has no durable ledger entry")
def temporary(context):
    assert context.harness.repository is None
    assert not any(row["id"] == context.harness.context.session_id for row in repository(context).list())


@given('spoken audio encoding uses "{encoding}"')
def audio_encoding(context, encoding):
    context.encoding = encoding


class Capture:
    def __init__(self, context, text, ending="accepted", seconds=1):
        self.context, self.text, self.ending, self.seconds = context, text, ending, seconds
        self.count = 0

    def events(self, on_level, should_stop=None, should_cancel=None, audio_tap=None):
        self.count += 1
        if self.count > 1:
            return
        if audio_tap:
            audio_tap(b"\x00\x00" * 16000)
            audio_tap(b"\x00\x20" * (16000 * self.seconds))
            audio_tap(b"\x00\x00" * 16000)
        if self.ending == "cancel":
            _cancel_path(self.context.cfg).touch()
            import signal
            os.kill(os.getpid(), signal.SIGTERM)
            return
        if self.ending == "error":
            from agavai.asr import AsrError
            raise AsrError("Capture failed.")
        yield "eou", "" if self.ending == "empty" else self.text

    def close(self):
        pass


def voice(context, text, *, ending="accepted", seconds=1):
    stream = Capture(context, text, ending, seconds)
    encoding = getattr(context, "encoding", "absent")
    from agavai.recording import _encode as real_encode
    # quiet_session scripts external playback; encoding can use the real local ffmpeg.
    with quiet_session(), patch("agavai.harness.session.open_stream", return_value=stream):
        if encoding in {"opus", "timeout"}:
            def encode(folder, **kwargs):
                if encoding == "timeout":
                    with patch("agavai.recording.subprocess.run", side_effect=subprocess.TimeoutExpired("ffmpeg", 15)):
                        return real_encode(folder, **kwargs)
                return real_encode(folder, **kwargs)
            with patch("agavai.harness.audio._encode", side_effect=encode):
                listen_session(context.cfg, harness=context.harness)
                context.harness.close()
        else:
            with patch("agavai.harness.audio._encode", return_value="Encoder unavailable; WAV retained."):
                listen_session(context.cfg, harness=context.harness)
                context.harness.close()
    context.saved = repository(context).inspect(context.harness.context.session_id)


@when('the voice controller accepts "{text}" with captured audio')
def captured(context, text):
    voice(context, text)


@then('the accepted turn has checksummed "{codec}" audio without idle silence')
def ready_audio(context, codec):
    turns = context.saved["turns"]
    assert len(turns) == 1 and turns[0]["mode"] == "spoken"
    audio = turns[0]["audio"]
    assert audio["status"] == "ready" and audio["codec"] == codec, audio
    path = repository(context).attachment(context.harness.context.session_id, audio["path"])
    assert hashlib.sha256(path.read_bytes()).hexdigest() == audio["sha256"]
    assert audio["duration_ms"] == 1000 and audio["source_start_ms"] == 1000 and audio["source_end_ms"] == 2000
    assert turns[0]["request_id"] in path.name
    if codec == "pcm_s16le":
        assert audio["warning"]
    destination = context.runtime_dir / "audio-export"
    result = cli(context, "export", context.harness.context.session_id, str(destination))
    assert result.returncode == 0, result.stderr
    assert (destination / audio["path"]).read_bytes() == path.read_bytes()


@then("no PCM bytes appear in the durable event stream")
def no_pcm(context):
    assert "\\u0000" not in json.dumps(context.saved["events"])
    assert not any(e["kind"] in {"partial", "level"} for e in context.saved["events"])
    assert any(e["kind"] == "audio_status" for e in context.saved["events"])


@when('the voice controller receives an "{ending}" capture')
def abandoned(context, ending):
    voice(context, "abandoned words", ending=ending)


@then("no accepted spoken turn or audio attachment was saved")
def no_audio(context):
    assert not context.saved["turns"]
    assert not list(repository(context).folder(context.harness.context.session_id).rglob("*.wav"))


@given("spoken-turn audio retention is disabled")
def no_retention(context):
    context.cfg.sessions.save_audio = False


@then("the spoken transcript is saved without audio")
def text_only(context):
    assert context.saved["turns"][0]["input"] == "explain gravity"
    assert context.saved["turns"][0]["audio"] is None


@given("the session audio quota is one megabyte")
def quota(context):
    context.cfg.sessions.max_audio_mb = 1


@when("the voice controller accepts a long audio turn")
def large_turn(context):
    voice(context, "explain gravity", seconds=40)


@then("the saved turn reports audio quota exceeded")
def refused(context):
    assert context.saved["turns"][0]["audio"]["status"] == "quota_exceeded"
    assert any(e["kind"] == "audio_status" and e["data"]["status"] == "quota_exceeded" for e in context.saved["events"])


@when("a separate process dies while encoding accepted turn audio")
def crash_audio(context):
    result = child(context, "explain gravity", mode="audio_crash")
    assert result.returncode == 74, result.stderr


@then("saved audio is reported incomplete on inspection and resume")
def incomplete(context):
    data = repository(context).inspect(child_sid(context))
    assert data["turns"][0]["audio"]["status"] == "incomplete"
    harness = Harness(context.cfg, session_id=child_sid(context))
    harness.close()
    assert repository(context).inspect(child_sid(context))["turns"][0]["audio"]["status"] == "incomplete"


@when("the finalized attachment goes missing")
def lose_audio(context):
    audio = context.saved["turns"][0]["audio"]
    repository(context).attachment(context.harness.context.session_id, audio["path"]).unlink()


@then("inspection and export report missing audio")
def missing_audio(context):
    sid = context.harness.context.session_id
    assert json.loads(cli(context, "show", sid).stdout)["turns"][0]["audio"]["status"] == "missing"
    destination = context.runtime_dir / "missing-export"
    result = cli(context, "export", sid, str(destination))
    assert result.returncode == 0, result.stderr
    assert json.loads((destination / "session.json").read_text())["turns"][0]["audio"]["status"] == "missing"


@when("the session is exported and deleted through the CLI")
def export_delete(context):
    sid = context.harness.context.session_id
    context.harness.close()
    destination = context.runtime_dir / "export"
    result = cli(context, "export", sid, str(destination))
    assert result.returncode == 0, result.stderr
    context.exported = json.loads((destination / "session.json").read_text())
    refused = cli(context, "delete", sid)
    assert refused.returncode == 1 and "--yes" in refused.stderr
    result = cli(context, "delete", sid, "--yes")
    assert result.returncode == 0, result.stderr
    assert not repository(context).folder(sid).exists()
    assert not any(row["id"] == sid for row in repository(context).list())


@then("the exported ledger retains source revisions and corrected context")
def corrections(context):
    sources = context.exported["sources"]
    assert len({s["revision"] for s in sources}) >= 2
    assert "Kubeflow" in json.dumps(context.exported["checkpoint"])
    assert any(e["kind"] == "source_changed" and e["data"]["source"]["derived_stale"] for e in context.exported["events"])


@then("the referenced recording and its audio still exist")
def original_audio(context):
    assert (context.recording_folder / "recording.json").exists()
    assert (context.recording_folder / "audio.wav").exists()


@when("the referenced recording is moved away")
def missing_recording(context):
    context.recording_folder.rename(context.recording_folder.with_name("moved"))


@then("session inspection reports an unavailable source")
def missing_source(context):
    data = repository(context).inspect(context.harness.context.session_id)
    assert data["sources"] and not data["sources"][0]["available"]


@when("expired and recent sessions are pruned through the CLI")
def prune(context):
    context.harness.close()
    context.expired_sid = context.harness.context.session_id
    recent = Harness(context.cfg)
    context.recent_sid = recent.context.session_id
    recent.close()
    held = Harness(context.cfg)
    context.add_cleanup(held.close)
    context.held_sid = held.context.session_id
    with repository(context).connect() as db:
        db.execute("UPDATE sessions SET updated='2000-01-01T00:00:00+00:00' WHERE id IN (?,?)", (context.expired_sid, context.held_sid))
    refused = cli(context, "prune", "--older-than-days", "1")
    assert refused.returncode == 1 and "--yes" in refused.stderr
    result = cli(context, "prune", "--older-than-days", "1", "--yes")
    assert result.returncode == 0, result.stderr


@then("only the expired session is removed")
def retained(context):
    ids = {r["id"] for r in repository(context).list()}
    assert context.expired_sid not in ids and context.recent_sid in ids and context.held_sid in ids
    assert repository(context).active(context.held_sid)


@when("a separate CLI encounters a newer session schema")
def newer(context):
    context.harness.close()
    with repository(context).connect() as db:
        db.execute("PRAGMA user_version=99")
    context.schema_result = cli(context, "list")


@then("the CLI rejects the unsupported schema")
def schema_error(context):
    assert context.schema_result.returncode == 1
    assert "Unsupported session schema version 99" in context.schema_result.stderr


@given("the session database rejects execution-start writes")
def storage_failure(context):
    with repository(context).connect() as db:
        db.execute("CREATE TRIGGER reject_start BEFORE INSERT ON executions BEGIN SELECT RAISE(FAIL, 'storage unavailable'); END")


@then("the persistence failure reaches the caller before execution")
def storage_error(context):
    assert "storage unavailable" in str(context.consumer_error.__cause__)
    assert not context.harness.context.execution.records


@then("the durable ledger still contains all pre-compaction outcomes")
def compacted_ledger(context):
    data = repository(context).inspect(context.harness.context.session_id)
    assert len(data["executions"]) == len(context.before_records)
    assert len(data["turns"]) == 13
    assert data["checkpoint"]["compacted_exchanges"] > 0
    assert data["checkpoint"]["messages"][:len(context.before_history)] == context.before_history


@when("two spoken turns arrive while the first audio encoder waits")
def queued_audio(context):
    import threading
    ready, release = threading.Event(), threading.Event()
    stream = Capture(context, "explain gravity")
    original_events = stream.events
    attempts = 0
    def events(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        if attempts > 2:
            return
        if attempts == 2:
            assert ready.wait(2), "The encoder must have started before capture reopens."
            release.set()
            stream.text = "explain that again"
        stream.count = 0
        yield from original_events(*args, **kwargs)
    stream.events = events
    def encode(folder, **kwargs):
        ready.set()
        assert release.wait(3), "Encoding must not block the next microphone capture."
        return "Scripted encoder retains WAV."
    with quiet_session(), patch("agavai.harness.session.open_stream", return_value=stream), patch("agavai.harness.audio._encode", side_effect=encode):
        try:
            listen_session(context.cfg, harness=context.harness)
        finally:
            release.set()
            context.harness.close()
    context.saved = repository(context).inspect(context.harness.context.session_id)


@then("both turns finish with separate ready audio attachments")
def two_audio(context):
    turns = context.saved["turns"]
    assert len(turns) == 2 and all(t["status"] == "answered" for t in turns)
    assert all(t["audio"]["status"] == "ready" for t in turns), turns
    assert len({t["audio"]["path"] for t in turns}) == 2
    for turn in turns:
        path = repository(context).attachment(context.harness.context.session_id, turn["audio"]["path"])
        assert hashlib.sha256(path.read_bytes()).hexdigest() == turn["audio"]["sha256"]
    notices = [e for e in context.saved["events"] if e["kind"] == "audio_status"]
    assert {e["request_id"] for e in notices} == {t["request_id"] for t in turns}


@when("the native session history check runs")
def native_history(context):
    if not os.environ.get("AGAVAI_NATIVE_UI_CHECK"):
        context.scenario.skip("Set AGAVAI_NATIVE_UI_CHECK=1 on an unlocked Wayland desktop")
        return
    context.native_sessions = subprocess.run([sys.executable, "scripts/check-compact-ui.py", "sessions"],
                                             capture_output=True, text=True, timeout=30)


@then("native session selection and typed continuation checks pass")
def native_history_pass(context):
    assert context.native_sessions.returncode == 0, context.native_sessions.stdout + context.native_sessions.stderr


@when("the voice controller attempts the action with unavailable storage")
def voice_storage_failure(context):
    from agavai.harness.events import EventDeliveryError
    context.failed_stream = Capture(context, "open the browser")
    with quiet_session(), patch("agavai.harness.session.open_stream", return_value=context.failed_stream):
        try:
            listen_session(context.cfg, harness=context.harness)
        except EventDeliveryError as exc:
            context.consumer_error = exc
        else:
            raise AssertionError("Persistence failure must stop the listener.")


@then("persistence failure closes the listener without another capture or action")
def voice_storage_stopped(context):
    assert context.failed_stream.count == 1
    assert not context.desktop_calls
    assert "storage unavailable" in str(context.consumer_error.__cause__)
    assert not repository(context).active(context.harness.context.session_id)
    assert not (context.runtime_dir / "listen.pid").exists()


@when("another process restores the interrupted session and exits")
def restore_again(context):
    result = child(context, "", sid=child_sid(context), mode="resume_crash")
    assert result.returncode == 75, result.stderr
    data = repository(context).get(child_sid(context))
    assert data["checkpoint"]["recovery_required"]


@when('the session CLI loads "{setting}"')
def invalid_session_config(context, setting):
    config = context.runtime_dir / "invalid-session.toml"
    config.write_text("[sessions]\n" + setting + "\n")
    context.config_result = subprocess.run([sys.executable, "-m", "agavai", "session", "list"],
        env={**os.environ, "AGAVAI_CONFIG": str(config), "XDG_RUNTIME_DIR": str(context.runtime_dir / "cli")},
        capture_output=True, text=True, timeout=10)


@then('the persistence configuration error names "{field}"')
def invalid_config_error(context, field):
    assert context.config_result.returncode != 0
    assert "[sessions] " + field in context.config_result.stderr


@when("a separate process dies after completing the action but before replying")
def reply_crash(context):
    context.reply_script = [call("launch", {"target": "browser"}), {"content": "Opened the browser."}]
    result = child(context, "open the browser", mode="reply_crash")
    assert result.returncode == 76, result.stderr


@then("the recovered context has one complete exchange and preserves the known outcome")
def known_recovery(context):
    data = repository(context).inspect(child_sid(context))
    assert data["executions"][0]["status"] == "ok"
    assert len(data["executions"]) == 1
    assert len([m for m in data["checkpoint"]["messages"] if m["role"] == "user" and m["content"] == "open the browser"]) == 1
    assert len([m for m in data["checkpoint"]["messages"] if m["role"] == "tool"]) == 1
    assert "fresh instruction" in context.child_result["reply"] and not context.requests


@when("real streaming recognition accepts the speech fixture through the capture pump")
def real_audio_capture(context):
    import wave
    from agavai.config import AsrConfig
    from agavai.meter import ParecSource
    context.cfg.asr = AsrConfig()
    context.cfg.small_brain = context.cfg.large_brain
    if os.environ.get("AGAVAI_ASR_TEST_MODEL_DIR"):
        context.cfg.asr.model_dir = Path(os.environ["AGAVAI_ASR_TEST_MODEL_DIR"])
    if not (context.cfg.asr.model_dir / "encoder.onnx").is_file():
        context.scenario.skip("Install the Parakeet speech test assets first.")
        return
    fixture = Path("features/fixtures/asr-sentence.wav")
    with wave.open(str(fixture)) as wav:
        pcm = wav.readframes(wav.getnframes()) + bytes(64000)
    source = context.runtime_dir / "fixture.pcm"
    source.write_bytes(pcm)
    # Keep the pipe open until native EOU; only the microphone source is replaced.
    capture = "import sys,time; sys.stdout.buffer.write(open(sys.argv[1],'rb').read()); sys.stdout.buffer.flush(); time.sleep(15)"
    complete = False
    collect = context.harness.output.sink
    def stop_after_reply(event):
        nonlocal complete
        collect(event)
        if event.kind == "task_status" and event.data["status"] == "answered":
            complete = True
    context.harness.output.sink = stop_after_reply
    context.harness.should_cancel = lambda: complete
    with quiet_session(), patch.object(ParecSource, "ARGV", [sys.executable, "-c", capture, str(source)]), patch("agavai.harness.audio._encode", return_value="Fixture retained as WAV."):
        listen_session(context.cfg, harness=context.harness)
    context.saved = repository(context).inspect(context.harness.context.session_id)


@then("the recognized turn and actual captured waveform are durable")
def real_audio_saved(context):
    import wave
    turns = context.saved["turns"]
    assert len(turns) == 1, turns
    assert turns[0]["input"] == "please find the meeting notes from yesterday and open the document in my downloads folder"
    audio = turns[0]["audio"]
    assert audio["status"] == "ready", audio
    path = repository(context).attachment(context.harness.context.session_id, audio["path"])
    with wave.open(str(path)) as wav:
        pcm = wav.readframes(wav.getnframes())
        assert wav.getframerate() == 16000
    assert pcm and pcm in (context.runtime_dir / "fixture.pcm").read_bytes()
    assert audio["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()


@when("the session CLI encounters a corrupt database")
def corrupt_database(context):
    root = context.runtime_dir / "corrupt-sessions"
    root.mkdir()
    (root / "sessions.sqlite3").write_bytes(b"not a SQLite database")
    context.corrupt_result = subprocess.run([sys.executable, "-m", "agavai", "session", "list"],
        env={**os.environ, "AGAVAI_SESSION_DIR": str(root), "XDG_RUNTIME_DIR": str(context.runtime_dir / "cli")},
        capture_output=True, text=True, timeout=10)
    context.corrupt_root = root


@then("the CLI reports the database failure without creating a session")
def corruption_error(context):
    assert context.corrupt_result.returncode == 1
    assert "agavai session:" in context.corrupt_result.stderr and "not a database" in context.corrupt_result.stderr
    assert not (context.corrupt_root / "sessions").exists()
