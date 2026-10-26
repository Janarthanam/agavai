"""Agavai's in-process control plane; models propose and the harness executes."""
from __future__ import annotations

from agavai.harness.context import ContextStore
from agavai.harness.events import EventSink, HarnessOutput


class Harness:
    def __init__(self, cfg, *, on_event: EventSink | None = None, should_cancel=None, session_id: str | None = None):
        self.cfg = cfg
        self.context = ContextStore()
        self.repository = None
        self._lease = None
        self._closed = False
        self.input_mode = "typed"
        self._capture = None
        self._audio = None
        sequence, recovered = 0, False
        try:
            if cfg.sessions.enabled:
                from agavai.harness.storage import SessionRepository, configuration
                self.repository = SessionRepository(cfg.sessions.dir)
                if session_id:
                    self.repository.get(session_id)
                self._lease = self.repository.claim(session_id or self.context.session_id)
                if session_id:
                    self.context, sequence, recovered = self.repository.resume(session_id)
                else:
                    self.repository.create(self.context, cfg)
            elif session_id:
                raise ValueError("Cannot resume a session while persistence is disabled.")
            if should_cancel is not None:
                self.context.should_cancel = should_cancel
            record = self._record if self.repository else None
            self.output = HarnessOutput(self.context, on_event, on_record=record)
            self.output.sequence = sequence
            metadata = {"persistent": self.repository is not None,
                        "history": self.repository.list() if self.repository else [],
                        "directory": str(cfg.sessions.dir) if self.repository else None}
            if session_id:
                self.output.emit("session_resumed", **metadata, recovered=recovered,
                                 recovery_required=self.context.recovery_required, status=self.context.turn_status,
                                 configuration=configuration(cfg))
            else:
                self.output.begin_session(**metadata)
        except Exception:
            if self._lease:
                self._lease.close()
            raise

    def _record(self, event):
        self.repository.record(event, self.context, mode=self.input_mode)
        if event.kind == "request_committed" and self._capture is not None:
            capture, self._capture = self._capture, None
            try:
                self._audio.accept(capture, event.request_id)
            except Exception:
                capture.close()
                raise

    @property
    def should_cancel(self):
        return self.context.should_cancel

    @should_cancel.setter
    def should_cancel(self, callback):
        self.context.should_cancel = callback

    def run_turn(self, text: str, *, continue_conversation: bool = False, audio=None) -> str:
        from agavai.harness.engine import run_turn
        if self._closed:
            raise ValueError("This harness session is closed.")
        self._capture = audio
        try:
            self.poll_audio()
            return run_turn(text, self.cfg, self.output, context=self.context,
                            continue_conversation=continue_conversation)
        finally:
            if self._capture is not None:
                self._capture.close()
                self._capture = None
            if self.repository:
                self.repository.save(self.context)
            self.poll_audio()

    def poll_audio(self):
        if self._audio:
            self._audio.publish()

    def capture_audio(self):
        if not self.repository or not self.cfg.sessions.save_audio:
            return None
        from agavai.harness.audio import TurnAudio, AudioAttachments
        if self._audio is None:
            self._audio = AudioAttachments(self)
        return TurnAudio(self.cfg)

    def close(self) -> None:
        if self._closed:
            return
        try:
            if self._audio:
                self._audio.close()
            self.output.emit("session_closed")
        finally:
            self._closed = True
            if self._lease:
                self._lease.close()
