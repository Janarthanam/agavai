import os
import signal
from types import SimpleNamespace
from unittest.mock import patch

from behave import when, then
from agavai import app
from agavai.__main__ import _cancel_path, listen_session, start_session
from agavai.asr import AsrError
from agavai.ui import summon_overlay
from agavai.meter import _select_read


class _Scripted:
    """Recognizer stand-in. Each events() call plays the next scripted utterance."""

    def __init__(self, sequences, on_open=None):
        self.sequences = [list(seq) for seq in sequences]
        self.on_open = on_open

    def events(self, should_stop=None):
        if self.on_open:
            self.on_open()
        seq = self.sequences.pop(0) if self.sequences else []
        for item in seq:
            if callable(item):
                item()
                continue
            yield item

    def close(self):
        return None


@when('I invoke Agavai while it is "{phase}"')
def invoke(context, phase):
    with patch("agavai.app.load_config", return_value=context.cfg), patch("agavai.app.read_state", return_value=phase), patch("agavai.app.summon_overlay", return_value=True) as summon, patch("agavai.app.start_session", return_value=True) as start:
        context.invoke_result = app.run()
        context.summon_count = summon.call_count
        context.start_calls = start.call_args_list


@when("I invoke Agavai without an available shell")
def unavailable(context):
    with patch("agavai.app.load_config", return_value=context.cfg), patch("agavai.app.summon_overlay", return_value=False), patch("agavai.app.start_session") as start:
        context.invoke_result = app.run()
        context.start_calls = start.call_args_list


@then("the shared overlay is summoned once")
def shared(context):
    assert context.summon_count == 1


@then("one automatic listening session is requested")
def automatic(context):
    assert len(context.start_calls) == 1 and context.start_calls[0].kwargs == {"automatic": True}


@then("no new listening session is requested")
def no_session(context):
    assert not context.start_calls


@then("invocation reports failure")
def failure(context):
    assert context.invoke_result == 1


@when("the Omarchy shell accepts the overlay invocation")
def accept(context):
    with patch("agavai.ui.shutil.which", return_value="/usr/bin/omarchy"), patch("agavai.ui.subprocess.run", return_value=SimpleNamespace(returncode=0)) as run:
        assert summon_overlay()
        context.shell_calls = run.call_count


@then("the shell invocation launches exactly once")
def once(context):
    assert context.shell_calls == 1


@when("I launch an automatic session with manual capture configured")
def auto_manual(context):
    context.cfg.vad.enabled = False
    with patch("agavai.__main__.read_listener", return_value=None), patch("agavai.__main__._publish_pid"), patch("agavai.__main__.subprocess.Popen", return_value=SimpleNamespace(pid=987654)) as spawn:
        assert start_session(context.cfg, automatic=True)
        context.auto_command = spawn.call_args.args[0]


@then("the detached command uses automatic listening")
def command(context):
    assert context.auto_command[-1] == "listen"


def session(context, sequences, stop_body=None):
    # Mock the hardware, the recognizer, and speech. Turn taking is the scripted
    # end-of-utterance marker, Enter, or Escape — not a silence timer.
    scripted = _Scripted(sequences)

    def default_stop(*_args, **_kwargs):
        return "Done"

    with patch("agavai.__main__.prepare_listen"), patch("agavai.__main__.cue_listen"), patch("agavai.__main__.finish"), patch("agavai.__main__._publish_pid"), patch("agavai.__main__.speak"), patch("agavai.tts.sweep_playback_wavs"), patch("agavai.__main__.open_stream", return_value=scripted), patch("agavai.__main__._run_stop_body", side_effect=stop_body or default_stop) as submit:
        context.listen_result = listen_session(context.cfg, context.ui)
        context.submit_count = submit.call_count
        context.submit_calls = submit.call_args_list


@when("an automatic session hears speech and an end of utterance")
def speech(context):
    session(context, [[("interim", "find the notes"), ("eou", "find the notes")]])


@when("an automatic session has no microphone")
def missing(context):
    class _Down:
        def events(self, should_stop=None):
            raise AsrError("Microphone input is unavailable. Check your input device and try again.")
            yield None

        def close(self):
            return None

    scripted = _Down()
    with patch("agavai.__main__.prepare_listen"), patch("agavai.__main__.cue_listen"), patch("agavai.__main__.finish"), patch("agavai.__main__._publish_pid"), patch("agavai.__main__.speak"), patch("agavai.tts.sweep_playback_wavs"), patch("agavai.__main__.open_stream", return_value=scripted), patch("agavai.__main__._run_stop_body", return_value="Done") as submit:
        context.listen_result = listen_session(context.cfg, context.ui)
        context.submit_count = submit.call_count


