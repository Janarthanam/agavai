"""Bounded local worker transport. Native runtimes never share the session process."""
from __future__ import annotations

import json
import os
import queue
import select
import signal
import struct
import subprocess
import threading
import time


class WorkerError(RuntimeError):
    pass


class WorkerProcess:
    def __init__(self, argv: list[str], *, env=None) -> None:
        try:
            self.proc = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                         stderr=subprocess.PIPE, env=env, start_new_session=True)
        except OSError as exc:
            raise WorkerError(f"Cannot start inference worker: {exc}") from exc
        self.lines: queue.Queue[bytes | None] = queue.Queue(maxsize=512)
        self.failure = ""
        self.stderr = bytearray()
        os.set_blocking(self.proc.stdin.fileno(), False)
        threading.Thread(target=self._read, daemon=True).start()
        threading.Thread(target=self._errors, daemon=True).start()

    def _read(self) -> None:
        try:
            for line in iter(lambda: self.proc.stdout.readline(1 << 20), b""):
                if not line.endswith(b"\n"):
                    self.failure = "Worker response exceeded the protocol limit."
                    break
                self.lines.put_nowait(line)
        except queue.Full:
            self.failure = "Worker output queue overflowed."
        except (OSError, ValueError) as exc:
            self.failure = str(exc)
        finally:
            try:
                self.lines.put_nowait(None)
            except queue.Full:
                pass

    def _errors(self) -> None:
        try:
            for chunk in iter(lambda: os.read(self.proc.stderr.fileno(), 4096), b""):
                self.stderr.extend(chunk)
                del self.stderr[:-8192]
        except (OSError, ValueError):
            return

    def send(self, payload: bytes, timeout: float = 2) -> None:
        packet = memoryview(struct.pack(">I", len(payload)) + payload)
        deadline = time.monotonic() + timeout
        try:
            while packet:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise WorkerError("Worker input timed out.")
                _, writable, _ = select.select([], [self.proc.stdin], [], min(remaining, 0.1))
                if writable:
                    packet = packet[os.write(self.proc.stdin.fileno(), packet):]
        except OSError as exc:
            raise WorkerError("Worker input closed.") from exc

    def receive(self, timeout: float) -> dict | None:
        if self.failure:
            raise WorkerError(self.failure)
        try:
            line = self.lines.get(timeout=max(0, timeout))
        except queue.Empty:
            if self.proc.poll() is not None:
                raise WorkerError(self.detail("Worker stopped."))
            return None
        if line is None:
            raise WorkerError(self.detail("Worker output closed."))
        try:
            message = json.loads(line)
        except (ValueError, UnicodeDecodeError) as exc:
            raise WorkerError("Invalid worker response.") from exc
        if not isinstance(message, dict):
            raise WorkerError("Worker response must be an object.")
        if message.get("kind") == "error":
            raise WorkerError(message.get("text") or "Worker failed.")
        return message

    def detail(self, text: str) -> str:
        tail = bytes(self.stderr).decode("utf-8", "replace").strip()[-1000:]
        return f"{text} {tail}" if tail else text

    def close(self) -> None:
        # Needle's public binding starts its own inference child.
        try:
            os.killpg(self.proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            self.proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            os.killpg(self.proc.pid, signal.SIGKILL)
            self.proc.wait()
        for pipe in (self.proc.stdin, self.proc.stdout, self.proc.stderr):
            pipe.close()


def read_frame(source, *, limit: int = 1 << 20) -> bytes | None:
    def exact(size):
        data = bytearray()
        while len(data) < size:
            chunk = source.read(size - len(data))
            if not chunk:
                if not data:
                    return None
                raise EOFError("Truncated worker frame")
            data.extend(chunk)
        return bytes(data)

    header = exact(4)
    if header is None:
        return None
    size = struct.unpack(">I", header)[0]
    if not 0 < size <= limit:
        raise ValueError("Invalid worker frame size")
    payload = exact(size)
    if payload is None:
        raise EOFError("Missing worker frame payload")
    return payload


def emit(message: dict) -> None:
    import sys
    print(json.dumps(message, ensure_ascii=False), flush=True)
