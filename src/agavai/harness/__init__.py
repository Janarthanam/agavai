"""Agavai's in-process control plane; models propose and the harness executes."""
from __future__ import annotations

from agavai.harness.context import ContextStore


class Harness:
    def __init__(self, cfg, ui=None):
        self.cfg = cfg
        self.ui = ui
        self.context = ContextStore()
        self.should_cancel = lambda: False

    def run_turn(self, text: str, *, continue_conversation: bool = False) -> str:
        from agavai.harness.engine import run_turn
        return run_turn(text, self.cfg, self.ui, context=self.context,
                        continue_conversation=continue_conversation)