@when("an automatic session hears only silence")
def silence(context):
    session(context, [[]])


@when("an automatic session hears only an interim hypothesis")
def interim(context):
    session(context, [[("interim", "find the notes")]])


@when("an automatic session hears an empty end of utterance")
def empty_eou(context):
    session(context, [[("eou", "")], []])


@when("an automatic session hears an end of boundary")
def boundary(context):
    session(context, [[("interim", "find the"), ("eob", "find the notes")]])


@when("an automatic session hears an interim and Enter")
def enter(context):
    def press_enter():
        os.kill(os.getpid(), signal.SIGTERM)

    session(context, [[("interim", "find the notes"), press_enter]])


@when("an automatic session hears an interim and Escape")
def escape(context):
    def press_escape():
        _cancel_path(context.cfg).touch()
        os.kill(os.getpid(), signal.SIGTERM)

    session(context, [[("interim", "find the notes"), press_escape]])


@then('the submitted line is "{text}"')
def submitted(context, text):
    assert context.submit_calls, "no submission"
    assert context.submit_calls[0].kwargs.get("text") == text, context.submit_calls[0]


@then("the voice request is submitted once")
def sent(context):
    assert context.submit_count == 1


@then("the voice request is not submitted")
def not_sent(context):
    assert context.submit_count == 0


def _choice_session(context, sequences, replies):
    context.phases = []
    context.continued = []

    def opened():
        context.phases.append(context.ui.data.get("phase"))

    def stop_body(cfg, ui, stop_requested, continue_conversation=False, text=""):
        context.continued.append(continue_conversation)
        reply = replies.pop(0)
        ui.assistant(reply)
        ui.display({"kind": "files", "title": "Images", "items": [
            {"id": "0", "kind": "image", "title": "Ship At Sea", "path": "/tmp/ship-at-sea.jpg"}
        ]})
        return reply

    scripted = _Scripted(sequences, on_open=opened)
    with patch("agavai.__main__.prepare_listen"), patch("agavai.__main__.cue_listen"), patch("agavai.__main__.finish"), patch("agavai.__main__._publish_pid"), patch("agavai.__main__.speak"), patch("agavai.tts.sweep_playback_wavs"), patch("agavai.__main__.open_stream", return_value=scripted), patch("agavai.__main__._run_stop_body", side_effect=stop_body):
        context.listen_result = listen_session(context.cfg, context.ui)
        context.submit_count = len(context.continued)


@when("an automatic session is asked to choose a screensaver image and then hears silence")
def choice_then_silence(context):
    _choice_session(
        context,
        [[("eou", "show me screensavers")], []],
        ["set the image you want as your screensaver"],
    )


@when("an automatic session hears a screensaver choice and then an answer")
def choice_then_answer(context):
    _choice_session(
        context,
        [[("eou", "show me screensavers")], [("eou", "ship at sea")]],
        ["set the image you want as your screensaver", "Wallpaper set to ship at sea."],
    )


@then("the follow-up listen started")
def follow_started(context):
    assert context.phases == ["listening", "listening"], context.phases


@then("the follow-up kept the shown images")
def kept_images(context):
    import json

    data = json.loads((context.runtime_dir / "ui.json").read_text())
    assert data["phase"] == "listening", data["phase"]
    assert data["display"]["title"] == "Images", data.get("display")
    assert "screensaver" in data["turns"][-1]["assistant"]


@then("the voice turns continued as")
def continued_as(context):
    expected = [row["continued"] == "true" for row in context.table]
    assert context.continued == expected, context.continued


@when("the microphone stream stalls")
def stall(context):
    stream = SimpleNamespace(fileno=lambda: 123)
    with patch("agavai.meter.time.monotonic", side_effect=[0, 2]), patch("agavai.meter.select.select") as select:
        context.stalled_result = _select_read(stream, 20)(640)
        assert not select.called


@then("the source ends rather than waiting for another shortcut")
def ends(context):
    assert context.stalled_result == b""
