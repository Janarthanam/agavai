from __future__ import annotations

import json
import math
import os
import signal
import struct
import tempfile
import wave
from pathlib import Path
from unittest.mock import patch

from behave import given, then, when

from agavai.harness.session import _cancel_path, _record_request_path, listen_session
from agavai.__main__ import main
from agavai.canvas import display_for, model_view
from agavai.recording import correct, line_text
from agavai.state import write_state
from agavai.tools import call_tool
from agavai.ui import cancel_ui


def _tone(ms: int) -> bytes:
    count = 16 * ms
    return b"".join(struct.pack("<h", int(3000 * math.sin(2 * math.pi * 440 * i / 16000))) for i in range(count))


def _send(context, action: str) -> None:
    """What `agavai record <action>` does to a running listener."""
    with _record_request_path(context.cfg).open("a") as requests:
        requests.write(action + "\n")
    os.kill(os.getpid(), signal.SIGUSR1)


class _ContinuousScript:
    """Continuous recognizer stand-in: plays audio, worker messages, and user actions in order."""

    def __init__(self, context, script: str) -> None:
        self.context = context
        self.ops = [line.split(" ", 1) for line in script.strip().splitlines() if line.strip()]

    def record(self, on_audio, should_stop):
        context = self.context
        for op, *rest in self.ops:
            if should_stop():
                return
            arg = rest[0] if rest else ""
            if op == "audio":
                for _ in range(int(arg) // 100):
                    on_audio(_tone(100))
            elif op in {"interim", "eob"}:
                yield {"kind": op, "text": arg}
            elif op == "eou":
                start, end, text = arg.split(" ", 2)
                yield {"kind": "eou", "text": text, "start_ms": int(start), "end_ms": int(end)}
            elif op == "asr_lost":
                yield {"kind": "asr_lost"}
            elif op == "peek":
                context.peeks.append(json.loads((context.runtime_dir / "ui.json").read_text()))
            elif op == "request":
                _send(context, arg)
                yield {"kind": "level", "db": -30.0}
            elif op == "sigterm":
                os.kill(os.getpid(), signal.SIGTERM)
                yield {"kind": "level", "db": -30.0}
            elif op == "dismiss":
                cancel_ui(context.cfg)
                _cancel_path(context.cfg).touch()
                os.kill(os.getpid(), signal.SIGTERM)
                yield {"kind": "level", "db": -30.0}
            else:
                raise AssertionError(f"unknown script step {op!r}")

    def close(self):
        return None


class _AssistantScript:
    """Assistant recognizer stand-in: each events() call plays the next utterance; callables run in place."""

    def __init__(self, utterances) -> None:
        self.utterances = list(utterances)

    def events(self, on_level, should_stop=None, should_cancel=None, audio_tap=None):
        for item in self.utterances.pop(0) if self.utterances else []:
            if callable(item):
                item()
            else:
                yield item

    def close(self):
        return None


def _quiet_session():
    """Hardware, chimes, and the assistant turn are not what these scenarios check."""
    return [
        patch("agavai.harness.session.prepare_listen"),
        patch("agavai.harness.session.finish"),
        patch("agavai.harness.session.cue_record"),
        patch("agavai.harness.session.cue_start"),
        patch("agavai.harness.session.cue_listen"),
        patch("agavai.harness.session._publish_pid"),
        patch("agavai.harness.session.speak"),
        patch("agavai.tts.sweep_playback_wavs"),
    ]


def _run(context, patches):
    for item in patches:
        item.start()
    try:
        return listen_session(context.cfg, harness=context.harness, record=True)
    finally:
        for item in reversed(patches):
            item.stop()


def _folders(context) -> list[Path]:
    root = context.cfg.recordings.dir
    return sorted(path for path in root.iterdir() if path.is_dir()) if root.is_dir() else []


def _meta(folder: Path) -> dict:
    return json.loads((folder / "recording.json").read_text())


def _snapshot(context) -> dict:
    return json.loads((context.runtime_dir / "ui.json").read_text())


@given("recordings are kept in a temp folder")
def step_folder(context):
    context.cfg.recordings.dir = Path(tempfile.mkdtemp()) / "Recordings"
    context.peeks = []


@given("ffmpeg is not installed")
def step_no_ffmpeg(context):
    context.no_ffmpeg = True


@given("a recording a crash left with 1.5 seconds of audio and a cut-off journal")
def step_crashed(context):
    folder = context.cfg.recordings.dir / "2026-01-01 09.00 Recording"
    folder.mkdir(parents=True)
    meta = {"title": "Recording", "started": "2026-01-01T09:00:00", "status": "recording", "audio": "audio.wav",
            "duration_ms": 0, "segments": [], "marks": [], "pauses": []}
    (folder / "recording.json").write_text(json.dumps(meta))
    with wave.open(str(folder / "audio.wav"), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(_tone(1000))
    # Audio that reached the disk after the last header update.
    with (folder / "audio.wav").open("ab") as wav_file:
        wav_file.write(_tone(500))
    segment = {"id": 1, "start_ms": 0, "end_ms": 900, "live": "before the crash"}
    (folder / "segments.jsonl").write_text(json.dumps({"segment": segment}) + '\n{"segment": {"id": 2, "st')
    context.crashed = folder


@when("I record while the microphone hears")
def step_record(context):
    script = _ContinuousScript(context, context.text)
    patches = _quiet_session() + [patch("agavai.harness.session.open_stream", return_value=script)]
    if getattr(context, "no_ffmpeg", False):
        patches.append(patch("agavai.recording.shutil.which", return_value=None))
    context.listen_result = _run(context, patches)


@when('I correct line {segment:d} to "{text}"')
def step_correct(context, segment, text):
    context.folder = _folders(context)[0]
    correct(context.folder, segment, text)


@when("the assistant is listening and a recording is toggled on and then off")
def step_assistant_toggle(context):
    assistant = _AssistantScript([[lambda: _send(context, "toggle"), ("interim", "hello")], []])
    recording = _ContinuousScript(context, "audio 1000\nrequest toggle")
    context.streams = []

    def open_stream(cfg, *, continuous=False):
        context.streams.append(continuous)
        return recording if continuous else assistant

    patches = _quiet_session() + [patch("agavai.harness.session.open_stream", side_effect=open_stream),
                                  patch("agavai.harness.session._run_stop_body", return_value="Done")]
    for item in patches:
        item.start()
    try:
        context.listen_result = listen_session(context.cfg, harness=context.harness)
    finally:
        for item in reversed(patches):
            item.stop()


def _record_cmd_idle(context, argv):
    with patch("agavai.__main__.load_config", return_value=context.cfg), patch("agavai.__main__.write_card"), \
            patch("agavai.harness.session.read_listener", return_value=None), \
            patch("agavai.app.summon_overlay", return_value=True), \
            patch("agavai.app.read_listener", return_value=None), \
            patch("agavai.app.start_session", return_value=True) as start:
        context.exit_code = main(argv)
        context.start_calls = start.call_args_list


@when('the assistant hears "{text}" and the model starts a recording')
def step_voice_start(context, text):
    assistant = _AssistantScript([[("eou", text)], []])
    recording = _ContinuousScript(context, "audio 1000\nrequest toggle")
    context.streams = []

    def open_stream(cfg, *, continuous=False):
        context.streams.append(continuous)
        return recording if continuous else assistant

    def model_turn(cfg, ui, stop_requested, *, continue_conversation=False, text="", harness=None, audio=None):
        # The model's tool call; its spoken reply comes before the recording starts.
        context.tool_result = call_tool("start_recording", {}, cfg)
        return "Recording."

    def no_process(*_args, **_kwargs):
        raise AssertionError("a voice start must reuse this session, not start a process")

    patches = _quiet_session() + [
        patch("agavai.harness.session.open_stream", side_effect=open_stream),
        patch("agavai.harness.session._run_stop_body", side_effect=model_turn),
        patch("agavai.harness.session.read_listener", return_value=os.getpid()),
        patch("agavai.harness.session.start_session", side_effect=no_process),
    ]
    for item in patches:
        item.start()
    try:
        context.listen_result = listen_session(context.cfg, harness=context.harness)
    finally:
        for item in reversed(patches):
            item.stop()
    assert context.tool_result.startswith("Recording starts"), context.tool_result


@given('a saved recording "{title}" from "{started}" lasting {seconds:d} seconds')
def step_saved_recording(context, title, started, seconds):
    folder = context.cfg.recordings.dir / f"{started} {title}"
    folder.mkdir(parents=True)
    (folder / "recording.json").write_text(json.dumps({
        "title": title, "started": started, "status": "ready", "audio": "audio.opus",
        "duration_ms": seconds * 1000, "segments": [], "marks": [], "pauses": []}))


@when("the assistant lists the recordings")
def step_list_recordings(context):
    context.listed = call_tool("list_recordings", {}, context.cfg)


@then("the canvas lists the recordings")
def step_canvas_recordings(context):
    block = display_for("list_recordings", context.listed)
    assert block["kind"] == "recordings", block
    rows = [{"title": item["title"], "subtitle": item["subtitle"]} for item in block["items"]]
    assert rows == [dict(row.items()) for row in context.table], rows
    assert all(Path(item["path"]).parent == context.cfg.recordings.dir for item in block["items"]), block


@then("the model hears the recordings by title, without their folders")
def step_model_recordings(context):
    text = model_view("list_recordings", context.listed)
    assert "Lecture" in text and str(context.cfg.recordings.dir) not in text, text


def _correct_cmd(context, folder: Path, line: int, text: str):
    with patch("agavai.__main__.load_config", return_value=context.cfg), patch("agavai.__main__.write_card"):
        context.exit_code = main(["recording", "correct", str(folder), str(line), text])


@when('the overlay corrects line {line:d} to "{text}" through the command line')
def step_correct_cmd(context, line, text):
    _correct_cmd(context, _folders(context)[0], line, text)


@when("the overlay corrects a line in a folder outside the recordings folder")
def step_correct_outside(context):
    outside = Path(tempfile.mkdtemp())
    (outside / "recording.json").write_text(json.dumps({"segments": [{"id": 1, "live": "x"}]}))
    _correct_cmd(context, outside, 1, "changed")
    assert "changed" not in (outside / "recording.json").read_text()


@when('I run "agavai record" with nothing running')
def step_record_cmd_idle(context):
    _record_cmd_idle(context, ["record"])


@when('I run "agavai record {action}" with nothing running')
def step_record_cmd_idle_action(context, action):
    _record_cmd_idle(context, ["record", action])


@when('I run "agavai record {action}" while a recording is running')
def step_record_cmd_running(context, action):
    write_state(context.cfg, "recording")
    with patch("agavai.__main__.load_config", return_value=context.cfg), patch("agavai.__main__.write_card"), \
            patch("agavai.harness.session.read_listener", return_value=4242), \
            patch("agavai.harness.session.os.kill") as kill:
        context.exit_code = main(["record", action])
        context.kills = kill.call_args_list


@when('I run "agavai record" while a listener is still starting')
def step_record_cmd_starting(context):
    write_state(context.cfg, "idle")
    with patch("agavai.__main__.load_config", return_value=context.cfg), patch("agavai.__main__.write_card"), \
            patch("agavai.harness.session.read_listener", return_value=4242), \
            patch("agavai.harness.session.os.kill") as kill:
        context.exit_code = main(["record"])
        context.kills = kill.call_args_list


@then('while recording the overlay showed the partial "{text}"')
def step_peek_partial(context, text):
    assert any(peek.get("recording", {}).get("partial") == text and peek["phase"] == "recording"
               for peek in context.peeks), context.peeks


@then('while recording the overlay showed the line "{time}" "{text}"')
def step_peek_line(context, time, text):
    assert any({"time": time, "text": text} in peek.get("recording", {}).get("lines", [])
               for peek in context.peeks), context.peeks


@then("while recording the overlay showed that the live transcript stopped")
def step_peek_lost(context):
    assert any(peek.get("recording", {}).get("transcribing") is False for peek in context.peeks), context.peeks


@then("the recording is saved with its audio compressed")
def step_saved(context):
    folders = _folders(context)
    assert len(folders) == 1, folders
    context.folder = folders[0]
    meta = _meta(context.folder)
    assert meta["status"] == "ready" and meta["audio"] == "audio.opus", meta
    for name in ("audio.opus", "recording.json", "transcript.md"):
        assert (context.folder / name).is_file(), name
    for name in ("audio.wav", "segments.jsonl"):
        assert not (context.folder / name).exists(), name


@then("the recording lasts {seconds:g} seconds")
def step_duration(context, seconds):
    context.folder = _folders(context)[0]
    assert _meta(context.folder)["duration_ms"] == int(seconds * 1000), _meta(context.folder)["duration_ms"]


@then("the recording keeps these lines")
def step_lines(context):
    context.folder = _folders(context)[0]
    lines = [{"start_ms": str(s["start_ms"]), "text": line_text(s)} for s in _meta(context.folder)["segments"]]
    expected = [{"start_ms": row["start_ms"], "text": row["text"]} for row in context.table]
    assert lines == expected, lines


@then("the recording pauses at {at:d} ms")
def step_pauses(context, at):
    assert _meta(_folders(context)[0])["pauses"] == [at], _meta(_folders(context)[0])


@then("the recording keeps marks at {first:d} and {second:d} ms")
def step_marks(context, first, second):
    marks = [mark["at_ms"] for mark in _meta(_folders(context)[0])["marks"]]
    assert marks == [first, second], marks


@then('the transcript file lists "{line}"')
def step_transcript(context, line):
    text = (_folders(context)[0] / "transcript.md").read_text()
    assert line in text.splitlines(), text


@then("the overlay shows the saved recording for review")
def step_review(context):
    data = _snapshot(context)
    display = data.get("display") or {}
    assert display.get("kind") == "recording" and display.get("path") == str(_folders(context)[0]), display
    assert "recording" not in data, data


@then("the overlay does not show the saved recording")
def step_no_review(context):
    assert (_snapshot(context).get("display") or {}).get("kind") != "recording", _snapshot(context)


@then('the snapshot shows the error "{text}"')
def step_error(context, text):
    data = _snapshot(context)
    assert data["phase"] == "error" and data.get("error") == text, data


@then("no recording folder is left")
def step_no_folder(context):
    assert _folders(context) == [], _folders(context)


@then("the recording keeps its uncompressed audio and says why")
def step_uncompressed(context):
    folder = _folders(context)[0]
    meta = _meta(folder)
    assert meta["audio"] == "audio.wav" and "ffmpeg" in meta["audio_error"], meta
    assert (folder / "audio.wav").is_file() and not (folder / "audio.opus").exists()


@then("the interrupted recording is finished and marked recovered")
def step_recovered(context):
    meta = _meta(context.crashed)
    assert meta["status"] == "ready" and meta["recovered"] is True, meta
    assert meta["duration_ms"] == 1500 and meta["audio"] == "audio.opus", meta
    assert not (context.crashed / "segments.jsonl").exists()


@then('the interrupted recording keeps its line "{text}"')
def step_recovered_line(context, text):
    assert [line_text(s) for s in _meta(context.crashed)["segments"]] == [text], _meta(context.crashed)


@then('line {segment:d} still keeps what was heard, "{text}"')
def step_heard(context, segment, text):
    line = _meta(context.folder)["segments"][segment - 1]
    assert line["live"] == text, line


@then("line {segment:d} has no correction")
def step_uncorrected(context, segment):
    line = _meta(context.folder)["segments"][segment - 1]
    assert "corrected" not in line, line


@then("the assistant went back to listening with the review on screen")
def step_back_to_assistant(context):
    assert context.streams == [False, True], context.streams
    data = _snapshot(context)
    assert data["phase"] == "listening" and (data.get("display") or {}).get("kind") == "recording", data


@then("the recording session ended")
def step_session_ended(context):
    assert context.listen_result == 0, context.listen_result


@then("a detached recording session was started")
def step_detached(context):
    assert context.exit_code == 0, context.exit_code
    assert [call.kwargs for call in context.start_calls] == [{"record": True}], context.start_calls


@then('the running recording was asked to "{action}"')
def step_asked(context, action):
    assert _record_request_path(context.cfg).read_text().split() == [action]
    assert [call.args for call in context.kills] == [(4242, signal.SIGUSR1)], context.kills


@then("no listener was signalled")
def step_not_signalled(context):
    assert context.kills == [], context.kills
