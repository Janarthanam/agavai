"""Outcomes at the desktop-tool boundary."""
from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class ToolOutcome:
    text: str
    status: Literal["ok", "error", "unknown"] = "ok"


class ToolFailure(RuntimeError):
    pass
