"""Session snapshot for the top-of-screen chat overlay."""

from __future__ import annotations

import json
import shutil
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any

from agavai.config import Config
from agavai.canvas import display_for, OPEN_EXTS
from agavai.richtext import rich_text

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
            "transcript": {"text": "", "final": False},
        }
        # The overlay is session-scoped: a fresh ui.json starts blank even if
        # an old one on disk still holds the previous session.
        if self.path.is_file():
            try:
                loaded = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    for key in ("level_db", "vad_state", "vad_backend", "display", "ts", "transcript", "answer_html", "error"):
                        loaded.pop(key, None)
                    self.data.update(loaded)
                    self.data["turns"] = []
            except (OSError, json.JSONDecodeError):
                pass

    def begin_session(self) -> None:
        """Reset the overlay to a blank session: prior turns and canvas drop."""
        self.data["turns"] = []
        self.data["transcript"] = {"text": "", "final": False}
        self.data.pop("answer_html", None)
        self.data.pop("error", None)
        self.data["level_db"] = None
        self.data["vad_state"] = "off"
        self.data["vad_backend"] = "off"
        self.data.pop("display", None)
        self.data["session_id"] = uuid.uuid4().hex

    def listening(self) -> None:
        self.begin_session()
        self._set_phase("listening", "Listening")
        self._write(summon=True)

    def cancelled(self) -> bool:
        try:
            return (self.cfg.runtime_dir / "dismissed-session").read_text() == self.data.get("session_id")
        except OSError:
            return False

    def partial(self, text: str) -> None:
        if self.data.get("phase") == "listening":
            self.data["transcript"] = {"text": text.strip(), "final": False}
            self._write()

    def display(self, block: dict[str, Any] | None) -> None:
        """Structured canvas for meaningful output (lists, images, cards)."""
        if block is None:
            self.data.pop("display", None)
        else:
            self.data["display"] = block
        self._write()

    def level(self, db: float | None, vad_state: str, vad_backend: str) -> None:
        """Throttled 10 Hz mic level + VAD state while listening."""
        self.data["level_db"] = db
        self.data["vad_state"] = vad_state
        self.data["vad_backend"] = vad_backend
        self._write()

    def vad_state(self, state: str) -> None:
        self.data["vad_state"] = state
        self._write()

    def transcribing(self) -> None:
        self._set_phase("transcribing", "Transcribing")
        self._write()

    def user(self, text: str) -> None:
        self.data.pop("display", None)
        self.data.pop("error", None)
        self.data.pop("answer_html", None)
        self.data["transcript"] = {"text": text.strip(), "final": True}
        if not self.data.get("session_id"):
            self.data["session_id"] = uuid.uuid4().hex
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
        block = display_for(name, result)
        if block is not None:
            self.data["display"] = block
        self._write()

    def assistant(self, text: str) -> None:
        turn = self._current_turn()
        turn["assistant"] = text.strip()
        self.data["answer_html"] = rich_text(text.strip())
        self._set_phase("speaking", "Speaking")
        self._write()

    def idle(self) -> None:
        self._set_phase("idle", "Idle")
        self._write()

    def error(self, text: str) -> None:
        self.data["error"] = text
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
        if phase != "listening":
            self.data["level_db"] = None
        if self.data.get("phase") != phase:
            self.data["ts"] = int(time.time() * 1000)
        self.data["phase"] = phase
        self.data["phase_label"] = label
        self.data["model_id"] = self.cfg.llm.model_id

    def _write(self, *, summon: bool = False) -> None:
        if self.cancelled():
            return
        self.cfg.runtime_dir.mkdir(parents=True, exist_ok=True)
        blob = json.dumps(self.data, ensure_ascii=False, indent=2) + "\n"
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(blob, encoding="utf-8")
        tmp.replace(self.path)
        if summon:
            summon_overlay()


def summon_overlay() -> bool:
    payload = "{}"
    for argv in (
        ["omarchy", "shell", "shell", "summon", PLUGIN_ID, payload],
        ["omarchy-shell", "shell", "summon", PLUGIN_ID, payload],
    ):
        if not shutil.which(argv[0]):
            continue
        try:
            proc = subprocess.run(argv, check=False, capture_output=True, timeout=3)
            if proc.returncode == 0:
                return True
        except (OSError, subprocess.TimeoutExpired):
            continue
    return False


def hide_overlay() -> None:
    for argv in (
        ["omarchy", "shell", "-q", "shell", "hide", PLUGIN_ID],
        ["omarchy-shell", "shell", "hide", PLUGIN_ID],
    ):
        if not shutil.which(argv[0]):
            continue
        subprocess.run(argv, check=False, capture_output=True, timeout=3)


def open_result(cfg: Config, index: int, session: str) -> bool:
    """Open only a document/media item from the currently displayed session."""
    try:
        data = json.loads((cfg.runtime_dir / "ui.json").read_text(encoding="utf-8"))
        if not session or str(data.get("session_id")) != session or index < 0:
            return False
        item = data.get("display", {}).get("items", [])[index]
        path = Path(str(item.get("path") or ""))
        allowed = path.is_dir() and item.get("kind") == "folder" or path.is_file() and path.suffix.lower() in OPEN_EXTS
        if not item.get("openable") or not path.is_absolute() or not allowed:
            return False
        subprocess.Popen(["xdg-open", str(path)], start_new_session=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except (OSError, ValueError, IndexError, KeyError, TypeError, AttributeError):
        return False


def cancel_ui(cfg: Config) -> None:
    """Keep late completions from replacing a cancelled session's snapshot."""
    path = cfg.runtime_dir / "ui.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        session = str(data.get("session_id") or "")
        if session:
            (cfg.runtime_dir / "dismissed-session").write_text(session)
        data.update(phase="idle", phase_label="Cancelled", level_db=None)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False) + "\n", encoding="utf-8")
        tmp.replace(path)
    except (OSError, ValueError, AttributeError):
        pass
