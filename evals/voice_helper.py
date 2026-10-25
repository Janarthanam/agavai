"""Run synthesis in the TTS environment or recognition in its selected ASR environment.

One JSON request/response on stdin/stdout. Recognition uses the product speech
adapters with 160 ms PCM packets (20 ms for VAD). Native EOU or VAD commits automatically; manual mode
simulates Enter at clip end. Replay timing excludes live capture/IPC jitter.
"""

from __future__ import annotations

import json
import resource
import sys
import time
import wave
from pathlib import Path

import statistics

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
    import numpy as np
    samples = np.asarray(samples, dtype=np.float32).reshape(-1)
    if rate == RATE:
        return samples
    times = np.arange(int(len(samples) * RATE / rate)) * (rate / RATE)
    return np.interp(times, np.arange(len(samples)), samples).astype(np.float32)


def _write(path: Path, samples: np.ndarray) -> None:
    import numpy as np
    pcm = (np.clip(samples, -1.0, 1.0) * 32767).astype("<i2")
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(RATE)
        wav.writeframes(pcm.tobytes())


def synth(req: dict) -> dict:
    import numpy as np
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
    from types import SimpleNamespace
    from agavai.config import VadConfig
    from agavai.meter import streaming_endpointer
    from agavai.speech_backends import create_backend

    events: list[dict] = []
    cfg = SimpleNamespace(**req["asr"])
    endpointer = streaming_endpointer(VadConfig(**req["vad"])) if cfg.endpoint == "vad" else None
    started = time.perf_counter()
    stream = create_backend(cfg, lambda kind, text: events.append({"kind": kind, "text": text}))
    load_s = time.perf_counter() - started
    results = []
    for clip in req["clips"]:
        with wave.open(clip["path"]) as wav:
            if (wav.getframerate(), wav.getnchannels(), wav.getsampwidth()) != (RATE, 1, 2):
                raise ValueError("Replay requires 16 kHz mono PCM16 WAV")
            pcm = wav.readframes(wav.getnframes())
        if len(pcm) > cfg.max_utterance_secs * RATE * 2:
            raise ValueError("Replay exceeds maximum utterance duration")
        stream.start()
        if endpointer is not None:
            endpointer.reset()
        events.clear()
        timeline, commits, step_seconds = [], [], []
        pending = ""
        ready_at = 0.0
        chunk_bytes = 640 if endpointer is not None else CHUNK * 2
        for offset in range(0, len(pcm), chunk_bytes):
            seen = len(events)
            tick = time.perf_counter()
            chunk = pcm[offset:offset + chunk_bytes]
            stream.feed(chunk)
            reason = endpointer.feed(chunk) if endpointer is not None else None
            step_s = time.perf_counter() - tick
            step_seconds.append(step_s)
            at = min(len(pcm), offset + chunk_bytes) / (RATE * 2)
            ready_at = max(ready_at, at) + step_s
            finish = reason == "silence"
            for event in events[seen:]:
                timeline.append({**event, "t": round(at, 3), "ready_t": round(ready_at, 3)})
                if event["kind"] == "endpoint" and cfg.endpoint == "native":
                    finish = True
                else:
                    pending = event["text"]
            if reason == "max_duration":
                raise ValueError("Maximum utterance duration exceeded; request was not submitted")
            if reason == "backend_failed":
                raise ValueError("Voice activity detection stopped responding")
            if reason == "start_timeout":
                endpointer.reset()
            if finish or reason == "min_speech":
                if finish:
                    tick = time.perf_counter()
                    text = stream.finish()
                    ready_at += time.perf_counter() - tick
                    commits.append({"text": text, "t": round(at, 3), "ready_t": round(ready_at, 3)})
                pending = ""
                stream.cancel()
                stream.start()
                if endpointer is not None:
                    endpointer.reset()
        if cfg.endpoint == "manual":
            tick = time.perf_counter()
            final = stream.finish()
            ready_at += time.perf_counter() - tick
            commits.append({"text": final, "t": len(pcm) / (RATE * 2), "ready_t": round(ready_at, 3)})
            pending = ""
        stream.cancel()
        first = next((e for e in timeline if e["kind"] == "partial" and e["text"]), {})
        results.append({
            "id": clip["id"],
            "commits": commits,
            "uncommitted": pending,
            "first_interim_t": first.get("t"),
            "first_interim_ready_t": first.get("ready_t"),
            "endpoint": cfg.endpoint,
            "interims": sum(e["kind"] == "partial" for e in timeline),
            "step_mean_s": round(statistics.fmean(step_seconds), 4) if step_seconds else 0.0,
            "step_max_s": round(max(step_seconds), 4) if step_seconds else 0.0,
        })
    return {"clips": results, "load_s": round(load_s, 2), "peak_rss_mb": round(_peak_rss_mb(), 1),
            "backend": cfg.backend, "endpoint": cfg.endpoint, "mode": cfg.mode}


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
