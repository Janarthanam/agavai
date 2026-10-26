"""Separate-process BDD driver: real harness/HTTP/dispatcher, scripted OS boundary."""
import json
import os
from pathlib import Path
import sys
from unittest.mock import patch
from types import SimpleNamespace

sys.modules["agavai.ui"] = None
from agavai.config import Config, LlmConfig
from agavai.harness import Harness

port, runtime, mode, sid, text = sys.argv[1:]
cfg = Config()
cfg.runtime_dir = Path(runtime)
cfg.router.backend = cfg.router.fallback = "keyword"
cfg.small_brain = LlmConfig(port=int(port), max_tokens=256, timeout_secs=5)
cfg.large_brain = None
events = []
def collect(event):
    events.append(event)
    if mode == "reply_crash" and event.kind == "reply":
        os._exit(76)
    if mode == "resume_crash" and event.kind == "session_resumed":
        os._exit(75)
harness = Harness(cfg, on_event=collect, session_id=sid or None)
(cfg.runtime_dir / "child-session").write_text(harness.context.session_id)


def desktop(*args, **kwargs):
    facts = harness.repository.inspect(harness.context.session_id)
    assert facts["executions"][-1]["status"] == "running"
    (cfg.runtime_dir / "side-effect").write_text("browser launched")
    if mode == "crash":
        os._exit(73)
    return SimpleNamespace(returncode=0, stdout="", stderr="")


def encoding(folder, **kwargs):
    os._exit(74)


with patch("agavai.tools._run", side_effect=desktop), patch("agavai.tools.shutil.which", return_value="/replay/bin"):
    if mode == "audio_crash":
        audio = harness.capture_audio()
        audio.write(b"\x00\x20" * 16000)
        harness.input_mode = "spoken"
        with patch("agavai.harness.audio._encode", side_effect=encoding):
            reply = harness.run_turn(text, audio=audio)
            harness.close()
    else:
        reply = harness.run_turn(text, continue_conversation=bool(sid))
        harness.close()
print(json.dumps({"reply": reply, "session": harness.context.session_id,
                  "events": [event.to_dict() for event in events]}))
