from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from agavai.config import Config


def speak(text: str, cfg: Config) -> str:
    """Speak text. Returns the engine used: kokoro, espeak, notify, or empty."""
    text = " ".join(text.split())
    if not text:
        return ""
    notify(text)
    prefer = (cfg.tts.prefer or "kokoro").lower()
    order = [prefer, "kokoro", "espeak"]
    seen: set[str] = set()
    for engine in order:
        if engine in seen or engine == "notify":
            continue
        seen.add(engine)
        if engine == "kokoro" and _kokoro(text, cfg):
            return "kokoro"
        if engine == "espeak" and _espeak(text):
            return "espeak"
    return "notify"


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


def _kokoro(text: str, cfg: Config) -> bool:
    py = cfg.tts.venv / "bin" / "python"
    script = Path(__file__).resolve().parents[2] / "scripts" / "kokoro_synth.py"
    if not py.is_file() or not script.is_file():
        return False
    if not cfg.tts.model_path.is_file() or not cfg.tts.voices_path.is_file():
        return False
    play = shutil.which("pw-play") or shutil.which("paplay")
    if not play:
        return False
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        wav = tmp.name
    env = os.environ.copy()
    env["CUDA_VISIBLE_DEVICES"] = ""
    try:
        proc = subprocess.run(
            [
                str(py),
                str(script),
                "--model",
                str(cfg.tts.model_path),
                "--voices",
                str(cfg.tts.voices_path),
                "--voice",
                cfg.tts.voice,
                "--out",
                wav,
                text[:800],
            ],
            check=False,
            capture_output=True,
            text=True,
            env=env,
            timeout=120,
        )
        if proc.returncode != 0 or not Path(wav).is_file() or Path(wav).stat().st_size < 44:
            return False
        played = subprocess.run([play, wav], check=False, capture_output=True)
        return played.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False
    finally:
        Path(wav).unlink(missing_ok=True)
