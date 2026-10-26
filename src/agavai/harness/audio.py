"""Bounded accepted-turn capture and asynchronous audio attachment publication."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import hashlib
import os
import shutil
import tempfile
import wave

from agavai.harness.storage import timestamp
from agavai.meter import rms_dbfs
from agavai.recording import _encode


class TurnAudio:
    def __init__(self, cfg):
        self.file = tempfile.SpooledTemporaryFile(max_size=256 * 1024)
        self.limit = int(cfg.asr.max_utterance_secs * 32000)
        self.threshold = cfg.vad.close_threshold_dbfs
        self.started = timestamp()
        self.offset = 0
        self.start = None
        self.end = 0
        self.error = ""
        self.transferred = False

    def write(self, pcm: bytes) -> None:
        self.offset += len(pcm)
        if self.error:
            return
        try:
            voiced = rms_dbfs(pcm) >= self.threshold
            if self.start is None:
                if not voiced:
                    return
                self.start = self.offset - len(pcm)
            if self.file.tell() + len(pcm) > self.limit:
                self.error = "Accepted-turn audio exceeded the capture limit."
                return
            self.file.write(pcm)
            if voiced:
                self.end = self.file.tell()
        except OSError as exc:
            self.error = f"Could not spool turn audio: {exc}"

    def discard(self):
        if not self.transferred:
            self.close()

    def close(self):
        self.file.close()


class AudioAttachments:
    def __init__(self, harness):
        self.harness = harness
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="agavai-audio")
        self.pending = []
        self.notices = []

    def accept(self, capture, request_id):
        repository = self.harness.repository
        sid = self.harness.context.session_id
        metadata = {"status": "writing", "bytes": capture.end + 44,
                    "sample_rate": 16000, "channels": 1, "sample_width": 2,
                    "captured_at": capture.started, "duration_ms": capture.end // 32,
                    "source_start_ms": (capture.start or 0) // 32,
                    "source_end_ms": ((capture.start or 0) + capture.end) // 32,
                    "path": str((repository.folder(sid) / "audio" / (request_id + ".writing") / "audio.wav").relative_to(repository.root))}
        if capture.error or not capture.end or len(self.pending) >= 2:
            metadata.update(status="failed", warning=capture.error or (
                "No voiced audio was captured." if not capture.end else "Audio finalizer queue is full."), bytes=0)
        elif not repository.reserve_audio(sid, request_id, metadata, self.harness.cfg.sessions.max_audio_mb):
            metadata.update(status="quota_exceeded", warning="Session audio quota reached; transcript retained.", bytes=0)
        else:
            capture.transferred = True
            self.pending.append((request_id, self.pool.submit(self._finalize, capture, request_id, metadata)))
            return
        capture.close()
        repository.set_audio(sid, request_id, metadata)
        self.notices.append((request_id, metadata))

    def _finalize(self, capture, request_id, metadata):
        repository = self.harness.repository
        sid = self.harness.context.session_id
        parent = repository.folder(sid) / "audio"
        staging = parent / (request_id + ".writing")
        try:
            staging.mkdir(mode=0o700, parents=True)
            capture.file.seek(0)
            capture.file.truncate(capture.end)
            with wave.open(str(staging / "audio.wav"), "wb") as wav:
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(16000)
                while data := capture.file.read(65536):
                    wav.writeframesraw(data)
            warning = _encode(staging, timeout=15)
            source = staging / ("audio.wav" if warning else "audio.opus")
            with source.open("rb") as stream:
                os.fsync(stream.fileno())
                checksum = hashlib.file_digest(stream, "sha256").hexdigest()
            target = parent / (request_id + source.suffix)
            source.replace(target)
            directory = os.open(parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
            metadata.update(status="ready", path=str(target.relative_to(repository.root)),
                            codec="pcm_s16le" if warning else "opus", sha256=checksum,
                            bytes=target.stat().st_size, warning=warning)
            shutil.rmtree(staging)
        except OSError as exc:
            metadata.update(status="failed", warning=f"Could not save turn audio: {exc}")
        finally:
            capture.close()
        repository.set_audio(sid, request_id, metadata)
        return metadata

    def publish(self):
        remaining = []
        for request_id, future in self.pending:
            if future.done():
                self.notices.append((request_id, future.result()))
            else:
                remaining.append((request_id, future))
        self.pending = remaining
        for request_id, metadata in self.notices:
            with self.harness.repository.connect() as db:
                task_id = db.execute("SELECT task_id FROM turns WHERE session_id=? AND request_id=?",
                    (self.harness.context.session_id, request_id)).fetchone()[0]
            self.harness.output.emit("audio_status", request_id=request_id, task_id=task_id, **metadata)
        self.notices.clear()

    def close(self):
        self.pool.shutdown(wait=True)
        self.publish()
