"""A recording's folder: the audio, its timed transcript, and what was marked.

While recording, audio goes to a growing WAV and each committed line to
segments.jsonl, so a crash leaves both recoverable. Stopping encodes Opus,
then writes recording.json, the source of truth, and a readable
transcript.md generated from it.
"""

from __future__ import annotations

import json
import fcntl
import shutil
import subprocess
import sys
import threading
import time
import wave
from datetime import datetime
from pathlib import Path
from typing import Any

from agavai.config import Config

SAMPLE_RATE = 16000
WAV_HEADER_BYTES = 44
# Recognition reports a line's first word late; play from a little earlier.
LEAD_MS = 300
LIVE_LINES = 30
# Whole committed utterances only, as with the assistant's controls: longer speech is content.
CONTROLS = {
    "agavai stop": "stop",
    "agavai stop recording": "stop",
    "agavai pause": "pause",
    "agavai resume": "resume",
    "agavai mark": "mark",
}


def control(text: str) -> str | None:
    return CONTROLS.get(" ".join(text.strip().rstrip(".!?…").replace(",", " ").casefold().split()))


def clock(ms: int) -> str:
    seconds = max(0, ms) // 1000
    hours, rest = divmod(seconds, 3600)
    minutes, seconds = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{seconds:02d}" if hours else f"{minutes:02d}:{seconds:02d}"


def line_text(segment: dict[str, Any]) -> str:
    return segment.get("corrected") or segment.get("final") or segment.get("live") or ""


class Recorder:
    """One recording in progress. audio() runs on the capture thread; the rest on the session thread.

    The recognizer hears everything, pauses included, so "Agavai resume" can
    be heard. Its clock therefore runs ahead of the audio file by the paused
    time, and lines are moved onto the audio file's clock.
    """

    def __init__(self, cfg: Config, *, now: datetime | None = None) -> None:
        started = now or datetime.now()
        self.dir = _new_folder(cfg.recordings.dir, started)
        self.meta: dict[str, Any] = {
            "title": "Recording",
            "started": started.isoformat(timespec="seconds"),
            "status": "recording",
            "audio": "audio.wav",
            "duration_ms": 0,
            "segments": [],
            "marks": [],
            "pauses": [],
        }
        _write_meta(self.dir, self.meta)
        self._wav_file = (self.dir / "audio.wav").open("wb")
        self._wav = wave.open(self._wav_file, "wb")
        self._wav.setnchannels(1)
        self._wav.setsampwidth(2)
        self._wav.setframerate(SAMPLE_RATE)
        self._journal = (self.dir / "segments.jsonl").open("a", encoding="utf-8")
        self._lock = threading.Lock()
        self.samples = 0
        self.heard = 0
        self.paused = False
        self._gaps: list[list[int]] = []
        self.error = ""

    def audio(self, pcm: bytes) -> None:
        """Append captured PCM unless paused. Never raises: a failed write is kept in error and ends the recording."""
        with self._lock:
            self.heard += len(pcm) // 2
            if self.paused or self.error:
                return
            self._append(pcm)

    def _append(self, pcm: bytes) -> None:
        try:
            # writeframes rewrites the header sizes each call, so the file stays playable.
            self._wav.writeframes(pcm)
            self._wav_file.flush()
        except OSError as exc:
            self.error = f"Recording stopped: {exc.strerror or exc}."
            return
        self.samples += len(pcm) // 2

    def elapsed_ms(self) -> int:
        return self.samples * 1000 // SAMPLE_RATE

    def _audio_ms(self, heard_ms: int) -> tuple[int, bool]:
        """The audio file's time for a recognizer time, and whether it fell in a pause.

        A time inside a pause maps to the point where the pause sits in the audio.
        """
        heard = heard_ms * SAMPLE_RATE // 1000
        skipped = 0
        in_pause = False
        with self._lock:
            for start, end in self._gaps:
                if heard < start:
                    break
                if end is None or heard < end:
                    heard, in_pause = start, True
                    break
                skipped += end - start
        return (heard - skipped) * 1000 // SAMPLE_RATE, in_pause

    def add_line(self, text: str, heard_start_ms: int, heard_end_ms: int) -> dict[str, Any] | None:
        """Keep a committed line at its recognizer times; a line spoken entirely while paused is not kept."""
        start_ms, started_paused = self._audio_ms(heard_start_ms)
        end_ms, ended_paused = self._audio_ms(heard_end_ms)
        if started_paused and ended_paused:
            return None
        segments = self.meta["segments"]
        previous_end = segments[-1]["end_ms"] if segments else 0
        line = {
            "id": len(segments) + 1,
            "start_ms": max(previous_end, start_ms - LEAD_MS, 0),
            "end_ms": max(end_ms, start_ms),
            "live": text,
        }
        segments.append(line)
        self._log({"segment": line})
        return line

    def mark(self, label: str = "") -> dict[str, Any]:
        mark = {"at_ms": self.elapsed_ms(), "label": label}
        self.meta["marks"].append(mark)
        self._log({"mark": mark})
        return mark

    def pause(self) -> None:
        """Paused audio is not kept, so the pause is a point on the timeline."""
        with self._lock:
            if self.paused:
                return
            self.paused = True
            self._gaps.append([self.heard, None])
        at = self.elapsed_ms()
        self.meta["pauses"].append(at)
        self._log({"pause": at})

    def resume(self) -> None:
        with self._lock:
            if self.paused:
                self.paused = False
                self._gaps[-1][1] = self.heard

    def live(self, partial: str, transcribing: bool) -> dict[str, Any]:
        """What the overlay shows while recording. Nothing heard during a pause is shown."""
        entries = [(s["start_ms"], {"time": clock(s["start_ms"]), "text": line_text(s)}) for s in self.meta["segments"]]
        entries += [(m["at_ms"], {"time": clock(m["at_ms"]), "text": m["label"] or "Mark", "mark": True}) for m in self.meta["marks"]]
        lines = [entry for _, entry in sorted(entries, key=lambda entry: entry[0])]
        return {
            "path": str(self.dir),
            "elapsed_ms": self.elapsed_ms(),
            "at": int(time.time() * 1000),
            "paused": self.paused,
            "lines": lines[-LIVE_LINES:],
            "partial": "" if self.paused else partial,
            "transcribing": transcribing,
        }

    def discard_if_empty(self) -> bool:
        """A recording that captured nothing leaves no folder behind."""
        if self.samples:
            return False
        self._wav.close()
        self._wav_file.close()
        self._journal.close()
        shutil.rmtree(self.dir)
        return True

    def finish(self) -> Path:
        self._wav.close()
        self._wav_file.close()
        self._journal.close()
        self.meta["duration_ms"] = self.elapsed_ms()
        _finalize(self.dir, self.meta)
        return self.dir

    def _log(self, entry: dict[str, Any]) -> None:
        self._journal.write(json.dumps(entry, ensure_ascii=False) + "\n")
        self._journal.flush()


