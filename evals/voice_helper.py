"""Runs in the Agavai speech venv (numpy, onnxruntime, kokoro-onnx).

Reads one JSON request on stdin and writes one JSON answer on stdout:

    {"mode": "synth", ...}      synthesize clips to 16 kHz mono PCM16 WAV
    {"mode": "recognize", ...}  replay WAVs through the streaming recognizer
    {"mode": "synth_time", ...} time warm Kokoro synthesis of reply texts

Recognition feeds the recognizer's own Stream 160 ms at a time and resets it
after each end of utterance, as the listen session does, so commits are a
function of the audio alone.
"""

from __future__ import annotations

import json
import resource
import sys
import time
import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

RATE = 16000
CHUNK = 2560


def _peak_rss_mb() -> float:
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024


def _kokoro(model: str, voices: str):
    from kokoro_onnx import Kokoro

    try:
        return Kokoro(model, voices, providers=["CPUExecutionProvider"])
    except TypeError:
        return Kokoro(model, voices)


def _to_16k(samples: np.ndarray, rate: int) -> np.ndarray:
    samples = np.asarray(samples, dtype=np.float32).reshape(-1)
    if rate == RATE:
        return samples
    times = np.arange(int(len(samples) * RATE / rate)) * (rate / RATE)
    return np.interp(times, np.arange(len(samples)), samples).astype(np.float32)


def _write(path: Path, samples: np.ndarray) -> None:
    pcm = (np.clip(samples, -1.0, 1.0) * 32767).astype("<i2")
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(RATE)
        wav.writeframes(pcm.tobytes())


def synth(req: dict) -> dict:
    kokoro = _kokoro(req["model"], req["voices"])
    out = []
    for item in req["items"]:
        rng = np.random.default_rng(item.get("seed", 0))
        parts = [np.zeros(int(RATE * item.get("lead_ms", 500) / 1000), np.float32)]
        start = len(parts[0]) / RATE
        for seg in item["segments"]:
            if "pause_ms" in seg:
                parts.append(np.zeros(int(RATE * seg["pause_ms"] / 1000), np.float32))
                continue
            if "noise_ms" in seg:
                parts.append((rng.standard_normal(int(RATE * seg["noise_ms"] / 1000)) * seg.get("level", 0.03)).astype(np.float32))
                continue
            samples, rate = kokoro.create(seg["text"], voice=seg.get("voice", "af_bella"), speed=seg.get("speed", 1.0), lang="en-us")
            parts.append(_to_16k(samples, rate))
        end = sum(len(p) for p in parts) / RATE
        parts.append(np.zeros(int(RATE * item.get("tail_ms", 2500) / 1000), np.float32))
        audio = np.concatenate(parts)
        if item.get("snr_db") is not None:
            speech = audio[int(start * RATE):int(end * RATE)]
            rms = float(np.sqrt(np.mean(speech ** 2))) if speech.size else 0.05
            noise = rng.standard_normal(audio.size).astype(np.float32)
            audio = audio + noise * rms / (10 ** (item["snr_db"] / 20))
        _write(Path(item["out"]), audio)
        out.append({"id": item["id"], "speech_start_s": round(start, 3), "speech_end_s": round(end, 3), "duration_s": round(audio.size / RATE, 3)})
    return {"clips": out, "peak_rss_mb": round(_peak_rss_mb(), 1)}


def recognize(req: dict) -> dict:
    import agavai.parakeet_worker as worker

    events: list[dict] = []
    worker.emit = lambda kind, text="": events.append({"kind": kind, "text": text})
    started = time.perf_counter()
    stream = worker.Stream(req["model_dir"], "cpu")
    load_s = time.perf_counter() - started
    results = []
    for clip in req["clips"]:
        with wave.open(clip["path"]) as wav:
            pcm = np.frombuffer(wav.readframes(wav.getnframes()), dtype="<i2").astype(np.float32) / 32768.0
        stream.reset()
        events.clear()
        timeline, commits, step_seconds = [], [], []
        pending = ""
        for offset in range(0, len(pcm), CHUNK):
            seen = len(events)
            tick = time.perf_counter()
            stream.feed(pcm[offset:offset + CHUNK])
            step_seconds.append(time.perf_counter() - tick)
            at = min(len(pcm), offset + CHUNK) / RATE
            for event in events[seen:]:
                timeline.append({**event, "t": round(at, 3)})
                if event["kind"] == "eou":
                    commits.append({"text": event["text"], "t": round(at, 3)})
                    pending = ""
                    stream.reset()
                else:
                    pending = event["text"]
        first = next((e["t"] for e in timeline if e["kind"] == "interim"), None)
        results.append({
            "id": clip["id"],
            "commits": commits,
            "uncommitted": pending,
            "first_interim_t": first,
            "interims": sum(e["kind"] == "interim" for e in timeline),
            "step_mean_s": round(float(np.mean(step_seconds)), 4) if step_seconds else 0.0,
            "step_max_s": round(float(np.max(step_seconds)), 4) if step_seconds else 0.0,
        })
    return {"clips": results, "load_s": round(load_s, 2), "peak_rss_mb": round(_peak_rss_mb(), 1)}


def synth_time(req: dict) -> dict:
    kokoro = _kokoro(req["model"], req["voices"])
    kokoro.create("Warming up.", voice=req.get("voice", "af_bella"), speed=1.0, lang="en-us")
    timings = []
    for text in req["texts"]:
        tick = time.perf_counter()
        kokoro.create(text, voice=req.get("voice", "af_bella"), speed=1.0, lang="en-us")
        timings.append(round(time.perf_counter() - tick, 3))
    return {"seconds": timings, "peak_rss_mb": round(_peak_rss_mb(), 1)}


if __name__ == "__main__":
    request = json.loads(sys.stdin.read())
    answer = {"synth": synth, "recognize": recognize, "synth_time": synth_time}[request["mode"]](request)
    sys.stdout.write(json.dumps(answer))
