"""A single bounded inference slot; only the controller may dispatch tools."""
from __future__ import annotations

import threading
from queue import Empty, Queue

from agavai.llm import LlmError
from agavai import journal


class TurnCancelled(LlmError):
    pass


class InferenceSlot:
    def __init__(self):
        self.running: threading.Thread | None = None

    def call(self, operation, cancelled):
        if cancelled():
            raise TurnCancelled()
        if self.running and self.running.is_alive():
            raise LlmError("The previous model request is still stopping. Please try again shortly.")
        reply = Queue(maxsize=1)
        request = journal._request
        def infer():
            with journal.request_scope(request):
                try:
                    reply.put((operation(), None))
                except Exception as exc:
                    reply.put((None, exc))
        self.running = threading.Thread(target=infer, name="agavai-inference", daemon=True)
        self.running.start()
        while True:
            if cancelled():
                raise TurnCancelled()
            try:
                value, error = reply.get(timeout=0.05)
            except Empty:
                continue
            self.running.join()
            if cancelled():
                raise TurnCancelled()
            if error is not None:
                raise error
            return value
