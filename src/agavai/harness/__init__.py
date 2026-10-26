"""Agavai's in-process control plane; models propose and the harness executes."""
from __future__ import annotations

from agavai.harness.context import ContextStore
from agavai.harness.events import EventSink, HarnessOutput


class Harness:
    def __init__(self, cfg, *, on_event: EventSink | None = None, should_cancel=None):
        self.cfg = cfg
        self.context = ContextStore()
        if should_cancel is not None:
            self.context.should_cancel = should_cancel
        self.output = HarnessOutput(self.context, on_event)
        self.output.begin_session()

    @property
    def should_cancel(self):
        return self.context.should_cancel

    @should_cancel.setter
    def should_cancel(self, callback):
        self.context.should_cancel = callback

    def run_turn(self, text: str, *, continue_conversation: bool = False) -> str:
        from agavai.harness.engine import run_turn
        return run_turn(text, self.cfg, self.output, context=self.context,
                        continue_conversation=continue_conversation)
