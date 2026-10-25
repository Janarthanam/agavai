"""One capture and a selectable speech worker for the assistant listen path."""
from __future__ import annotations

import json
import logging
import os
from dataclasses import replace
from pathlib import Path
import select
import shutil
import struct
import subprocess
import threading
import time

from agavai.config import AsrConfig, Config
from agavai.meter import ParecSource, rms_dbfs, streaming_endpointer
from agavai.worker import WorkerError, WorkerProcess

MIC_ERROR = "Microphone input is unavailable. Check your input device and try again."
AsrError = WorkerError
log = logging.getLogger(__name__)


def worker_settings(cfg):
    from agavai.speech_backends import SPEECH_BACKENDS
    try:
        factory = SPEECH_BACKENDS[cfg.backend]
        factory.validate_selection(cfg)
        settings = factory.settings(cfg)
    except (KeyError, ValueError) as exc:
        raise AsrError(str(exc)) from exc
    if not 20 <= cfg.chunk_ms <= 5000 or min(cfg.startup_timeout_secs, cfg.finish_timeout_secs, cfg.max_utterance_secs) <= 0:
        raise AsrError("Invalid ASR chunk size or deadline.")
    return {key: str(value) if isinstance(value, Path) else value for key, value in settings.items()}


class StreamingRecognizer:
    """Session-lived inference worker; each events() call owns one microphone capture."""

    def __init__(self, cfg: Config, *, continuous: bool = False):
        # Recording has its own continuous Parakeet worker, independent of the
        # assistant's configured recognizer and utterance endpoint policy.
        if continuous and cfg.asr.backend != "parakeet-onnx":
            cfg = replace(cfg, asr=AsrConfig())
        self.cfg = cfg
        settings = worker_settings(cfg.asr)
        settings["continuous"] = continuous
        python = Path(cfg.asr.venv) / "bin/python"
        if not python.is_file():
            raise AsrError(f"ASR runtime is missing: {python}")
        try:
            self._endpointer = streaming_endpointer(cfg.vad) if cfg.asr.endpoint == "vad" else None
        except ValueError as exc:
            raise AsrError(str(exc)) from exc
        self._parec = None
        self._pump = None
        self._stop_pump = threading.Event()
        self._pump_done = threading.Event()
        self._pump_error = ""
        self._asr_lost = threading.Event()
        self._uid = 0
        started = time.monotonic()
        self._worker = WorkerProcess([str(python), str(Path(__file__).with_name("asr_worker.py")), json.dumps(settings)])
        try:
            ready = self._worker.receive(cfg.asr.startup_timeout_secs)
            if not ready or ready.get("kind") != "ready" or ready.get("protocol") != 1:
                raise AsrError("ASR worker did not provide a compatible readiness handshake.")
            if cfg.asr.endpoint == "native" and not ready.get("native_endpoint"):
                raise AsrError("Selected recognizer does not provide native endpointing.")
            log.info("asr ready backend=%s mode=%s endpoint=%s vad=%s device=%s load_secs=%.2f",
                     cfg.asr.backend, cfg.asr.mode, cfg.asr.endpoint,
                     cfg.vad.backend if cfg.asr.endpoint == "vad" else "none", cfg.asr.device, time.monotonic() - started)
        except Exception:
            self.close()
            raise

    def events(self, on_level, should_stop=None, should_cancel=None):
        if not shutil.which("parec"):
            raise AsrError(MIC_ERROR)
        self._uid += 1
        uid = self._uid
        self._stop_pump.clear()
        self._pump_done.clear()
        self._pump_error = ""
        self._endpoint_reason = ""
        if self._endpointer is not None:
            self._endpointer.reset()
        self._level_db = None
        self._send(b"S", uid)
        finished = False
        try:
            try:
                self._parec = subprocess.Popen(ParecSource.ARGV, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            except OSError as exc:
                raise AsrError(MIC_ERROR) from exc
            self._pump = threading.Thread(target=self._pump_audio, args=(uid,), daemon=True)
            self._pump.start()
            next_level = 0.0
            started = time.monotonic()
            while True:
                if should_cancel and should_cancel():
                    return
                if self._pump_error:
                    raise AsrError(self._pump_error)
                reason = "enter" if should_stop and should_stop() else self._endpoint_reason
                if reason:
                    self._stop_capture()
                    log.info("asr endpoint policy=%s reason=%s", self.cfg.asr.endpoint, reason)
                    if reason == "min_speech":
                        self._send(b"C", uid)
                        self._wait_terminal(uid, "cancelled")
                        finished = True
                        yield "eou", ""
                        return
                    if self.cfg.asr.mode == "batch":
                        yield "finishing", ""
                    message = self._finish(uid)
                    finished = True
                    yield "eou", message.get("text") or ""
                    return
                if time.monotonic() - started >= self.cfg.asr.max_utterance_secs:
                    raise AsrError("Maximum utterance duration exceeded; request was not submitted.")
                db = self._level_db
                if db is not None and time.monotonic() >= next_level:
                    on_level(db)
                    next_level = time.monotonic() + 0.1
                message = self._worker.receive(0.05)
                if message:
                    if message.get("utterance_id") != uid:
                        continue
                    kind = message.get("kind")
                    if kind == "endpoint" and self.cfg.asr.endpoint == "native":
                        self._stop_capture()
                        message = self._finish(uid)
                        finished = True
                        yield "eou", message.get("text") or ""
                        return
                    if kind == "partial":
                        yield "interim", message.get("text") or ""
                if self._pump_done.is_set():
                    if self._pump_error:
                        raise AsrError(self._pump_error)
                    if self._endpoint_reason:
                        continue
                    # A disconnected mic is not the user submitting a command.
                    return
        finally:
            self._stop_capture()
            if not finished:
                try:
                    self._send(b"C", uid)
                    self._wait_terminal(uid, "cancelled")
                except AsrError:
                    self.close()
                    raise

    def record(self, on_audio, should_stop):
        """Keep one capture open; transcription failure never discards its audio."""
        if not shutil.which("parec"):
            raise AsrError(MIC_ERROR)
        self._uid += 1
        uid = self._uid
        self._stop_pump.clear()
        self._pump_done.clear()
        self._asr_lost.clear()
        self._pump_error = ""
        self._level_db = None
        self._send(b"S", uid)
        lost_reported = False
        try:
            try:
                self._parec = subprocess.Popen(ParecSource.ARGV, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            except OSError as exc:
                raise AsrError(MIC_ERROR) from exc
            self._pump = threading.Thread(target=self._pump_audio, args=(uid, on_audio), daemon=True)
            self._pump.start()
            next_level = 0.0
            while not should_stop():
                if self._pump_error:
                    raise AsrError(self._pump_error)
                if time.monotonic() >= next_level:
                    yield {"kind": "level", "db": self._level_db}
                    next_level = time.monotonic() + 0.1
                if self._asr_lost.is_set():
                    if not lost_reported:
                        lost_reported = True
                        yield {"kind": "asr_lost"}
                    if self._pump_done.wait(0.05):
                        break
                    continue
                try:
                    message = self._worker.receive(0.05)
                except AsrError as exc:
                    log.error("recording transcription stopped: %s", exc)
                    self._asr_lost.set()
                    continue
                if message and message.get("utterance_id") == uid:
                    yield message
                if self._pump_done.is_set():
                    break
            self._stop_capture()
            if self._pump_error:
                raise AsrError(self._pump_error)
            if not self._asr_lost.is_set():
                self._send(b"F", uid)
                deadline = time.monotonic() + self.cfg.asr.finish_timeout_secs
                while time.monotonic() < deadline:
                    message = self._worker.receive(0.1)
                    if not message or message.get("utterance_id") != uid:
                        continue
                    if message.get("kind") == "final":
                        return
                    yield message
                raise AsrError("Recording transcript did not finish; audio was saved.")
        finally:
            self._stop_capture()

    def _finish(self, uid):
        started = time.monotonic()
        self._send(b"F", uid, timeout=min(2, self.cfg.asr.finish_timeout_secs))
        result = self._wait_terminal(uid, "final", deadline=started + self.cfg.asr.finish_timeout_secs)
        log.info("asr final backend=%s finish_secs=%.2f", self.cfg.asr.backend, time.monotonic() - started)
        return result

    def _wait_terminal(self, uid, kind, *, deadline=None):
        if deadline is None:
            deadline = time.monotonic() + self.cfg.asr.finish_timeout_secs
        while time.monotonic() < deadline:
            message = self._worker.receive(min(0.1, max(0, deadline - time.monotonic())))
            if message and message.get("utterance_id") == uid and message.get("kind") == kind:
                return message
        raise AsrError(f"ASR {kind} timed out; request was not submitted.")

    def _send(self, kind, uid, payload=b"", *, timeout=2):
        self._worker.send(struct.pack(">cI", kind, uid) + payload, timeout=timeout)

    def _pump_audio(self, uid, on_audio=None):
        got = False
        tail = b""
        try:
            out = self._parec.stdout
            while not self._stop_pump.is_set():
                ready, _, _ = select.select([out], [], [], 0.05)
                if not ready:
                    continue
                data = os.read(out.fileno(), 3200)
                if not data:
                    if not got:
                        self._pump_error = MIC_ERROR
                    break
                got = True
                if on_audio is not None:
                    on_audio(data)
                    self._level_db = rms_dbfs(data)
                    if not self._asr_lost.is_set():
                        try:
                            self._send(b"A", uid, data)
                        except AsrError as exc:
                            log.error("recording transcription input stopped: %s", exc)
                            self._asr_lost.set()
                    continue
                data = tail + data
                frame_bytes = 640 if self._endpointer is not None else len(data) - len(data) % 2
                if not frame_bytes:
                    tail = data
                    continue
                offset = 0
                while len(data) - offset >= frame_bytes:
                    frame = data[offset:offset + frame_bytes]
                    offset += frame_bytes
                    self._level_db = rms_dbfs(frame)
                    self._send(b"A", uid, frame)
                    if self._endpointer is not None:
                        reason = self._endpointer.feed(frame)
                        if reason == "start_timeout":
                            self._endpointer.reset()
                        elif reason == "max_duration":
                            raise AsrError("Maximum utterance duration exceeded; request was not submitted.")
                        elif reason == "backend_failed":
                            raise AsrError("Voice activity detection stopped responding; request was not submitted.")
                        elif reason:
                            self._endpoint_reason = reason
                            return
                tail = data[offset:]
            if len(tail) >= 2:
                self._send(b"A", uid, tail[:len(tail) - len(tail) % 2])
        except (OSError, AsrError) as exc:
            if not self._stop_pump.is_set():
                self._pump_error = f"Microphone/ASR input failed: {exc}"
        finally:
            self._pump_done.set()

    def _stop_capture(self):
        self._stop_pump.set()
        if self._parec is not None and self._parec.poll() is None:
            self._parec.terminate()
            try:
                self._parec.wait(timeout=1)
            except subprocess.TimeoutExpired:
                self._parec.kill()
                self._parec.wait()
        if self._pump is not None:
            self._pump.join(timeout=3)
            if self._pump.is_alive():
                raise AsrError("Microphone pump did not stop.")
        if self._parec is not None and self._parec.stdout is not None:
            self._parec.stdout.close()

    def close(self):
        self._stop_capture()
        if self._endpointer is not None:
            self._endpointer.backend.close()
        self._worker.close()


def open_stream(cfg: Config, *, continuous: bool = False) -> StreamingRecognizer:
    return StreamingRecognizer(cfg, continuous=continuous)
