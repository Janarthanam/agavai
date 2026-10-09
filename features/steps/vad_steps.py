from __future__ import annotations

import math
import struct

from behave import given, then, when

from agavai.config import Config, load_config
from agavai.meter import AcousticResult, Endpointer, ParecSource, frame_iter, make_backend, rms_dbfs

FRAME = 640


def _sine_dbfs(amplitude: int = 32767, frames: int = 8) -> float:
    buf = b"".join(
        struct.pack("<h", int(amplitude * math.sin(2 * math.pi * i / 32)))
        for i in range(160 * frames)
    )
    return rms_dbfs(buf[:FRAME])


class BackendFake:
    """Scripted VadBackend: dB or speech/non-speech per frame."""

    def __init__(self, script: list[str]) -> None:
        self.script = script
        self.pos = 0

    def feed(self, frame: bytes) -> AcousticResult:
        kind = self.script[min(self.pos, len(self.script) - 1)]
        self.pos += 1
        if kind == "speech":
            return AcousticResult("speech")
        return AcousticResult("non_speech")

    def reset(self) -> None:
        self.pos = 0

    def close(self) -> None:
        return None


def _endpointer(context, silence_ms: int) -> Endpointer:
    cfg = Config()
    cfg.vad.silence_ms = silence_ms
    return Endpointer(cfg.vad, backend=BackendFake([]))


@given("an endpointer with silence window {ms:d} ms")
def step_ep(context, ms):
    context.ep = _endpointer(context, ms)
    context.result = None


def _run(context, speech_ms: int, silence_ms: int) -> None:
    ep = context.ep
    ep.backend = BackendFake(["speech"] * (speech_ms // 20))
    for _ in range(speech_ms // 20):
        context.result = ep.feed(b"\x00" * FRAME) or context.result
    ep.backend = BackendFake(["silence"] * (silence_ms // 20 + 5))
    for _ in range(silence_ms // 20 + 5):
        out = ep.feed(b"\x00" * FRAME)
        if out:
            context.result = out
            return


@when("speech runs for {speech_ms:d} seconds then silence runs for {silence_ms:d} ms")
def step_speech_silence(context, speech_ms, silence_ms):
    _run(context, speech_ms * 1000, silence_ms)


@when("speech runs for {speech_ms:d} ms then silence runs for {silence_ms:d} ms")
def step_speech_silence_ms(context, speech_ms, silence_ms):
    _run(context, speech_ms, silence_ms)


@when("speech runs for {n:d} seconds")
def step_speech(context, n):
    ep = context.ep
    ep.backend = BackendFake(["speech"] * 2000)
    for _ in range(n * 50):
        out = ep.feed(b"\x00" * FRAME)
        if out:
            context.result = out
            return


@when("silence runs for {n:d} seconds")
def step_silence(context, n):
    ep = context.ep
    ep.backend = BackendFake(["silence"] * 2000)
    for _ in range(n * 50):
        out = ep.feed(b"\x00" * FRAME)
        if out:
            context.result = out
            return


@when("I convert PCM to dBFS")
def step_pcm(context):
    context.silence_db = rms_dbfs(bytes(FRAME))
    context.sine_db = _sine_dbfs()


@when("I frame a 1500-byte read stream")
def step_frame(context):
    blob = bytes(range(256)) * 6
    blob = blob[:1500]
    pos = 0

    def read(n: int) -> bytes:
        nonlocal pos
        chunk = blob[pos : pos + n]
        pos += n
        return chunk

    context.frames = list(frame_iter(read, FRAME))
    context.tail = blob[len(context.frames) * FRAME :]


@when("a read stream times out before data arrives")
def step_read_timeout(context):
    script = iter([None, None, b"\x00" * FRAME, None, b""])
    context.frames = list(frame_iter(lambda n: next(script, b""), FRAME))


@then("the reader should have produced a frame")
def step_produced(context):
    assert [len(f) for f in context.frames] == [FRAME], context.frames


@when("I resolve the vad backend")
def step_resolve(context):
    cfg = getattr(context, "cfg", None) or Config()
    if getattr(context, "config_path", None):
        cfg = load_config(context.config_path)
    _, context.resolved = make_backend(cfg.vad)


@then("silence should be -100 dBFS")
def step_silence_db(context):
    assert context.silence_db == -100.0, context.silence_db


@then("a full-scale sine should be near -3 dBFS")
def step_sine_db(context):
    assert -3.2 < context.sine_db < -2.8, context.sine_db


@then("there should be {n:d} full frames")
def step_frames(context, n):
    assert len(context.frames) == n, len(context.frames)
    assert all(len(f) == FRAME for f in context.frames)


@then("the tail should be {n:d} bytes")
def step_tail(context, n):
    assert len(context.tail) == n, len(context.tail)


@then('the parec argv should use "{flag}" for "{target}"')
def step_argv(context, flag, target):
    argv = ParecSource.ARGV
    assert flag in argv and target in argv, argv
    assert "--target=@DEFAULT_SOURCE@" not in " ".join(argv), argv


@then('the endpointer should report "{want}"')
def step_report(context, want):
    assert context.result == want, context.result


@then("the endpointer should report nothing")
def step_report_none(context):
    assert context.result is None, context.result


@then('the resolved backend should be "{want}"')
def step_resolved(context, want):
    assert context.resolved == want, context.resolved
