"""Optional Silero VAD backend (v5.1.2 ONNX) via a bounded venv child.

The main interpreter stays stdlib-only. Inference runs as a subprocess of
`cfg.vad.venv/bin/python` (the TTS venv), using a framed request/response
protocol with a bounded, cancel-aware poll. Any protocol failure is
`backend_failed`, never silence. `SileroBackend` only classifies audio —
`Endpointer` owns all session timing.

Prerequisite (opt-in): `scripts/download-vad.sh` installs the pinned
v5.1.2 model. Missing model/venv raises at construction; `make_backend`
degrades to energy without touching session flow.
"""

from __future__ import annotations

import os
import select
import signal
import struct
import subprocess
import sys
import time
from pathlib import Path

from agavai.config import VadConfig
from agavai.meter import AcousticResult

_MAGIC = b"SVAD"
_HEADER = ">4sIQ"
_WINDOW = 512
_REQUEST_BYTES = _WINDOW * 2
_READY = b"READY v1\n"
_PROTOCOL = "v1"
# Importing onnxruntime and loading the model takes far longer than one window's response budget.
_STARTUP_MS = 10_000

# The runtime script executes inside the venv child; it imports onnxruntime
# there and speaks the framed protocol on stdio.
_RUNTIME = """\\
import struct, sys
import numpy as np
import onnxruntime as ort

model_path = sys.argv[1]
threshold = float(sys.argv[2])
opts = ort.SessionOptions()
so = ort.SessionOptions()  # CPU by default; device is pinned in the venv
# A 32 ms window needs no thread pool, and idle pool threads spin a core each.
opts.intra_op_num_threads = 1
opts.inter_op_num_threads = 1
sess = ort.InferenceSession(model_path, sess_options=opts, providers=["CPUExecutionProvider"])
sys.stdout.buffer.write(b"READY v1\\n")
sys.stdout.buffer.flush()
state = None
 expected_id = 0
while True:
    header = sys.stdin.buffer.read(struct.calcsize(">4sIQ"))
    if len(header) < struct.calcsize(">4sIQ"):
        break
    magic, length, rid = struct.unpack(">4sIQ", header)
    if magic == b"SVAD" and length == 0:
        state = None
        continue
    if magic != b"SVAD" or length != 1024:
        break
    payload = sys.stdin.buffer.read(length)
    if len(payload) < length:
        break
    samples = np.frombuffer(payload, dtype="<i2").astype("float32") / 32768.0
    feed = {"input": samples.reshape(1, -1), "sr": np.array([16000], dtype="i8")}
    if state is None:
        state = np.zeros((2, 1, 128), dtype="float32")
    feed["state"] = state
    out = sess.run(None, feed)
    prob = float(out[0][0][0])
    state = out[1]
    sys.stdout.buffer.write(b"P %d %.6f\\n" % (rid, prob))
    sys.stdout.buffer.flush()
    expected_id += 1
"""


def _runtime_script() -> str:
    return _RUNTIME.replace(" expected_id = 0", "expected_id = 0")


class SileroBackend:
    """Opt-in classifier: 512-sample windows via the bounded venv child."""

    def __init__(self, cfg: VadConfig) -> None:
        self.cfg = cfg
        self.model_path = Path(cfg.model_path).expanduser()
        self.venv_python = Path(cfg.venv).expanduser() / "bin" / "python"
        if not self.venv_python.is_file():
            raise RuntimeError(f"venv python missing: {self.venv_python}")
        if not self.model_path.is_file():
            raise RuntimeError(f"model missing: {self.model_path}")
        self.proc = self._spawn()
        self.buffer = b""
        self.window_start = 0
        self.request_id = 0
        self._restarted = False

    # ---- lifecycle ----

    def _spawn(self) -> subprocess.Popen:
        script = _runtime_script()
        proc = subprocess.Popen(
            [str(self.venv_python), "-c", script, str(self.model_path), str(self.cfg.threshold)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        if not self._wait_ready(proc, _STARTUP_MS):
            self._reap(proc)
            raise RuntimeError("silero handshake failed")
        return proc

    def _wait_ready(self, proc: subprocess.Popen, deadline_ms: int | None = None) -> bool:
        limit = (deadline_ms or self.cfg.response_timeout_ms) / 1000
        end = time.monotonic() + limit
        fd = proc.stdout.fileno()
        buf = b""
        while time.monotonic() < end:
            ready, _, _ = select.select([fd], [], [], 0.02)
            if ready:
                try:
                    buf += os.read(fd, 256)
                except OSError:
                    return False
                if _READY in buf:
                    return True
        return False

    def _reap(self, proc: subprocess.Popen) -> None:
        try:
            if proc.stdin:
                proc.stdin.close()
        except OSError:
            pass
        proc.terminate()
        try:
            proc.wait(timeout=1)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()

    # ---- classification ----

    def feed(self, frame: bytes) -> AcousticResult:
        self.buffer += frame
        if len(self.buffer) < _REQUEST_BYTES:
            return AcousticResult("pending")
        window = self.buffer[:_REQUEST_BYTES]
        self.buffer = self.buffer[_REQUEST_BYTES:]
        prob = self._infer(window)
        if prob is None:
            return AcousticResult("non_speech", covered_samples=_WINDOW, backend_failed="infer")
        classification = "speech" if prob >= self.cfg.threshold else "non_speech"
        self.window_start += _WINDOW
        return AcousticResult(classification, covered_samples=_WINDOW)

    def _infer(self, window: bytes) -> float | None:
        for attempt in (0, 1):
            prob = self._request(window)
            if prob is not None:
                return prob
            if attempt == 0 and not self._restarted:
                self._restarted = True
                self._reap(self.proc)
                try:
                    self.proc = self._spawn()
                except RuntimeError:
                    return None
        return None

    def _request(self, window: bytes) -> float | None:
        proc = self.proc
        rid = self.request_id
        try:
            assert proc.stdin is not None and proc.stdout is not None
            proc.stdin.write(struct.pack(_HEADER, _MAGIC, len(window), rid))
            proc.stdin.write(window)
            proc.stdin.flush()
        except (OSError, ValueError):
            return None
        deadline = time.monotonic() + self.cfg.response_timeout_ms / 1000
        fd = proc.stdout.fileno()
        buf = b""
        while time.monotonic() < deadline:
            ready, _, _ = select.select([fd], [], [], 0.02)
            if ready:
                try:
                    buf += os.read(fd, 128)
                except OSError:
                    return None
                if b"\n" in buf:
                    return self._parse_response(buf, rid)
        return None

    def _parse_response(self, buf: bytes, rid: int) -> float | None:
        try:
            line = buf.split(b"\n", 1)[0]
            parts = line.split()
            if len(parts) != 3 or parts[0] != b"P" or int(parts[1]) != rid:
                return None
            prob = float(parts[2])
        except (ValueError, IndexError):
            return None
        if not (0.0 <= prob <= 1.0):
            return None
        self.request_id += 1
        return prob

    def reset(self) -> None:
        self.buffer = b""
        self.window_start = 0
        # A new utterance must not be judged with the previous one's model state:
        # carried over, it ends words early enough to split a 700 ms pause.
        # A dead child is restarted, with fresh state, by the next request.
        try:
            assert self.proc.stdin is not None
            self.proc.stdin.write(struct.pack(_HEADER, _MAGIC, 0, self.request_id))
            self.proc.stdin.flush()
        except (OSError, ValueError):
            pass

    def close(self) -> None:
        self._reap(self.proc)
