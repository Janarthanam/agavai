"""Streaming ASR for the assistant listen path.

The parent stays stdlib-only. Parakeet runs in the TTS venv via
parakeet_worker.py. A reader thread drains the worker's stdout so a full
pipe cannot stall the microphone pump. Turn taking lives in the listen loop:
this module only delivers interim, end-of-boundary, and end-of-utterance events.
"""

from __future__ import annotations

import json
import os
import queue
import select
import shutil
import struct
import subprocess
import threading
from pathlib import Path

from agavai.config import Config
from agavai.meter import ParecSource

MIC_ERROR = "Microphone input is unavailable. Check your input device and try again."


class AsrError(RuntimeError):
    pass


def resolve_device(requested: str) -> str:
    """CPU unless config asks for GPU and an NVIDIA GPU is present."""
    if (requested or "cpu").strip().lower() != "gpu":
        return "cpu"
    if Path("/proc/driver/nvidia/version").is_file():
        return "cuda"
    return "cpu"


class StreamingRecognizer:
    """One Parakeet process for the listen session. Capture starts per utterance."""

    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        root = Path(cfg.asr.model_dir).expanduser()
        python = Path(cfg.asr.venv).expanduser() / "bin" / "python"
        missing = [
            name
            for name in ("streaming_encoder.fp16.onnx", "decoder_joint-model.int8.onnx", "vocab.txt")
            if not (root / name).is_file()
        ]
        if missing:
            raise AsrError("Streaming ASR model is not installed. Run scripts/download-asr.sh.")
        if not python.is_file():
            raise AsrError(f"Streaming ASR runtime is missing: {python}")
        worker = Path(__file__).with_name("parakeet_worker.py")
        device = resolve_device(cfg.asr.device)
        self.proc = subprocess.Popen(
            [str(python), str(worker), str(root), device],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self._lines: queue.Queue[str | None] = queue.Queue()
        self._stdout_eof = threading.Event()
        self._stderr_buf = bytearray()
        self._reader = threading.Thread(target=self._read_stdout, daemon=True)
        self._reader.start()
        self._err_reader = threading.Thread(target=self._drain_stderr, daemon=True)
        self._err_reader.start()
        self._parec: subprocess.Popen | None = None
        self._pump: threading.Thread | None = None
        self._stop_pump = threading.Event()
        self._pump_done = threading.Event()
        self._mic_error = threading.Event()
        self._write_lock = threading.Lock()
        ready = self._read_line(120)
        if not ready:
            err = self._stderr()
            self.close()
            raise AsrError(err or "Streaming ASR did not start.")
        try:
            msg = json.loads(ready)
        except json.JSONDecodeError as exc:
            self.close()
            raise AsrError("Streaming ASR did not start.") from exc
        if msg.get("kind") == "error":
            text = msg.get("text") or "Streaming ASR did not start."
            self.close()
            raise AsrError(text)
        if msg.get("kind") != "ready":
            self.close()
            raise AsrError("Streaming ASR did not start.")

    def events(self, should_stop=None):
        if self.proc.poll() is not None:
            raise AsrError(self._stderr() or "Streaming ASR stopped.")
        if not shutil.which("parec"):
            raise AsrError(MIC_ERROR)
        self._mic_error.clear()
        self._pump_done.clear()
        self._stop_pump.clear()
        self._parec = subprocess.Popen(ParecSource.ARGV, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        self._pump = threading.Thread(target=self._pump_audio, args=(should_stop,), daemon=True)
        self._pump.start()
        try:
            while True:
                if should_stop and should_stop():
                    return
                if self._mic_error.is_set():
                    raise AsrError(MIC_ERROR)
                line = self._read_line(0.05)
                if line is None:
                    if self.proc.poll() is not None:
                        raise AsrError(self._stderr() or "Streaming ASR stopped.")
                    if self._pump_done.is_set():
                        yield from self._flush()
                        return
                    continue
                kind, text = _event(line)
                if kind == "eou":
                    yield kind, text
                    return
                if kind in {"interim", "eob"}:
                    yield kind, text
        finally:
            self._sync_reset()
            self._stop_capture()

    def close(self) -> None:
        self._stop_capture()
        proc = getattr(self, "proc", None)
        if proc is not None and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()

    def _pump_audio(self, should_stop) -> None:
        assert self._parec is not None and self._parec.stdout is not None
        out = self._parec.stdout
        got = False
        try:
            while not self._stop_pump.is_set():
                if should_stop and should_stop():
                    break
                ready, _, _ = select.select([out], [], [], 0.05)
                if not ready:
                    continue
                data = os.read(out.fileno(), 3200)
                if not data:
                    if not got:
                        self._mic_error.set()
                    break
                got = True
                self._write(data)
        except Exception:
            self._mic_error.set()
        finally:
            self._pump_done.set()
            self._stop_parec()

    def _flush(self):
        """Ask the worker to finish the buffered tail, then yield until it resets."""
        self._stop_pump.set()
        if self._pump is not None:
            self._pump.join(timeout=2)
        if self.proc.poll() is not None:
            return
        self._write(b"")
        deadline_s = 30
        waited = 0.0
        while waited < deadline_s:
            line = self._read_line(0.1)
            waited += 0.1
            if line is None:
                if self.proc.poll() is not None:
                    return
                continue
            waited = 0.0
            kind, text = _event(line)
            if kind == "reset":
                return
            if kind in {"interim", "eob", "eou"}:
                yield kind, text

    def _sync_reset(self) -> None:
        self._stop_pump.set()
        if self._pump is not None and self._pump.is_alive():
            self._pump.join(timeout=2)
        if self.proc.poll() is not None:
            return
        try:
            self._write(b"")
        except OSError:
            self.close()
            return
        deadline_s = 30
        waited = 0.0
        while waited < deadline_s:
            line = self._read_line(0.1)
            waited += 0.1
            if line is None:
                if self.proc.poll() is not None:
                    return
                continue
            waited = 0.0
            kind, _text = _event(line)
            if kind == "reset":
                return
        self.close()

    def _write(self, payload: bytes) -> None:
        assert self.proc.stdin is not None
        frame = struct.pack(">I", len(payload)) + payload
        with self._write_lock:
            self.proc.stdin.write(frame)
            self.proc.stdin.flush()

    def _read_stdout(self) -> None:
        assert self.proc.stdout is not None
        buf = b""
        try:
            while True:
                ready, _, _ = select.select([self.proc.stdout], [], [], 0.05)
                if not ready:
                    if self.proc.poll() is None:
                        continue
                    try:
                        chunk = os.read(self.proc.stdout.fileno(), 65536)
                    except OSError:
                        break
                    if not chunk:
                        break
                else:
                    chunk = os.read(self.proc.stdout.fileno(), 65536)
                    if not chunk:
                        break
                buf += chunk
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    self._lines.put(line.decode("utf-8", "replace"))
        finally:
            if buf.strip():
                self._lines.put(buf.decode("utf-8", "replace"))
            self._lines.put(None)
            self._stdout_eof.set()

    def _read_line(self, timeout: float) -> str | None:
        if self._stdout_eof.is_set() and self._lines.empty():
            return None
        try:
            item = self._lines.get(timeout=timeout)
        except queue.Empty:
            return None
        if item is None:
            self._stdout_eof.set()
            return None
        return item

    def _drain_stderr(self) -> None:
        if self.proc.stderr is None:
            return
        try:
            while True:
                chunk = os.read(self.proc.stderr.fileno(), 4096)
                if not chunk:
                    return
                self._stderr_buf.extend(chunk)
                if len(self._stderr_buf) > 8192:
                    del self._stderr_buf[:-8192]
        except OSError:
            return

    def _stderr(self) -> str:
        return bytes(self._stderr_buf).decode("utf-8", "replace").strip()

    def _stop_capture(self) -> None:
        self._stop_pump.set()
        self._stop_parec()

    def _stop_parec(self) -> None:
        proc = self._parec
        if proc is None or proc.poll() is not None:
            return
        proc.terminate()
        try:
            proc.wait(timeout=1)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()


def _event(line: str) -> tuple[str | None, str]:
    try:
        msg = json.loads(line)
    except json.JSONDecodeError:
        return None, ""
    kind = msg.get("kind")
    if kind == "error":
        raise AsrError(msg.get("text") or "Streaming ASR failed.")
    if kind in {"interim", "eob", "eou", "reset"}:
        return kind, msg.get("text") or ""
    return None, ""


def open_stream(cfg: Config) -> StreamingRecognizer:
    return StreamingRecognizer(cfg)
