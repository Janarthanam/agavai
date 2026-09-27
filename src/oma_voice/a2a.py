from __future__ import annotations

import json

from oma_voice.config import Config


CARD = {
    "name": "oma-voice",
    "description": "Local Omarchy voice assistant. Voxtype ears, Qwen3-4B brain, MCP desktop tools.",
    "url": "stdio://oma-voice",
    "version": "0.1.0",
    "capabilities": {"streaming": False},
    "skills": [
        {"id": "desktop", "name": "Omarchy desktop", "description": "Launch apps, themes, workspaces, reminders."},
        {"id": "files", "name": "Local files", "description": "Search allowed home roots with fd."},
        {"id": "screen", "name": "Screen context", "description": "Focused window title plus OCR. No pixel click in v1."},
        {"id": "media", "name": "Web media", "description": "Open https URLs including YouTube."},
    ],
    "authentication": {"schemes": []},
}


def write_card(cfg: Config) -> None:
    cfg.a2a_dir.mkdir(parents=True, exist_ok=True)
    path = cfg.a2a_dir / "oma-voice.json"
    path.write_text(json.dumps(CARD, indent=2) + "\n", encoding="utf-8")
