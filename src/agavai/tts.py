from __future__ import annotations

import json
import math
import os
import shutil
import signal
import socket
import struct
import subprocess
import sys
import tempfile
import time
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from agavai.config import Config

_RATE = 24000

_PLAYBACK_WAVS: list[Path] = []


def speak(text: str, cfg: Config) -> str:
    """Speak text. Returns the engine used: kokoro, espeak, notify, or empty."""
    text = " ".join(text.split())
    if not text:
        return ""
    prefer = (cfg.tts.prefer or "kokoro").lower()
    order = [prefer, "kokoro", "espeak"]
    seen: set[str] = set()
    for engine in order:
        if engine in seen or engine == "notify":
            continue
        seen.add(engine)
        if engine == "kokoro" and _kokoro(text, cfg):
            print("agavai: speaking (kokoro)", file=sys.stderr)
            return "kokoro"
        if engine == "espeak" and _espeak(text):
            print("agavai: speaking (espeak)", file=sys.stderr)
            return "espeak"
    notify(text)
    print("agavai: TTS failed; notification only", file=sys.stderr)
    return "notify"


def notify(text: str) -> None:
    if shutil.which("omarchy-notification-send"):
        subprocess.run(
            ["omarchy-notification-send", "-g", "󰨜", "Agavai", text[:200]],
            check=False,
            capture_output=True,
        )


def cue_listen(cfg: Config) -> None:
    """Instant Siri-style chime, then start warming Kokoro in the background."""
    _play_tones(((880, 0.07), (1320, 0.11)))
    ensure_tts_server(cfg)


def cue_think(cfg: Config) -> None:
    """Immediate 'working on it' while the LLM runs. Prefers a pre-rendered Kokoro clip."""
    ack = cfg.runtime_dir / "ack-on-it.wav"
    if ack.is_file() and ack.stat().st_size > 44:
        _play_wav(ack, wait=False)
    else:
        _play_tones(((660, 0.06), (660, 0.06)))
    ensure_tts_server(cfg)


def ensure_tts_server(cfg: Config) -> None:
    if _tts_ping(cfg):
        return
    py = cfg.tts.venv / "bin" / "python"
    script = _synth_script()
    if not py.is_file() or not script.is_file():
        return
    if not cfg.tts.model_path.is_file() or not cfg.tts.voices_path.is_file():
        return
    cfg.runtime_dir.mkdir(parents=True, exist_ok=True)
    sock = _sock_path(cfg)
    if sock.exists():
        try:
            sock.unlink()
        except OSError:
            return
    env = os.environ.copy()
    env["CUDA_VISIBLE_DEVICES"] = ""
    log = cfg.runtime_dir / "kokoro-serve.log"
    ack = cfg.runtime_dir / "ack-on-it.wav"
    with log.open("a", encoding="utf-8") as errf:
        subprocess.Popen(
            [
                str(py),
                str(script),
                "--model",
                str(cfg.tts.model_path),
                "--voices",
                str(cfg.tts.voices_path),
                "--voice",
                cfg.tts.voice,
                "--serve",
                str(sock),
                "--ack",
                str(ack),
            ],
            stdout=errf,
            stderr=errf,
            env=env,
            start_new_session=True,
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


def _kokoro(text: str, cfg: Config, *, keep_wav: bool = False) -> str | None:
    play = shutil.which("pw-play") or shutil.which("paplay")
    if not play:
        return None
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        wav = tmp.name
    if keep_wav:
        ok = _kokoro_synth(text, cfg, wav)
        if not ok or not Path(wav).is_file() or Path(wav).stat().st_size < 44:
            Path(wav).unlink(missing_ok=True)
            return None
        return wav
    try:
        ok = _kokoro_synth(text, cfg, wav)
        if not ok or not Path(wav).is_file() or Path(wav).stat().st_size < 44:
            return None
        time.sleep(0.2)
        played = _play_wav(Path(wav), wait=True)
        return wav if played else None
    finally:
        Path(wav).unlink(missing_ok=True)


def _kokoro_synth(text: str, cfg: Config, wav: str) -> bool:
    if _tts_ping(cfg):
        return _kokoro_socket(text, cfg, wav)
    ensure_tts_server(cfg)
    for _ in range(40):
        time.sleep(0.25)
        if _tts_ping(cfg):
            return _kokoro_socket(text, cfg, wav)
    return _kokoro_oneshot(text, cfg, wav)


def _kokoro_socket(text: str, cfg: Config, wav: str) -> bool:
    try:
        conn = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        conn.settimeout(30)
        conn.connect(str(_sock_path(cfg)))
        req = json.dumps({"text": text[:800], "out": wav, "voice": cfg.tts.voice}) + "\n"
        conn.sendall(req.encode())
        raw = b""
        while not raw.endswith(b"\n"):
            chunk = conn.recv(4096)
            if not chunk:
                break
            raw += chunk
        conn.close()
        data = json.loads(raw.decode() or "{}")
        return bool(data.get("ok"))
    except (OSError, json.JSONDecodeError, TimeoutError):
        return False


def _kokoro_oneshot(text: str, cfg: Config, wav: str) -> bool:
    py = cfg.tts.venv / "bin" / "python"
    script = _synth_script()
    if not py.is_file() or not script.is_file():
        return False
    if not cfg.tts.model_path.is_file() or not cfg.tts.voices_path.is_file():
        return False
    env = os.environ.copy()
    env["CUDA_VISIBLE_DEVICES"] = ""
    cfg.runtime_dir.mkdir(parents=True, exist_ok=True)
    log = cfg.runtime_dir / "kokoro.log"
    try:
        with log.open("w", encoding="utf-8") as errf:
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
                stdout=errf,
                stderr=errf,
                env=env,
                timeout=120,
            )
        if proc.returncode != 0:
            print(f"agavai: kokoro synth failed (see {log})", file=sys.stderr)
            return False
        return True
    except (subprocess.TimeoutExpired, OSError) as exc:
        print(f"agavai: kokoro error: {exc}", file=sys.stderr)
        return False


