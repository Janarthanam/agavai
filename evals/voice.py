"""Voice sections: Hearing, Turn taking, Spoken tasks, Speech output.

Clips are synthesized once with Kokoro and kept under evals/audio/, named by
a hash of their specification. The recognizer is the one the product runs.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Callable

from agavai.config import Config, load_config

from evals.cases import load_cases
from evals.graders import DONE, HONEST, numbers_in

AUDIO = Path(__file__).with_name("audio")
HELPER = Path(__file__).with_name("voice_helper.py")
VOICE = "af_bella"
# Eight seconds of room tone after speech: the recognizer, not the clip, decides when the turn ends.
TAIL_MS = 8000
FLOOR_SNR_DB = 45

# Requests from shipped cases: (text, words that decide the action, case id).
REQUESTS = [
    ("turn the volume up", ["volume", "up"], "desktop.volume.up"),
    ("remind me in ten minutes to check the oven", ["remind", "ten", "oven"], "desktop.reminder"),
    ("set the theme to gruvbox", ["theme", "gruvbox"], "desktop.theme.set"),
    ("switch to workspace three", ["workspace", "three"], "values.workspace.three"),
    ("lock the screen", ["lock", "screen"], "desktop.lock"),
    ("open the browser", ["open", "browser"], "desktop.launch.browser"),
    ("find the budget notes", ["budget", "notes"], "files.find.budget"),
    ("set brightness to forty percent", ["brightness", "forty"], "values.brightness.forty"),
    ("turn on do not disturb", ["disturb"], "desktop.dnd.on"),
    ("take a screenshot", ["screenshot"], "desktop.screenshot"),
    ("what is my battery level", ["battery"], "desktop.battery"),
    ("set the wallpaper to ship at sea", ["wallpaper", "ship", "sea"], "desktop.wallpaper.set"),
]
OTHER_VOICES = ("am_michael", "bf_emma")
NOISY = 6
FAST = 4

# Speech the recognizer must not cut short or invent: (id, segments, expected commits as key lists).
TURN_CLIPS = [
    ("pause.700ms", [{"text": "remind me in ten minutes"}, {"pause_ms": 700}, {"text": "to check the oven"}], [["remind", "oven"]]),
    ("pause.1200ms", [{"text": "set the theme to"}, {"pause_ms": 1200}, {"text": "gruvbox"}], [["theme", "gruvbox"]]),
    ("hesitation", [{"text": "turn the um"}, {"pause_ms": 500}, {"text": "volume up"}], [["volume", "up"]]),
    ("long-request", [{"text": "find the budget notes from last year and the meeting notes from september please"}], [["budget", "september"]]),
    ("two-requests", [{"text": "open the browser"}, {"pause_ms": 2500}, {"text": "lock the screen"}], [["browser"], ["lock"]]),
    ("silence", [{"pause_ms": 4000}], []),
    ("noise", [{"noise_ms": 4000, "level": 0.02}], []),
]

NAMES = ["gruvbox", "nord", "home net", "homenet", "catppuccin", "rose pine", "tokyo night", "ship at sea", "neon city",
         "mountain dawn", "firefox", "spotify", "signal", "oven", "bank", "stretch", "friday", "budget", "laundry"]


def _speech_env(cfg: Config) -> tuple[str, dict[str, str]]:
    python = str(Path(cfg.asr.venv).expanduser() / "bin" / "python")
    paths = {"model": str(cfg.tts.model_path), "voices": str(cfg.tts.voices_path), "model_dir": str(Path(cfg.asr.model_dir).expanduser())}
    return python, paths


def helper(cfg: Config, request: dict[str, Any], timeout: int = 1800) -> dict[str, Any]:
    python, _ = _speech_env(cfg)
    proc = subprocess.run([python, "-I", str(HELPER)], input=json.dumps(request), capture_output=True, text=True, timeout=timeout, check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"voice helper failed: {proc.stderr[-1500:]}")
    return json.loads(proc.stdout)


def clip_specs() -> list[dict[str, Any]]:
    specs = []
    for index, (text, keys, case_id) in enumerate(REQUESTS):
        specs.append({"id": f"clean.{VOICE}.{index:02d}", "group": "clean", "text": text, "keys": keys, "case": case_id,
                      "segments": [{"text": text, "voice": VOICE}], "seed": index})
        voice = OTHER_VOICES[index % len(OTHER_VOICES)]
        specs.append({"id": f"voice.{voice}.{index:02d}", "group": "voices", "text": text, "keys": keys,
                      "segments": [{"text": text, "voice": voice}], "seed": index})
        if index < NOISY:
            specs.append({"id": f"noise.10db.{index:02d}", "group": "noise", "text": text, "keys": keys, "snr_db": 10, "seed": index,
                          "segments": [{"text": text, "voice": VOICE}]})
        if index < FAST:
            specs.append({"id": f"fast.{index:02d}", "group": "fast", "text": text, "keys": keys,
                          "segments": [{"text": text, "voice": VOICE, "speed": 1.3}], "seed": index})
    for name, segments, expected in TURN_CLIPS:
        specs.append({"id": f"turn.{name}", "group": "turn", "text": " ".join(s.get("text", "") for s in segments).strip(),
                      "expected": expected, "segments": [{**s, "voice": VOICE} if "text" in s else s for s in segments], "seed": 7})
    for spec in specs:
        spec.setdefault("snr_db", FLOOR_SNR_DB)
        spec["tail_ms"] = TAIL_MS
        key = json.dumps({k: spec.get(k) for k in ("segments", "snr_db", "seed", "tail_ms")}, sort_keys=True)
        spec["file"] = str(AUDIO / f"{spec['id']}-{hashlib.sha256(key.encode()).hexdigest()[:10]}.wav")
    return specs


def ensure_clips(cfg: Config, specs: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Synthesize missing clips. Speech start and end are kept in a manifest beside them."""
    manifest_path = AUDIO / "manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    missing = [s for s in specs if not Path(s["file"]).exists() or Path(s["file"]).name not in manifest]
    if missing:
        _, paths = _speech_env(cfg)
        items = [{"id": s["id"], "segments": s["segments"], "snr_db": s["snr_db"], "seed": s.get("seed", 0), "tail_ms": s["tail_ms"], "out": s["file"]} for s in missing]
        answer = helper(cfg, {"mode": "synth", "model": paths["model"], "voices": paths["voices"], "items": items})
        for spec, clip in zip(missing, answer["clips"]):
            manifest[Path(spec["file"]).name] = clip
        AUDIO.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return {s["id"]: manifest[Path(s["file"]).name] for s in specs}


