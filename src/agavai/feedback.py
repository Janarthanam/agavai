"""Listening / thinking cues. Matches F9 dictation: Omarchy OSD + transient unmute."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from agavai.config import Config

UNMUTE_FLAG = "unmuted-by-us"


def osd_show(message: str, *, icon: str = "microphone", duration: int = 0) -> None:
    payload = json.dumps(
        {"icon": icon, "message": message, "duration": duration},
        separators=(",", ":"),
    )
    for argv in (
        ["omarchy", "shell", "-q", "osd", "show", payload],
        ["omarchy-shell", "osd", "show", payload],
    ):
        if not shutil.which(argv[0]):
            continue
        proc = subprocess.run(argv, check=False, capture_output=True, text=True)
        if proc.returncode == 0:
            return


def osd_close() -> None:
    for argv in (
        ["omarchy", "shell", "-q", "osd", "close"],
        ["omarchy-shell", "osd", "close"],
    ):
        if not shutil.which(argv[0]):
            continue
        subprocess.run(argv, check=False, capture_output=True)


def _source_muted() -> bool:
    proc = subprocess.run(
        ["pactl", "get-source-mute", "@DEFAULT_SOURCE@"],
        check=False,
        capture_output=True,
        text=True,
    )
    return "yes" in (proc.stdout or "").lower()


def _set_source_mute(mute: bool) -> None:
    subprocess.run(
        ["pactl", "set-source-mute", "@DEFAULT_SOURCE@", "1" if mute else "0"],
        check=False,
        capture_output=True,
    )


def _keyboard_mute(on: bool) -> None:
    bin_ = shutil.which("omarchy-brightness-keyboard-mute")
    if not bin_:
        return
    subprocess.run([bin_, "on" if on else "off"], check=False, capture_output=True)


def _flag(cfg: Config) -> Path:
    return cfg.runtime_dir / UNMUTE_FLAG


def prepare_listen(cfg: Config) -> None:
    """Unmute if needed and hold the Listening OSD until hide_listen()."""
    cfg.runtime_dir.mkdir(parents=True, exist_ok=True)
    flag = _flag(cfg)
    if _source_muted():
        _set_source_mute(False)
        flag.write_text("1\n", encoding="utf-8")
        _keyboard_mute(False)
    else:
        flag.unlink(missing_ok=True)
    # Visual feedback is the bottom voice overlay (janar.agavai), not this OSD.


def hide_listen(cfg: Config) -> None:
    flag = _flag(cfg)
    if flag.is_file():
        _set_source_mute(True)
        flag.unlink(missing_ok=True)
        _keyboard_mute(True)
    osd_close()


def show_phase(message: str, *, icon: str = "microphone") -> None:
    osd_show(message, icon=icon, duration=0)


def finish(cfg: Config) -> None:
    hide_listen(cfg)
    osd_close()
