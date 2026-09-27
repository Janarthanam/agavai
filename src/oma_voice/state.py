from __future__ import annotations

from oma_voice.config import Config

VALID = {"idle", "listening", "transcribing", "thinking", "speaking", "error"}


def read_state(cfg: Config) -> str:
    path = cfg.state_file
    if not path.is_file():
        return "idle"
    value = path.read_text(encoding="utf-8").strip()
    return value if value in VALID else "idle"


def write_state(cfg: Config, value: str) -> None:
    if value not in VALID:
        raise ValueError(value)
    cfg.runtime_dir.mkdir(parents=True, exist_ok=True)
    tmp = cfg.state_file.with_suffix(".tmp")
    tmp.write_text(value + "\n", encoding="utf-8")
    tmp.replace(cfg.state_file)
