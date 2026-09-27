"""Session snapshot for the top-of-screen chat overlay."""

from __future__ import annotations

import json
import shutil
import subprocess
from typing import Any

from agavai.config import Config

PLUGIN_ID = "janar.agavai"
MAX_TURNS = 5
RESULT_CHARS = 280


def _clip(text: str, limit: int = RESULT_CHARS) -> str:
    text = " ".join(str(text).split())
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


class ChatUi:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.path = cfg.runtime_dir / "ui.json"
        self.data: dict[str, Any] = {
            "phase": "idle",
            "phase_label": "Idle",
            "model_id": cfg.llm.model_id,
            "turns": [],
        }
        if self.path.is_file():
            try:
                loaded = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    self.data.update(loaded)
                    if not isinstance(self.data.get("turns"), list):
                        self.data["turns"] = []
            except (OSError, json.JSONDecodeError):
                pass

    def listening(self) -> None:
        self._set_phase("listening", "Listening")
        self._write(summon=True)

    def transcribing(self) -> None:
        self._set_phase("transcribing", "Transcribing")
        self._write()

    def user(self, text: str) -> None:
        self._set_phase("thinking", "Thinking")
        turns = list(self.data.get("turns") or [])
        turns.append({"user": text.strip(), "tools": [], "assistant": ""})
        self.data["turns"] = turns[-MAX_TURNS:]
        self._write(summon=True)

    def tool_start(self, name: str, arguments: Any) -> None:
        args = arguments if isinstance(arguments, str) else json.dumps(arguments, ensure_ascii=False)
        turn = self._current_turn()
        turn["tools"].append(
            {
                "name": name,
                "args": _clip(args, 160),
                "result": "",
                "status": "running",
            }
        )
        self._set_phase("thinking", f"Calling {name}")
        self._write()

    def tool_done(self, name: str, result: str) -> None:
        turn = self._current_turn()
        for tool in reversed(turn["tools"]):
            if tool.get("name") == name and tool.get("status") == "running":
                tool["result"] = _clip(result)
                tool["status"] = "ok"
                break
        self._write()

    def assistant(self, text: str) -> None:
        turn = self._current_turn()
        turn["assistant"] = text.strip()
        self._set_phase("speaking", "Speaking")
        self._write()

    def idle(self) -> None:
        self._set_phase("idle", "Idle")
        self._write()

    def error(self, text: str) -> None:
        self._set_phase("error", "Error")
        turn = self._current_turn()
        if not turn["user"] and not turn["tools"] and not turn["assistant"]:
            turn["assistant"] = text
        elif not turn["assistant"]:
            turn["assistant"] = text
        self._write()

    def _current_turn(self) -> dict[str, Any]:
        turns = list(self.data.get("turns") or [])
        if not turns:
            turns.append({"user": "", "tools": [], "assistant": ""})
            self.data["turns"] = turns
        return turns[-1]

    def _set_phase(self, phase: str, label: str) -> None:
        self.data["phase"] = phase
        self.data["phase_label"] = label
        self.data["model_id"] = self.cfg.llm.model_id

    def _write(self, *, summon: bool = False) -> None:
        self.cfg.runtime_dir.mkdir(parents=True, exist_ok=True)
        blob = json.dumps(self.data, ensure_ascii=False, indent=2) + "\n"
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(blob, encoding="utf-8")
        tmp.replace(self.path)
        if summon:
            summon_overlay()


def summon_overlay() -> None:
    payload = "{}"
    for argv in (
        ["omarchy", "shell", "-q", "shell", "summon", PLUGIN_ID, payload],
        ["omarchy-shell", "shell", "summon", PLUGIN_ID, payload],
    ):
        if not shutil.which(argv[0]):
            continue
        subprocess.run(argv, check=False, capture_output=True, timeout=3)


def hide_overlay() -> None:
    for argv in (
        ["omarchy", "shell", "-q", "shell", "hide", PLUGIN_ID],
        ["omarchy-shell", "shell", "hide", PLUGIN_ID],
    ):
        if not shutil.which(argv[0]):
            continue
        subprocess.run(argv, check=False, capture_output=True, timeout=3)