def recover(cfg: Config) -> list[Path]:
    """Finish folders a crash left in the recording state. Call only with no live recorder."""
    root = cfg.recordings.dir
    if not root.is_dir():
        return []
    recovered = []
    for folder in sorted(root.iterdir()):
        meta = _read_meta(folder)
        if not meta or meta.get("status") != "recording":
            continue
        try:
            _recover(folder, meta)
        except (OSError, KeyError, ValueError, wave.Error) as exc:
            # One damaged folder must not stop a new recording; it stays for a later attempt.
            print(f"agavai: could not recover {folder}: {exc}", file=sys.stderr)
            continue
        recovered.append(folder)
    return recovered


def _recover(folder: Path, meta: dict[str, Any]) -> None:
    journal = folder / "segments.jsonl"
    if journal.is_file():
        for raw in journal.read_text(encoding="utf-8").splitlines():
            try:
                entry = json.loads(raw)
            except json.JSONDecodeError:
                continue  # the last line can be cut off by the crash
            if "segment" in entry:
                meta["segments"].append(entry["segment"])
            elif "mark" in entry:
                meta["marks"].append(entry["mark"])
            elif "pause" in entry:
                meta["pauses"].append(entry["pause"])
    meta["duration_ms"] = _repair_wav(folder / "audio.wav")
    meta["recovered"] = True
    _finalize(folder, meta)


def recordings(cfg: Config) -> list[dict[str, Any]]:
    """Saved recordings, newest first."""
    root = cfg.recordings.dir
    rows = []
    for folder in root.iterdir() if root.is_dir() else []:
        meta = _read_meta(folder)
        if meta and meta.get("status") == "ready":
            rows.append({
                "title": meta["title"],
                "started": meta["started"],
                "duration_ms": meta["duration_ms"],
                "lines": len(meta["segments"]),
                "path": str(folder),
            })
    return sorted(rows, key=lambda row: row["started"], reverse=True)


