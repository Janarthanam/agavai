"""Outcomes at the desktop-tool boundary."""
from dataclasses import dataclass


@dataclass(frozen=True)
class ToolOutcome:
    text: str
    status: str = "ok"


class ToolFailure(RuntimeError):
    pass
