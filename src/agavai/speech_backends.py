"""Speech adapter registry with lazy native imports for independent environments."""
from __future__ import annotations

import array
from dataclasses import asdict
from pathlib import Path
import sys
from typing import Protocol


class SpeechBackend(Protocol):
    partials: bool
    native_endpoint: bool

    @staticmethod
    def validate_selection(cfg) -> None: ...
    @staticmethod
    def settings(cfg) -> dict: ...
    def start(self) -> None: ...
    def feed(self, pcm: bytes) -> None: ...
    def finish(self) -> str: ...
    def cancel(self) -> None: ...


class ParakeetBackend:
    partials = True
    native_endpoint = True

    @staticmethod
    def validate_selection(cfg):
        if cfg.mode != "streaming" or cfg.endpoint != "native":
            raise ValueError("Parakeet requires streaming mode and native endpointing")

    @staticmethod
    def settings(cfg):
        settings = asdict(cfg)
        if cfg.device == "cpu":
            settings["device"] = "cpu"
        elif cfg.device in {"gpu", "cuda"} and Path("/proc/driver/nvidia/version").is_file():
            settings["device"] = "cuda"
        else:
            raise ValueError(f"Requested ASR device is unavailable: {cfg.device}. Select cpu explicitly.")
        if any(not (Path(cfg.model_dir) / name).is_file() for name in ("encoder.onnx", "decoder_joint.onnx", "vocab.txt")):
            raise ValueError("Parakeet model is not installed. Run scripts/download-asr.sh.")
        return settings

    def __init__(self, cfg, on_event):
        from agavai.parakeet_worker import Stream
        self.on_event = on_event
        self.text = ""
        self.stream = Stream(str(cfg.model_dir), cfg.device, on_event=self._event)

    def _event(self, kind, text):
        self.text = text
        self.on_event("endpoint" if kind == "eou" else "partial", text)

    def start(self):
        self.text = ""
        self.stream.reset()

    def feed(self, pcm):
        import numpy as np
        self.stream.feed(np.frombuffer(pcm, dtype="<i2").astype(np.float32) / np.float32(32768))

    def finish(self):
        import numpy as np
        self.stream.feed(np.empty(0, np.float32), final=True)
        return self.text

    def cancel(self):
        self.stream.reset()
        self.text = ""


class WhistleBackend:
    native_endpoint = False

    @staticmethod
    def validate_selection(cfg):
        if cfg.device != "cpu" or cfg.endpoint not in {"manual", "vad"} or cfg.mode not in {"streaming", "batch"}:
            raise ValueError("Whistle requires CPU, manual or vad endpointing and streaming or batch mode")

    @staticmethod
    def settings(cfg):
        if not Path(cfg.model_path).is_file():
            raise ValueError(f"Whistle model is missing: {cfg.model_path}")
        if cfg.runtime_library is None or not Path(cfg.runtime_library).is_file():
            raise ValueError("Whistle needs an installed runtime_library. Run scripts/setup-cactus.sh.")
        return asdict(cfg)

    def __init__(self, cfg, on_event):
        from agavai.cactus_runtime import prepare
        prepare(cfg.runtime_library)
        from needle import Whistle
        self.model = Whistle(weights=str(cfg.model_path))
        self.on_event = on_event
        self.partials = cfg.mode == "streaming"
        self.chunk_bytes = cfg.chunk_ms * 32
        self.start()

    def start(self):
        self.pending = bytearray()
        self.committed = []
        self.chunks = []
        self.iterator = None

    @staticmethod
    def _samples(pcm):
        values = array.array("h")
        values.frombytes(pcm)
        if sys.byteorder != "little":
            values.byteswap()
        return array.array("f", (value / 32768 for value in values))

    def _stream_chunks(self):
        # The SDK pulls one chunk per next(); finish ends this iterator to flush its tail.
        while self.chunks:
            yield self.chunks.pop(0)

    def _result(self, result):
        text = (result.get("text") or "").strip()
        if text:
            self.committed.append(text)
        display = " ".join([*self.committed, result.get("pending") or ""]).strip()
        self.on_event("partial", display)

    def feed(self, pcm):
        self.pending.extend(pcm)
        if not self.partials:
            return
        while len(self.pending) >= self.chunk_bytes:
            chunk = bytes(self.pending[:self.chunk_bytes])
            del self.pending[:self.chunk_bytes]
            self.chunks.append(self._samples(chunk))
            if self.iterator is None:
                self.iterator = self.model.stream(self._stream_chunks())
            self._result(next(self.iterator))

    def finish(self):
        if not self.partials:
            if not self.pending:
                return ""
            result = self.model.transcribe(self._samples(self.pending))
            return (result.get("text") or "").strip()
        if self.pending:
            self.chunks.append(self._samples(self.pending))
            if self.iterator is None:
                self.iterator = self.model.stream(self._stream_chunks())
            self._result(next(self.iterator))
        if self.iterator is not None:
            for result in self.iterator:
                self._result(result)
            self.iterator = None
        return " ".join(self.committed)

    def cancel(self):
        if self.iterator is not None:
            self.iterator.close()
        self.start()


SPEECH_BACKENDS = {"parakeet-onnx": ParakeetBackend, "whistle-cactus": WhistleBackend}


def create_backend(cfg, on_event):
    try:
        factory = SPEECH_BACKENDS[cfg.backend]
    except KeyError as exc:
        raise ValueError(f"Unknown speech backend: {cfg.backend}") from exc
    return factory(cfg, on_event)
