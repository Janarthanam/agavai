"""Measured sections: Speed, Interruption, Reliability, Footprint.

These sample a clock or the model at product settings, so they repeat only
within their spread. They run on an idle machine and record every sample.
"""

from __future__ import annotations

import json
import os
import statistics
import struct
import tempfile
import threading
import time
import tomllib
import urllib.request
import wave
from pathlib import Path
from typing import Any, Callable

from agavai.config import load_config
from agavai.tts import _play_interruptible

from evals.cases import Case, load_cases
from evals.graders import DONE, HONEST
from evals.voice import _speech_env, helper

BUDGETS = Path(__file__).with_name("budgets.toml")
NO_TOOL_PROBE = Case(id="probe.no-tool", section="speed", turns=[{"say": "what is fifteen percent of eighty", "kind": "answer", "number": 12}])


def load_budgets() -> dict[str, Any]:
    return tomllib.loads(BUDGETS.read_text(encoding="utf-8"))


def _busy(cfg) -> bool:
    try:
        with urllib.request.urlopen(f"{cfg.llm.base_url}/slots", timeout=2) as resp:
            slots = json.loads(resp.read())
        if any(slot.get("is_processing") for slot in slots):
            return True
    except (OSError, ValueError):
        pass
    state = Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")) / "agavai" / "state"
    try:
        return state.read_text().strip() in {"listening", "thinking", "speaking"}
    except OSError:
        return False


def _wait_idle(cfg, log) -> bool:
    for _ in range(60):
        if not _busy(cfg):
            return True
        time.sleep(1)
    log("measure: machine stayed busy; sample skipped")
    return False


def reliability_item(case_id: str, results: list[dict[str, Any]]) -> dict[str, Any]:
    runs = [r["outcome"] for r in results]
    all_done = bool(runs) and all(r == DONE for r in runs)
    return {"id": case_id, "outcome": DONE if all_done else HONEST, "runs": runs, "results": results,
            "reason": "done in every run" if all_done else f"{runs.count(DONE)} of {len(runs)} runs done"}


def check(name: str, samples: list[float | None], budget: float, marginal: float, basis: str) -> dict[str, Any]:
    """A checkpoint is met when the median sample is inside its budget. A missing sample counts as over."""
    present = [s for s in samples if s is not None]
    if not samples:
        return {"id": name, "outcome": "unscored", "reason": "no samples", "samples": [], "budget": budget, "basis": basis}
    ordered = sorted(float("inf") if s is None else s for s in samples)
    median = statistics.median(ordered)
    met = median <= budget
    return {
        "id": name,
        "outcome": DONE if met else HONEST,
        "reason": f"median {median:.2f}s against {budget}s" if median != float("inf") else f"most samples never happened (budget {budget}s)",
        "median": None if median == float("inf") else round(median, 3),
        "spread": [round(min(present), 3), round(max(present), 3)] if present else None,
        "samples": [None if s is None else round(s, 3) for s in samples],
        "budget": budget,
        "marginal": met and median >= budget * (1 - marginal),
        "basis": basis,
    }


def _synth_times(cfg, texts: list[str]) -> dict[str, Any]:
    _, paths = _speech_env(cfg)
    return helper(cfg, {"mode": "synth_time", "model": paths["model"], "voices": paths["voices"], "texts": texts})