def _tts_ping(cfg: Config) -> bool:
    sock = _sock_path(cfg)
    if not sock.exists():
        return False
    try:
        conn = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        conn.settimeout(0.4)
        conn.connect(str(sock))
        conn.sendall(b'{"cmd":"ping"}\n')
        raw = b""
        while not raw.endswith(b"\n"):
            chunk = conn.recv(256)
            if not chunk:
                break
            raw += chunk
        conn.close()
        return bool(json.loads(raw.decode() or "{}").get("ok"))
    except (OSError, json.JSONDecodeError, TimeoutError):
        return False


def _sock_path(cfg: Config) -> Path:
    return cfg.runtime_dir / "kokoro.sock"


def _synth_script() -> Path:
    return Path(__file__).resolve().parents[2] / "scripts" / "kokoro_synth.py"


def _play_tones(notes: tuple[tuple[int, float], ...]) -> None:
    play = shutil.which("pw-play") or shutil.which("paplay")
    if not play:
        return
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        path = Path(tmp.name)
    try:
        _write_tones(path, notes)
        _play_wav(path, wait=False)
    except OSError:
        path.unlink(missing_ok=True)


def _write_tones(path: Path, notes: tuple[tuple[int, float], ...]) -> None:
    samples: list[int] = []
    for freq, dur in notes:
        n = int(_RATE * dur)
        for i in range(n):
            env = min(1.0, i / 80, (n - i) / 80)
            samples.append(int(12000 * env * math.sin(2 * math.pi * freq * i / _RATE)))
        samples.extend([0] * int(_RATE * 0.03))
    with wave.open(str(path), "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(_RATE)
        wf.writeframes(b"".join(struct.pack("<h", s) for s in samples))


def _play_wav(path: Path, *, wait: bool) -> bool:
    play = shutil.which("pw-play") or shutil.which("paplay")
    if not play or not path.is_file():
        return False
    argv = [play, "--media-role", "Speech", "--volume", "1.0", str(path)]
    if wait:
        played = subprocess.run(argv, check=False, capture_output=True, text=True)
        if played.returncode != 0:
            print(
                f"agavai: pw-play failed: {(played.stderr or played.stdout or '')[:400]}",
                file=sys.stderr,
            )
            return False
        return True
    subprocess.Popen(argv, start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return True


@dataclass
class PlaybackHandle:
    wav: Path
    proc: Any


def sweep_playback_wavs() -> None:
    for wav in list(_PLAYBACK_WAVS):
        try:
            Path(wav).unlink(missing_ok=True)
        except OSError:
            pass
    _PLAYBACK_WAVS.clear()


def _interruptible_speak(
    text: str,
    cfg: Config,
    *,
    stop_requested: Callable[[], bool] | None = None,
    poll_s: float = 0.1,
) -> str:
    """Listener-routed playback: synth + owned pw-play group + poll loop.

    Returns "completed" | "cancelled" | "silent". Mirrors speak's engine
    order [prefer, kokoro, espeak]. A top notification is only the fallback
    when no speech engine can play the reply.
    """
    text = " ".join(text.split())
    if not text:
        return "silent"
    cancelled = stop_requested if stop_requested is not None else (lambda: False)
    prefer = (cfg.tts.prefer or "kokoro").lower()
    order = [prefer, "kokoro", "espeak"]
    seen: set[str] = set()
    for engine in order:
        if engine in seen or engine == "notify":
            continue
        seen.add(engine)
        if engine == "kokoro":
            wav = _kokoro(text, cfg, keep_wav=True)
            if wav is None:
                continue
            return _play_interruptible(Path(wav), cancelled, poll_s=poll_s)
        if engine == "espeak":
            if _espeak(text):
                return "silent"
            continue
    notify(text)
    print("agavai: TTS failed; notification only", file=sys.stderr)
    return "silent"


def _play_interruptible(
    wav: Path, cancelled: Callable[[], bool], *, poll_s: float = 0.1
) -> str:
    play = shutil.which("pw-play") or shutil.which("paplay")
    if not play or not wav.is_file():
        wav.unlink(missing_ok=True)
        return "silent"
    argv = [play, "--media-role", "Speech", "--volume", "1.0", str(wav)]
    proc = subprocess.Popen(
        argv,
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    handle = PlaybackHandle(wav=wav, proc=proc)
    _PLAYBACK_WAVS.append(wav)
    slice_s = min(poll_s, 0.1)
    try:
        while True:
            if proc.poll() is not None:
                return "completed"
            if cancelled():
                _kill_playback(proc)
                return "cancelled"
            time.sleep(slice_s)
            if proc.poll() is not None:
                return "completed"
            if cancelled():
                _kill_playback(proc)
                return "cancelled"
    finally:
        try:
            if proc.poll() is None:
                _kill_playback(proc)
        finally:
            wav.unlink(missing_ok=True)
            if wav in _PLAYBACK_WAVS:
                _PLAYBACK_WAVS.remove(wav)


def _kill_playback(proc: Any) -> None:
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
    except (OSError, ProcessLookupError):
        try:
            os.kill(proc.pid, signal.SIGTERM)
        except (OSError, ProcessLookupError):
            pass
    try:
        proc.wait(timeout=1.0)
    except Exception:
        try:
            proc.kill()
        except OSError:
            pass
        try:
            proc.wait(timeout=1.0)
        except Exception:
            pass
