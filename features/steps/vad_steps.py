from __future__ import annotations

import json
import os
from pathlib import Path
import wave

from behave import given, then, when

from agavai.config import Config, load_config
from agavai.meter import AcousticResult, Endpointer, frame_iter, make_backend, streaming_endpointer

AUDIO = Path(__file__).resolve().parents[2] / "evals" / "audio"

FRAME = 640


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




@then("there should be {n:d} full frames")
def step_frames(context, n):
    assert len(context.frames) == n, len(context.frames)
    assert all(len(f) == FRAME for f in context.frames)


@then("the tail should be {n:d} bytes")
def step_tail(context, n):
    assert len(context.tail) == n, len(context.tail)



@then('the endpointer should report "{want}"')
def step_report(context, want):
    assert context.result == want, context.result


@then("the endpointer should report nothing")
def step_report_none(context):
    assert context.result is None, context.result


@then('the resolved backend should be "{want}"')
def step_resolved(context, want):
    assert context.resolved == want, context.resolved


@given("the streaming VAD uses the installed Silero model with a {ms:d} ms quiet window")
def step_silero_installed(context, ms):
    cfg = load_config().vad
    cfg.backend = "silero"
    cfg.silence_ms = ms
    cfg.model_path = Path(os.environ.get("AGAVAI_VAD_TEST_MODEL", str(cfg.model_path)))
    context.vad_cfg = cfg


@given("the streaming VAD selects Silero without its model")
def step_silero_missing(context):
    cfg = Config().vad
    cfg.backend = "silero"
    cfg.model_path = Path("/nonexistent/silero.onnx")
    context.vad_cfg = cfg


@when('I replay "{first}", "{second}" and "{third}" through one endpointer')
def step_replay_clips(context, first, second, third):
    """Like a session's turns: each clip is one capture, and every endpoint resets the endpointer."""
    manifest = json.loads((AUDIO / "manifest.json").read_text())
    endpointer = streaming_endpointer(context.vad_cfg)
    context.add_cleanup(endpointer.backend.close)
    context.endpoints = {}
    for clip in (first, second, third):
        name = next(name for name, meta in manifest.items() if meta["id"] == clip)
        with wave.open(str(AUDIO / name)) as audio:
            pcm = audio.readframes(audio.getnframes())
        endpointer.reset()
        ends = []
        for offset in range(0, len(pcm) - FRAME + 1, FRAME):
            reason = endpointer.feed(pcm[offset:offset + FRAME])
            if reason == "start_timeout":
                endpointer.reset()
            elif reason:
                ends.append((reason, (offset + FRAME) / 32000 - manifest[name]["speech_end_s"]))
                endpointer.reset()
        context.endpoints[clip] = ends


@when("I build the streaming endpointer")
def step_build_endpointer(context):
    try:
        streaming_endpointer(context.vad_cfg)
        context.endpointer_error = None
    except ValueError as exc:
        context.endpointer_error = str(exc)


@then('building it fails with "{text}"')
def step_endpointer_fails(context, text):
    assert context.endpointer_error and text in context.endpointer_error, context.endpointer_error


@then('"{clip}" ends once, within {secs:g} seconds of its speech')
def step_request_ends(context, clip, secs):
    ends = context.endpoints[clip]
    assert len(ends) == 1 and ends[0][0] == "silence" and 0 < ends[0][1] <= secs, ends


@then('"{clip}" never ends a turn')
def step_never_ends(context, clip):
    assert context.endpoints[clip] == [], context.endpoints[clip]
