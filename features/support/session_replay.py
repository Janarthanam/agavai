"""Script external audio/desktop boundaries while exercising the real voice controller."""
from contextlib import contextmanager, ExitStack
from unittest.mock import patch


@contextmanager
def quiet_session():
    with ExitStack() as stack:
        for name in ("prepare_listen", "finish", "hide_listen", "cue_start", "cue_think", "cue_record", "cue_listen"):
            stack.enter_context(patch("agavai.harness.session." + name))
        stack.enter_context(patch("agavai.tts.sweep_playback_wavs"))
        stack.enter_context(patch("agavai.tts._interruptible_speak", return_value="completed"))
        stack.enter_context(patch("agavai.recording._encode", return_value="Replay keeps uncompressed audio."))
        yield
