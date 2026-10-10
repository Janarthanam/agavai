"""The world a case acts on: plain state, with a record of every read and change.

Nothing here knows how the assistant reaches the world. Bindings translate a
route into `read` and `change` calls; graders compare snapshots.
"""

from __future__ import annotations

import copy
import tomllib
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

WORLD_DIR = Path(__file__).with_name("world")

# Changing these alters what is on screen, not what the person has.
VIEW_AREAS = {"launched", "urls", "pickers", "screenshots", "workspace", "focus", "fullscreen"}


@dataclass(frozen=True)
class Change:
    path: str
    before: Any
    after: Any

    @property
    def area(self) -> str:
        return self.path.split(".", 1)[0]

    @property
    def severity(self) -> str:
        return "view" if self.area in VIEW_AREAS else "state"


def load_world(name: str = "default") -> dict[str, Any]:
    return tomllib.loads((WORLD_DIR / f"{name}.toml").read_text(encoding="utf-8"))


def get_path(state: dict[str, Any], path: str) -> Any:
    node: Any = state
    for key in path.split("."):
        if isinstance(node, list):
            node = node[int(key)]
        elif isinstance(node, dict):
            node = node.get(key)
        else:
            return None
    return node


def set_path(state: dict[str, Any], path: str, value: Any) -> None:
    keys = path.split(".")
    node = state
    for key in keys[:-1]:
        node = node.setdefault(key, {})
    node[keys[-1]] = value


class World:
    def __init__(self, state: dict[str, Any], now: datetime) -> None:
        self.state = state
        self.now = now
        self.ops: list[dict[str, str]] = []

    def read(self, area: str, detail: str = "") -> None:
        self.ops.append({"op": "read", "area": area, "detail": detail})

    def change(self, area: str, detail: str = "") -> None:
        self.ops.append({"op": "change", "area": area, "detail": detail})

    def snapshot(self) -> dict[str, Any]:
        return copy.deepcopy(self.state)


def flatten(state: dict[str, Any]) -> dict[str, Any]:
    """Two levels deep: `audio.volume`, `mail.outbox`. Lists compare whole."""
    flat: dict[str, Any] = {}
    for area, value in state.items():
        if isinstance(value, dict):
            for key, inner in value.items():
                flat[f"{area}.{key}"] = inner
        else:
            flat[area] = value
    return flat


def changes(before: dict[str, Any], after: dict[str, Any]) -> list[Change]:
    old, new = flatten(before), flatten(after)
    return [
        Change(path, old.get(path), new.get(path))
        for path in sorted(set(old) | set(new))
        if old.get(path) != new.get(path)
    ]
