from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from behave import given, then, when

from agavai.config import Config
from agavai.tts import cue_listen, cue_think, speak


def _cfg(tmp: Path) -> Config:
    cfg = Config()
    cfg.tts.prefer = "kokoro"
    cfg.tts.voice = "af_bella"
    cfg.tts.venv = tmp / "tts-venv"
    cfg.tts.model_path = tmp / "kokoro-v1.0.fp16.onnx"
    cfg.tts.voices_path = tmp / "voices-v1.0.bin"
    return cfg


@given("a kokoro-ready temp config")
def step_ready(context):
    tmp = Path(tempfile.mkdtemp())
    py = tmp / "tts-venv" / "bin" / "python"
    py.parent.mkdir(parents=True)
    py.write_text("#!/bin/sh\nexit 0\n")
    py.chmod(0o755)
    (tmp / "kokoro-v1.0.fp16.onnx").write_bytes(b"onnx")
    (tmp / "voices-v1.0.bin").write_bytes(b"voices")
    context.cfg = _cfg(tmp)
    context.tmp = tmp
    wav_written = {"ok": False}

    def fake_run(argv, **kwargs):
        result = MagicMock()
        result.returncode = 0
        result.stdout = ""
        result.stderr = ""
        argv = [str(a) for a in argv]
        if "--out" in argv:
            out = argv[argv.index("--out") + 1]
            Path(out).write_bytes(b"RIFF" + b"\x00" * 80)
            wav_written["ok"] = True
        return result

    which = patch("agavai.tts.shutil.which", return_value="/usr/bin/pw-play")
    run = patch("agavai.tts.subprocess.run", side_effect=fake_run)
    popen = patch("agavai.tts.subprocess.Popen", return_value=MagicMock())
    ping = patch("agavai.tts._tts_ping", return_value=False)
    sleep = patch("agavai.tts.time.sleep")
    context.which = which.start()
    context.run = run.start()
    context.popen = popen.start()
    ping.start()
    sleep.start()
    context.add_cleanup(which.stop)
    context.add_cleanup(run.stop)
    context.add_cleanup(popen.stop)
    context.add_cleanup(ping.stop)
    context.add_cleanup(sleep.stop)
    context.wav_written = wav_written


@given("a config that prefers kokoro with no assets")
def step_missing(context):
    tmp = Path(tempfile.mkdtemp())
    context.cfg = _cfg(tmp)
    which = patch("agavai.tts.shutil.which", return_value=None)
    which.start()
    context.add_cleanup(which.stop)


@when('I speak "{text}"')
def step_speak(context, text):
    context.engine = speak(text, context.cfg)


@then('the speak engine should be "{name}"')
def step_engine(context, name):
    assert context.engine == name, context.engine


@then('the speak engine should not be "{name}"')
def step_not_engine(context, name):
    assert context.engine != name, context.engine


@when("I cue listen")
def step_cue_listen(context):
    cue_listen(context.cfg)


@when("I cue think")
def step_cue_think(context):
    cue_think(context.cfg)


@then("an earcon should be played")
def step_earcon(context):
    played = False
    for c in list(context.run.call_args_list) + list(context.popen.call_args_list):
        argv = [str(x) for x in c.args[0]]
        if any("pw-play" in p or p.endswith("paplay") for p in argv) and "--media-role" in argv:
            played = True
    assert played, context.popen.call_args_list


@then("the TTS server should be started")
def step_server(context):
    found = False
    for c in context.popen.call_args_list:
        argv = [str(x) for x in c.args[0]]
        if "--serve" in argv:
            found = True
    assert found, context.popen.call_args_list


@then("the synth command should run the TTS venv python")
def step_venv_py(context):
    synth = None
    env = {}
    for c in context.run.call_args_list:
        argv = [str(x) for x in c.args[0]]
        if any("kokoro_synth.py" in p for p in argv):
            synth = argv
            env = c.kwargs.get("env") or {}
            break
    assert synth, context.run.call_args_list
    assert str(context.cfg.tts.venv / "bin" / "python") in synth, synth
    assert "--voice" in synth
    assert context.cfg.tts.voice in synth
    assert env.get("CUDA_VISIBLE_DEVICES") == ""