def recognize(cfg: Config, clips: list[dict[str, str]]) -> dict[str, Any]:
    _, paths = _speech_env(cfg)
    return helper(cfg, {"mode": "recognize", "model_dir": paths["model_dir"], "clips": clips})


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", " ", text.lower())


def has_word(transcript: str, word: str) -> bool:
    flat = _norm(transcript)
    return word in flat.split() or word.replace(" ", "") in flat.replace(" ", "")


def word_errors(reference: str, hypothesis: str) -> tuple[int, int]:
    ref, hyp = _norm(reference).split(), _norm(hypothesis).split()
    row = list(range(len(hyp) + 1))
    for i, r in enumerate(ref, 1):
        prev, row[0] = row[0], i
        for j, h in enumerate(hyp, 1):
            prev, row[j] = row[j], min(row[j] + 1, row[j - 1] + 1, prev + (r != h))
    return row[len(hyp)], len(ref)


def heard_text(heard: dict[str, Any]) -> str:
    """What the person's words became: committed lines, plus what Enter would still commit."""
    return " ".join([*(c["text"] for c in heard["commits"]), heard.get("uncommitted", "")]).strip()


def grade_hearing(spec: dict[str, Any], heard: dict[str, Any]) -> dict[str, Any]:
    transcript = heard_text(heard)
    missing = [k for k in spec["keys"] if not has_word(transcript, k)]
    errors, words = word_errors(spec["text"], transcript)
    outcome = DONE if not missing else HONEST
    reason = "done" if not missing else f"lost {', '.join(missing)}"
    return {"id": spec["id"], "group": spec["group"], "text": spec["text"], "transcript": transcript, "outcome": outcome,
            "reason": reason, "word_errors": errors, "words": words}


def grade_turns(spec: dict[str, Any], heard: dict[str, Any], timing: dict[str, Any]) -> dict[str, Any]:
    """The number of commits and when the last one came. Whether the words are right is Hearing's question."""
    expected = spec.get("expected", [spec.get("keys", [])])
    commits = heard["commits"]
    problems = []
    if len(commits) != len(expected):
        problems.append(f"{len(commits)} commits, expected {len(expected)}")
    elif commits and commits[-1]["t"] < timing["speech_end_s"]:
        problems.append(f"last commit at {commits[-1]['t']}s, before speech ended at {timing['speech_end_s']}s")
    return {"id": spec["id"], "group": spec["group"], "text": spec["text"], "commits": commits,
            "outcome": DONE if not problems else HONEST, "reason": problems[0] if problems else "done"}


def key_tokens(reply: str) -> tuple[set[float], list[str]]:
    lowered = reply.lower()
    return numbers_in(reply), [n for n in NAMES if n in lowered]


def speech_output_candidates(case_results: list[dict[str, Any]], limit: int = 12) -> list[dict[str, str]]:
    picks = []
    for result in sorted(case_results, key=lambda r: r["id"]):
        for turn in result.get("turns", []):
            reply = turn.get("reply") or ""
            numbers, names = key_tokens(reply)
            if turn.get("grade", {}).get("outcome") == DONE and (numbers or names) and reply not in {p["text"] for p in picks}:
                picks.append({"id": f"reply.{result['id']}", "text": reply})
                break
        if len(picks) >= limit:
            break
    return picks


