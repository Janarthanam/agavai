from __future__ import annotations

import subprocess
import time
from pathlib import Path

from agavai.config import Config


def record_start(cfg: Config) -> None:
    cfg.runtime_dir.mkdir(parents=True, exist_ok=True)
    cfg.prompt_file.write_text("", encoding="utf-8")
    proc = subprocess.run(
        ["voxtype", "record", "start", f"--file={cfg.prompt_file}"],
        check=False,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip() or "voxtype start failed")


def record_stop() -> None:
    proc = subprocess.run(
        ["voxtype", "record", "stop"],
        check=False,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip() or "voxtype stop failed")


def record_cancel() -> None:
    subprocess.run(
        ["voxtype", "record", "cancel"],
        check=False,
        capture_output=True,
    )


def wait_for_prompt(path: Path, timeout_s: float = 25.0) -> str:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if path.is_file() and path.stat().st_size > 0:
            text = path.read_text(encoding="utf-8", errors="replace").strip()
            if text:
                return text
        time.sleep(0.1)
    return ""
