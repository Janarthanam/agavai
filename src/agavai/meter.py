"""Mic level metering and end-of-speech detection (energy VAD).

The main interpreter stays stdlib-only: `EnergyBackend` is pure Python over
dBFS frames. `Endpointer` owns all temporal/session policy (the settled
900 ms silence window, lead-in, start timeout, min-speech, max duration) on
the 16 kHz capture-sample timeline. Backends only classify audio.
"""

from __future__ import annotations

import math
import os
import select
import shutil
import struct
import subprocess
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Literal, Protocol

from agavai.config import VadConfig

CLAMP_DBFS = -100.0
_REF = 32768.0


def rms_dbfs(frame: bytes) -> float:
    """s16le PCM → dBFS, clamped to −100. Pure; no I/O."""
    if len(frame) % 2:
        frame = frame[:-1]
    n = len(frame) // 2
    if not n:
        return CLAMP_DBFS
    total = 0.0
    for (sample,) in struct.iter_unpack("<h", frame):
        total += sample * sample
    rms = math.sqrt(total / n)
    if rms <= 0:
        return CLAMP_DBFS
    return max(CLAMP_DBFS, 20.0 * math.log10(rms / _REF))


def frame_iter(read: Callable[[int], bytes | None], frame_bytes: int) -> Iterator[bytes]:
    """Accumulate variable-size reads into fixed-size frames. Pure.

    `read` returns `None` when no data is available yet (a watchdog timeout,
    skipped); `b""` means end of stream and ends the iterator.
    """
    buf = b""
    while True:
        chunk = read(frame_bytes - len(buf))
        if chunk is None:
            continue
        if not chunk:
            return
        buf += chunk
        if len(buf) == frame_bytes:
            yield buf
            buf = b""


def _select_read(stream, frame_ms: int, should_stop: Callable[[], bool] | None = None) -> Callable[[int], bytes | None]:
    """Reader closure: `select`-gated unbuffered reads.

    Returns `None` when the fd is not ready within `frame_ms` (no data yet),
    `b""` at EOF, else the bytes read. `os.read` is a single syscall that
    returns at most what the kernel signalled ready, so an iteration can never
    block past `frame_ms` — unlike `BufferedReader.read(n)`, which blocks until
    `n` bytes. This is what keeps the session loop able to observe SIGTERM and
    both deadlines even when the source stalls.
    """
    fd = stream.fileno()
    last_data = time.monotonic()

    def read(n: int) -> bytes | None:
        nonlocal last_data
        if should_stop and should_stop() or time.monotonic() - last_data >= 1.5:
            return b""
        ready, _, _ = select.select([fd], [], [], frame_ms / 1000)
        if not ready:
            return None
        try:
            chunk = os.read(fd, n)
            if chunk:
                last_data = time.monotonic()
            return chunk
        except OSError:
            return b""

    return read


@dataclass(frozen=True)
class AcousticResult:
    classification: Literal["speech", "non_speech", "pending"]
    covered_samples: int = 320
    backend_failed: str | None = None


class VadBackend(Protocol):
    """Acoustic classification only; never makes a session/stop decision."""

    def feed(self, frame: bytes) -> AcousticResult: ...
    def reset(self) -> None: ...
    def close(self) -> None: ...


class EnergyBackend:
    """Default classifier: dBFS hysteresis + adaptive floor. No model."""

    def __init__(self, cfg: VadConfig) -> None:
        self.cfg = cfg
        self.history: list[float] = []

    def feed(self, frame: bytes) -> AcousticResult:
        db = rms_dbfs(frame)
        self.history.append(db)
        open_db, close_db = self._thresholds()
        if db >= open_db:
            return AcousticResult("speech")
        if db < close_db:
            return AcousticResult("non_speech")
        return AcousticResult("pending")

    def _thresholds(self) -> tuple[float, float]:
        cfg = self.cfg
        if len(self.history) < 150:
            return (cfg.open_threshold_dbfs, cfg.close_threshold_dbfs)
        ordered = sorted(self.history[-150:])
        floor = ordered[max(0, int(len(ordered) * 0.05) - 1)]
        margin = floor + cfg.noise_margin_db
        return (
            max(cfg.open_threshold_dbfs, margin),
            max(cfg.close_threshold_dbfs, margin),
        )

    def reset(self) -> None:
        self.history.clear()

    def close(self) -> None:
        return None