def grade_speech_output(pick: dict[str, str], transcript: str) -> dict[str, Any]:
    numbers, names = key_tokens(pick["text"])
    heard_numbers = numbers_in(transcript)
    lost = [f"{n:g}" for n in numbers if not any(abs(n - h) < 0.01 for h in heard_numbers)]
    lost += [n for n in names if not has_word(transcript, n)]
    return {"id": pick["id"], "text": pick["text"], "transcript": transcript, "outcome": DONE if not lost else HONEST,
            "reason": "done" if not lost else f"lost {', '.join(lost)}"}


def regrade_voice(voice: dict[str, Any]) -> dict[str, Any]:
    """Grade stored recognizer output again with the current graders."""
    from evals.runner import regrade

    if not voice:
        return voice
    specs = {s["id"]: s for s in clip_specs()}
    clips = [c for c in voice.get("clips", []) if c["id"] in specs]
    cases = {c.id: c for c in load_cases()}
    spoken = []
    for item in voice.get("spoken_tasks", []):
        result = regrade(cases[item["case"]], item["result"])
        spoken.append({**item, "outcome": result["outcome"], "reason": result["reason"], "result": result})
    return {
        **voice,
        "hearing": [grade_hearing(specs[c["id"]], c) for c in clips if specs[c["id"]]["group"] != "turn"],
        "turn_taking": [grade_turns(specs[c["id"]], c, c) for c in clips if specs[c["id"]]["group"] in {"clean", "turn"}],
        "spoken_tasks": spoken,
        "speech_output": [grade_speech_output({"id": s["id"], "text": s["text"]}, s["transcript"]) for s in voice.get("speech_output", [])],
    }


def run_voice(shipped_caps: set[str], *, log: Callable[[str], None], case_results: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    from evals.runner import pinned_config, run_case

    cfg = load_config()
    specs = clip_specs()
    log(f"voice: synthesizing up to {len(specs)} clips (cached in {AUDIO})")
    timing = ensure_clips(cfg, specs)
    log("voice: replaying clips through the recognizer")
    heard = recognize(cfg, [{"id": s["id"], "path": s["file"]} for s in specs])
    by_id = {c["id"]: c for c in heard["clips"]}

    hearing = [grade_hearing(s, by_id[s["id"]]) for s in specs if s["group"] != "turn"]
    turns = [grade_turns(s, by_id[s["id"]], timing[s["id"]]) for s in specs if s["group"] in {"clean", "turn"}]

    log("voice: running spoken tasks through the product")
    cases = {c.id: c for c in load_cases()}
    cfg_pinned = pinned_config()
    spoken = []
    for spec in specs:
        if spec["group"] != "clean":
            continue
        clip = by_id[spec["id"]]
        committed_by = "end of utterance" if clip["commits"] else "Enter"
        transcript = clip["commits"][0]["text"] if clip["commits"] else clip.get("uncommitted", "")
        result = run_case(cases[spec["case"]], cfg_pinned, shipped_caps, spoken=lambda _say, t=transcript: t)
        spoken.append({"id": f"spoken.{spec['case']}", "case": spec["case"], "heard": transcript, "committed_by": committed_by, "outcome": result["outcome"],
                       "reason": result["reason"], "reply": result["turns"][0]["reply"] if result["turns"] else "", "result": result})

    speech_output: list[dict[str, Any]] = []
    if case_results:
        picks = speech_output_candidates(case_results)
        log(f"voice: speaking {len(picks)} replies and hearing them back")
        with tempfile.TemporaryDirectory(prefix="agavai-eval-speech-") as tmp:
            items = [{"id": p["id"], "segments": [{"text": p["text"], "voice": VOICE}], "out": str(Path(tmp) / f"{i}.wav"), "lead_ms": 300, "tail_ms": 2000}
                     for i, p in enumerate(picks)]
            _, paths = _speech_env(cfg)
            helper(cfg, {"mode": "synth", "model": paths["model"], "voices": paths["voices"], "items": items})
            back = recognize(cfg, [{"id": i["id"], "path": i["out"]} for i in items])
        for pick, clip in zip(picks, back["clips"]):
            speech_output.append(grade_speech_output(pick, heard_text(clip)))

    return {
        "clips": [{**{k: s[k] for k in ("id", "group", "text", "snr_db")}, **timing[s["id"]], **{k: by_id[s["id"]][k] for k in ("commits", "uncommitted", "first_interim_t", "step_mean_s", "step_max_s")}} for s in specs],
        "recognizer": {"load_s": heard["load_s"], "peak_rss_mb": heard["peak_rss_mb"]},
        "hearing": hearing,
        "turn_taking": turns,
        "spoken_tasks": spoken,
        "speech_output": speech_output,
    }