def _silent_wav(seconds: float) -> Path:
    handle = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    with wave.open(handle, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(24000)
        wav.writeframes(struct.pack("<h", 0) * int(24000 * seconds))
    return Path(handle.name)


def cancel_latency(samples: int) -> list[float | None]:
    """The product's own playback loop, playing silence. Cancel is requested from
    another thread about half a second in; the clock runs from that request.
    Request times are spread across one 100 ms poll so the wait is not aligned."""
    out: list[float | None] = []
    for index in range(samples):
        flag = threading.Event()
        requested: list[float] = []

        def request() -> None:
            requested.append(time.monotonic())
            flag.set()

        timer = threading.Timer(0.5 + 0.1 * (index + 0.5) / samples, request)
        timer.start()
        outcome = _play_interruptible(_silent_wav(4.0), flag.is_set)
        ended = time.monotonic()
        timer.cancel()
        out.append(ended - requested[0] if outcome == "cancelled" and requested else None)
    return out


def _llama_rss_mb(cfg) -> float | None:
    for proc in Path("/proc").iterdir():
        if not proc.name.isdigit():
            continue
        try:
            cmd = (proc / "cmdline").read_bytes().replace(b"\0", b" ").decode()
            if "llama-server" in cmd and str(cfg.llm.port) in cmd:
                for line in (proc / "status").read_text().splitlines():
                    if line.startswith("VmRSS:"):
                        return round(int(line.split()[1]) / 1024, 1)
        except OSError:
            continue
    return None


def run_measure(out: Path, *, log: Callable[[str], None]) -> dict[str, Any]:
    from evals.runner import product_config, run_case

    budgets = load_budgets()
    samples = budgets["measure"]["samples"]
    marginal = budgets["measure"]["marginal"]
    cfg = product_config()
    cases = {c.id: c for c in load_cases()}
    voice = json.loads((out / "voice.json").read_text()) if (out / "voice.json").exists() else {}

    log("measure: reliability at product settings")
    reliability = []
    for case_id in budgets["reliability"]["cases"]:
        results = []
        for _ in range(budgets["reliability"]["runs"]):
            if _wait_idle(cfg, log):
                results.append(run_case(cases[case_id], cfg, set()))
        reliability.append(reliability_item(case_id, results))

    log("measure: speed")
    speed = []
    clean = [c for c in voice.get("clips", []) if c["group"] == "clean"]
    if clean:
        first = [None if c["first_interim_t"] is None else c.get("first_interim_ready_t", c["first_interim_t"] + c["step_mean_s"]) - c["speech_start_s"] for c in clean]
        commit = [c["commits"][0].get("ready_t", c["commits"][0]["t"] + c["step_mean_s"]) - c["speech_end_s"] if c["commits"] else None for c in clean]
        basis = "recognizer replay with sequential compute and audio arrival; excludes live IPC/capture jitter"
        if cfg.asr.mode == "streaming":
            speed.append(check("first_words", first, budgets["speed"]["first_words_s"], marginal, basis))
        if cfg.asr.endpoint == "native":
            speed.append(check("commit", commit, budgets["speed"]["commit_s"], marginal, basis + "; missing commits count as over"))
    changed, tool_reply, plain_reply, tool_texts, plain_texts = [], [], [], [], []
    for _ in range(samples):
        if _wait_idle(cfg, log):
            result = run_case(cases["desktop.volume.up"], cfg, set())
            turn = result["turns"][0]
            changed.append(turn["first_change_s"])
            tool_reply.append(turn["seconds"])
            tool_texts.append(turn["reply"])
        if _wait_idle(cfg, log):
            result = run_case(NO_TOOL_PROBE, cfg, set())
            plain_reply.append(result["turns"][0]["seconds"])
            plain_texts.append(result["turns"][0]["reply"])
    kokoro = _synth_times(load_config(), tool_texts + plain_texts)
    synth = kokoro["seconds"]
    # The product synthesizes the whole sentence, waits 0.2 s, then plays it.
    tool_audio = [r + s + 0.2 for r, s in zip(tool_reply, synth[: len(tool_texts)])]
    plain_audio = [r + s + 0.2 for r, s in zip(plain_reply, synth[len(tool_texts):])]
    basis = "the product's turn at product settings with a simulated desktop, plus warm Kokoro synthesis of the same reply and the 0.2 s pause before playback"
    speed.append(check("desktop_changed", changed, budgets["speed"]["desktop_changed_s"], marginal, "the product's turn at product settings; time until the simulated desktop changed"))
    speed.append(check("reply_audio_no_tool", plain_audio, budgets["speed"]["reply_audio_no_tool_s"], marginal, basis))
    speed.append(check("reply_audio_tool", tool_audio, budgets["speed"]["reply_audio_tool_s"], marginal, basis))

    log("measure: interruption")
    interruption = [
        check("cancel_stops_audio", cancel_latency(samples), budgets["interruption"]["cancel_stops_audio_s"], marginal,
              "the product's playback loop playing a silent clip, cancelled 0.5 s in"),
        {"id": "barge_in", "outcome": HONEST, "reason": "not built: speech cannot interrupt a reply", "needs": ["barge_in"]},
    ]

    footprint = {
        "unscored": "No footprint budgets are set (docs/eval.md open decision 6).",
        "llama_server_rss_mb": _llama_rss_mb(cfg),
        "recognizer_peak_rss_mb": (voice.get("recognizer") or {}).get("peak_rss_mb"),
        "recognizer_load_s": (voice.get("recognizer") or {}).get("load_s"),
        "recognizer_step_mean_s": round(statistics.mean(c["step_mean_s"] for c in clean), 4) if clean else None,
        "speech_peak_rss_mb": kokoro["peak_rss_mb"],
        "listening_idle_cpu": None,
        "listening_idle_cpu_note": "Not measured: needs a live listening session on the microphone.",
    }
    return {"speed": speed, "interruption": interruption, "reliability": reliability, "footprint": footprint,
            "samples": {"tool_replies": tool_texts, "plain_replies": plain_texts, "synth_seconds": synth}}