def correct(folder: Path, segment_id: int, text: str, *, expected_text: str | None = None) -> None:
    """Serialize correction overlays and reject stale source-derived edits."""
    if not folder.is_dir():
        raise ValueError(f"No recording in {folder}")
    with (folder / ".edit.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        meta = _read_meta(folder)
        if not meta:
            raise ValueError(f"No recording in {folder}")
        for segment in meta["segments"]:
            if segment["id"] == segment_id:
                if expected_text is not None and line_text(segment) != expected_text:
                    raise ValueError("The transcript changed before that correction. Please request the edit again.")
                text = " ".join(text.split())
                heard = segment.get("final") or segment.get("live") or ""
                if text and text != heard:
                    segment["corrected"] = text
                else:
                    segment.pop("corrected", None)
                break
        else:
            raise ValueError(f"No line {segment_id} in {folder.name}")
        _write_meta(folder, meta)
        _write_transcript(folder, meta)

def _new_folder(root: Path, started: datetime) -> Path:
    base = f"{started:%Y-%m-%d %H.%M} Recording"
    root.mkdir(parents=True, exist_ok=True)
    for n in range(1, 1000):
        folder = root / (base if n == 1 else f"{base} {n}")
        try:
            folder.mkdir()
            return folder
        except FileExistsError:
            continue
    raise OSError(f"Too many recordings named {base!r} in {root}")


def _finalize(folder: Path, meta: dict[str, Any]) -> None:
    """Encode the audio, then publish recording.json and transcript.md. The journal goes last."""
    error = _encode(folder) if meta["duration_ms"] else "Nothing was recorded."
    meta["audio"] = "audio.wav" if error else "audio.opus"
    if error:
        meta["audio_error"] = error
    else:
        meta.pop("audio_error", None)
    meta["status"] = "ready"
    _write_meta(folder, meta)
    _write_transcript(folder, meta)
    (folder / "segments.jsonl").unlink(missing_ok=True)


def _encode(folder: Path) -> str:
    """Opus from the WAV. The WAV is deleted only once the Opus file has the same length."""
    wav = folder / "audio.wav"
    opus = folder / "audio.opus"
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        return "ffmpeg is not installed, so the audio stays uncompressed."
    proc = subprocess.run(
        ["ffmpeg", "-nostdin", "-loglevel", "error", "-y", "-i", str(wav),
         "-c:a", "libopus", "-b:a", "24k", "-application", "voip", str(opus)],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        opus.unlink(missing_ok=True)
        return (proc.stderr.strip().splitlines() or ["ffmpeg could not encode the audio."])[-1]
    expected = _seconds(wav)
    encoded = _seconds(opus)
    if expected is None or encoded is None or abs(encoded - expected) > 1.0:
        opus.unlink(missing_ok=True)
        return "The compressed audio did not match the recording, so the original is kept."
    wav.unlink()
    return ""


def _seconds(path: Path) -> float | None:
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True,
    )
    try:
        return float(proc.stdout.strip())
    except ValueError:
        return None


def _repair_wav(path: Path) -> int:
    """Rewrite the header from the bytes that reached the disk; returns the duration in ms."""
    if not path.is_file():
        return 0
    pcm = path.read_bytes()[WAV_HEADER_BYTES:]
    pcm = pcm[: len(pcm) - len(pcm) % 2]
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(SAMPLE_RATE)
        wav.writeframes(pcm)
    return len(pcm) // 2 * 1000 // SAMPLE_RATE


def _read_meta(folder: Path) -> dict[str, Any] | None:
    try:
        meta = json.loads((folder / "recording.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return meta if isinstance(meta, dict) else None


def _write_meta(folder: Path, meta: dict[str, Any]) -> None:
    tmp = folder / "recording.json.tmp"
    tmp.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(folder / "recording.json")


def _write_transcript(folder: Path, meta: dict[str, Any]) -> None:
    started = datetime.fromisoformat(meta["started"])
    lines = [f"# {meta['title']}", "", f"{started:%A %d %B %Y, %H:%M} · {clock(meta['duration_ms'])}", ""]
    entries = [(s["start_ms"], f"[{clock(s['start_ms'])}] {line_text(s)}") for s in meta["segments"]]
    entries += [(m["at_ms"], f"⚑ [{clock(m['at_ms'])}] {m['label'] or 'Mark'}") for m in meta["marks"]]
    entries += [(at, f"⏸ [{clock(at)}] Paused") for at in meta["pauses"]]
    lines += [text for _, text in sorted(entries, key=lambda entry: entry[0])]
    tmp = folder / "transcript.md.tmp"
    tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    tmp.replace(folder / "transcript.md")
