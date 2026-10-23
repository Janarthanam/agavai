import math
import os
from pathlib import Path
import signal
import struct
import subprocess
import sys
import tempfile
import time
from unittest.mock import patch

from behave import when, then

from agavai.__main__ import _cancel_path, listen_session
from agavai.asr import rms_dbfs
from agavai.meter import ParecSource


WORKER = """
import json, struct, sys
with open(sys.argv[1], 'wb') as recorded:
    print(json.dumps({'kind': 'ready', 'protocol': 1, 'native_endpoint': True}), flush=True)
    while header := sys.stdin.buffer.read(4):
        size = struct.unpack('>I', header)[0]
        frame = sys.stdin.buffer.read(size)
        kind, uid = struct.unpack('>cI', frame[:5])
        if kind == b'A':
            recorded.write(frame[5:])
            recorded.flush()
        elif kind == b'C':
            print(json.dumps({'kind': 'cancelled', 'utterance_id': uid}), flush=True)
"""
CAPTURE = """
import sys, time
with open(sys.argv[1], 'rb') as audio:
    while packet := audio.read(640):
        sys.stdout.buffer.write(packet)
        sys.stdout.buffer.flush()
        time.sleep(0.02)
"""


def capture(context, *, cancel=False, empty=False, vad=False):
    model = context.runtime_dir / "model"
    model.mkdir()
    for name in ("encoder.onnx", "decoder_joint.onnx", "vocab.txt"):
        (model / name).touch()
    context.cfg.asr.model_dir = model
    context.cfg.asr.venv = Path(sys.executable).resolve().parents[1]
    context.audio = b"" if empty else bytes(6400) + struct.pack("<h", 8192) * 3840 + bytes(6400)
    if vad:
        context.cfg.asr.backend, context.cfg.asr.endpoint = "whistle-cactus", "vad"
        context.cfg.asr.model_path, context.cfg.asr.runtime_library = model / "whistle.cact", model / "libneedle.so"
        context.cfg.asr.model_path.touch()
        context.cfg.asr.runtime_library.touch()
        context.audio += struct.pack("<h", 42)
    audio = context.runtime_dir / "mic.pcm"
    audio.write_bytes(context.audio)
    context.recorded = context.runtime_dir / "worker.pcm"
    context.levels = []
    context.capture_count = 0
    spawn = subprocess.Popen
    publish_level = context.ui.level

    def level(db, vad_state, vad_backend):
        context.levels.append((time.monotonic(), db))
        publish_level(db, vad_state, vad_backend)
        if cancel and len(context.levels) == 3:
            _cancel_path(context.cfg).touch()
            os.kill(os.getpid(), signal.SIGTERM)

    def popen(argv, **kwargs):
        if argv[0] == "parec":
            context.capture_count += 1
            return spawn([sys.executable, "-c", CAPTURE, str(audio)], **kwargs)
        assert Path(argv[1]).name == "asr_worker.py", argv
        return spawn([sys.executable, "-c", WORKER, str(context.recorded)], **kwargs)

    with patch("agavai.asr.subprocess.Popen", side_effect=popen), patch("agavai.asr.shutil.which", return_value="/usr/bin/parec"), patch("agavai.__main__.prepare_listen"), patch("agavai.__main__.cue_listen"), patch("agavai.__main__.cue_start"), patch("agavai.__main__.finish"), patch("agavai.__main__._publish_pid"), patch("agavai.tts.sweep_playback_wavs"), patch.object(context.ui, "level", side_effect=level), patch("agavai.__main__._run_stop_body") as submit:
        context.listen_result = listen_session(context.cfg, context.ui)
        context.submit_count = submit.call_count


@when("streaming capture receives silence and speech without recognition output")
def captured(context):
    capture(context)


@when("VAD capture receives audio ending in a short frame")
def vad_tail(context):
    capture(context, vad=True)


@when("I cancel streaming capture after microphone levels arrive")
def cancelled(context):
    capture(context, cancel=True)


@when("streaming capture ends before any microphone audio arrives")
def empty(context):
    capture(context, empty=True)


@then("the orb receives silent and audible microphone levels at most 10 times per second")
def levels(context):
    assert len(context.levels) >= 3, context.levels
    assert context.levels[0][1] == -100.0, context.levels
    assert any(-12.1 < db < -12.0 for _, db in context.levels), context.levels
    assert context.levels[-1][1] == -100.0, context.levels
    assert all(b[0] - a[0] >= 0.099 for a, b in zip(context.levels, context.levels[1:])), context.levels
    assert context.ui.data["transcript"]["text"] == ""


@then("recognition and metering use one unchanged audio stream")
def same_capture(context):
    assert context.capture_count == 1, context.capture_count
    assert context.recorded.read_bytes() == context.audio


@then("no microphone levels are published")
def no_levels(context):
    assert context.levels == [], context.levels


@when("I convert PCM to dBFS")
def pcm_dbfs(context):
    sine = b"".join(struct.pack("<h", int(32767 * math.sin(2 * math.pi * i / 32))) for i in range(320))
    context.silence_db = rms_dbfs(bytes(640))
    context.sine_db = rms_dbfs(sine)


@then("silence should be -100 dBFS")
def silence_db(context):
    assert context.silence_db == -100.0, context.silence_db


@then("a full-scale sine should be near -3 dBFS")
def sine_db(context):
    assert -3.2 < context.sine_db < -2.8, context.sine_db


@then('the parec argv should use "{flag}" for "{target}"')
def parec_argv(context, flag, target):
    assert flag in ParecSource.ARGV and target in ParecSource.ARGV, ParecSource.ARGV
    assert "--target=@DEFAULT_SOURCE@" not in " ".join(ParecSource.ARGV), ParecSource.ARGV


@when("I check the native orb animation without desktop capture")
def native_orb(context):
    root = Path(__file__).resolve().parents[2]
    with tempfile.TemporaryDirectory(prefix="agavai-orb-") as directory:
        runtime = Path(directory)
        (runtime / "Assistant").symlink_to(root / "plugin", target_is_directory=True)
        test = runtime / "tst_orb.qml"
        test.write_text((root / "features/support/orb-ui.qml").read_text())
        env = dict(os.environ, XDG_RUNTIME_DIR=directory, QT_QPA_PLATFORM="offscreen", QT_QUICK_BACKEND="software", QT_QPA_PLATFORMTHEME="basic", QT_STYLE_OVERRIDE="Fusion")
        context.orb_result = subprocess.run(
            ["/usr/lib/qt6/bin/qmltestrunner", "-input", str(test)],
            env=env, text=True, capture_output=True, timeout=20,
        )


@then("the native orb animation check passes")
def native_pass(context):
    result = context.orb_result
    assert result.returncode == 0, result.stdout + result.stderr
