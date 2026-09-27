from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from oma_voice.config import Config


def speak(text: str, cfg: Config) -> None:
    text = " ".join(text.split())
    if not text:
        return
    notify(text)
    prefer = cfg.tts_prefer
    order = [prefer, "piper", "espeak"]
    seen: set[str] = set()
    for engine in order:
        if engine in seen:
            continue
        seen.add(engine)
        if engine == "piper" and _piper(text):
            return
        if engine == "espeak" and _espeak(text):
            return


def notify(text: str) -> None:
    if shutil.which("omarchy-notification-send"):
        subprocess.run(
            ["omarchy-notification-send", "-g", "󰨜", "Agavai", text[:200]],
            check=False,
            capture_output=True,
        )


def _espeak(text: str) -> bool:
    bin_ = shutil.which("espeak-ng") or shutil.which("espeak")
    if not bin_:
        return False
    proc = subprocess.run(
        [bin_, "-v", "en-us", "-s", "160", text[:800]],
        check=False,
        capture_output=True,
    )
    return proc.returncode == 0


def _piper(text: str) -> bool:
    piper = shutil.which("piper")
    play = shutil.which("pw-play") or shutil.which("paplay")
    voice = Path.home() / ".local/share/piper-voices/en_US-lessac-medium.onnx"
    if not piper or not play or not voice.is_file():
        return False
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        wav = tmp.name
    try:
        proc = subprocess.run(
            [piper, "-m", str(voice), "-f", wav],
            input=text[:800],
            text=True,
            check=False,
            capture_output=True,
        )
        if proc.returncode != 0:
            return False
        subprocess.run([play, wav], check=False, capture_output=True)
        return True
    finally:
        Path(wav).unlink(missing_ok=True)