def make_backend(cfg: VadConfig) -> tuple[VadBackend, Literal["energy", "silero"]]:
    """Resolve the requested backend; unavailable silero → energy (never raise)."""
    if (cfg.backend or "energy").lower() == "silero":
        try:
            from agavai.vad_silero import SileroBackend

            return SileroBackend(cfg), "silero"
        except Exception as exc:
            print(f"agavai: silero backend unavailable ({exc}) → energy backend", flush=True)
    return EnergyBackend(cfg), "energy"


class ParecSource:
    """Raw PCM taps of @DEFAULT_SOURCE@ → dBFS frames. No files, no network."""

    ARGV = [
        "parec",
        "--raw",
        "--format=s16le",
        "--rate=16000",
        "--channels=1",
        "--latency-msec=20",
        "-d",
        "@DEFAULT_SOURCE@",
    ]

    def __init__(self, cfg: VadConfig) -> None:
        self.cfg = cfg
        self.frame_bytes = cfg.rate * cfg.frame_ms // 1000 * 2

    def frames(self, should_stop: Callable[[], bool] | None = None) -> Iterator[bytes]:
        if not shutil.which("parec"):
            return
        proc = subprocess.Popen(self.ARGV, stdout=subprocess.PIPE)
        try:
            assert proc.stdout is not None
            yield from frame_iter(
                _select_read(proc.stdout, self.cfg.frame_ms, should_stop), self.frame_bytes
            )
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=1)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()


class Endpointer:
    """Sole owner of lead-in, start timeout, voiced/min-speech accounting,
    the settled 900 ms silence timer, and max duration."""

    def __init__(self, cfg: VadConfig, backend: VadBackend | None = None) -> None:
        self.cfg = cfg
        self.backend, _ = (backend, "energy") if backend else make_backend(cfg)
        self.samples = 0
        self.voiced_samples = 0
        self.silence_samples = 0
        self.speaking = False

    def feed(self, frame: bytes) -> str | None:
        cfg = self.cfg
        frame_samples = len(frame) // 2
        self.samples += frame_samples
        elapsed_ms = self.samples * 1000 // cfg.rate

        result = self.backend.feed(frame)
        if result.backend_failed:
            return None

        if result.classification == "pending":
            return self._deadlines(elapsed_ms)

        if not self.speaking and result.classification == "non_speech":
            if elapsed_ms < cfg.lead_in_ignore_ms:
                return None
            return self._deadlines(elapsed_ms)

        if result.classification == "speech":
            if not self.speaking:
                self.speaking = True
            self.voiced_samples += result.covered_samples
            self.silence_samples = 0
            return self._deadlines(elapsed_ms)

        self.silence_samples += result.covered_samples
        if self.speaking and self.silence_samples * 1000 // cfg.rate >= cfg.silence_ms:
            if self.voiced_samples * 1000 // cfg.rate < cfg.min_speech_ms:
                return "min_speech"
            return "silence"
        return self._deadlines(elapsed_ms)

    def _deadlines(self, elapsed_ms: int) -> str | None:
        if not self.speaking and elapsed_ms >= self.cfg.start_timeout_ms:
            return "start_timeout"
        if self.speaking and elapsed_ms >= self.cfg.max_record_ms:
            return "max_duration"
        return None

    def reset(self) -> None:
        self.samples = 0
        self.voiced_samples = 0
        self.silence_samples = 0
        self.speaking = False
        self.backend.reset()


def energy_endpointer(cfg: VadConfig) -> Endpointer:
    """Explicit streaming policy; do not inherit the legacy backend fallback."""
    if not cfg.enabled or cfg.backend != "energy":
        raise ValueError("VAD endpointing requires [vad] enabled=true and backend=energy")
    if cfg.rate != 16000 or cfg.frame_ms != 20:
        raise ValueError("VAD endpointing requires 16000 Hz and 20 ms frames")
    if min(cfg.silence_ms, cfg.min_speech_ms, cfg.start_timeout_ms, cfg.max_record_ms) <= 0:
        raise ValueError("VAD silence, speech and duration limits must be positive")
    if cfg.close_threshold_dbfs > cfg.open_threshold_dbfs:
        raise ValueError("VAD close threshold must not exceed its open threshold")
    return Endpointer(cfg, backend=EnergyBackend(cfg))
