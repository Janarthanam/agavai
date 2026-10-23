"""ASR worker: length-prefixed (command byte, uint32 utterance ID, PCM) in; JSONL out."""
from __future__ import annotations

import json
from pathlib import Path
import struct
import sys
from types import SimpleNamespace

# Workers are launched by file path, independent of the session's PYTHONPATH.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agavai.speech_backends import create_backend
from agavai.worker import emit, read_frame


def serve(cfg, source=None):
    source = source or sys.stdin.buffer
    utterance = None

    def event(kind, text):
        emit({"kind": kind, "text": text, "utterance_id": utterance})

    backend = create_backend(cfg, event)
    emit({"kind": "ready", "protocol": 1, "partials": backend.partials,
          "native_endpoint": backend.native_endpoint, "backend": cfg.backend})
    audio_bytes = 0
    while (frame := read_frame(source)) is not None:
        if len(frame) < 5:
            raise ValueError("Short ASR command")
        kind, uid = struct.unpack(">cI", frame[:5])
        if kind == b"S":
            if utterance is not None:
                raise ValueError("Previous utterance is still active")
            utterance = uid
            audio_bytes = 0
            backend.start()
        elif uid != utterance:
            raise ValueError("ASR utterance ID mismatch")
        elif kind == b"A":
            pcm = frame[5:]
            if len(pcm) % 2:
                raise ValueError("PCM frame contains a partial sample")
            audio_bytes += len(pcm)
            if audio_bytes > cfg.max_utterance_secs * 32000:
                raise ValueError("Maximum utterance duration exceeded; request was not submitted")
            backend.feed(pcm)
        elif kind == b"F":
            event("final", backend.finish())
            backend.cancel()
            utterance = None
        elif kind == b"C":
            backend.cancel()
            event("cancelled", "")
            utterance = None
        else:
            raise ValueError("Unknown ASR command")


def main():
    cfg = SimpleNamespace(**json.loads(sys.argv[1]))
    serve(cfg)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        emit({"kind": "error", "text": str(exc)})
        sys.exit(1)
