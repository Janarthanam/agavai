"""Run cases against the unmodified product: real router, prompt, schemas,
orchestrator, and model. Only the world, the clock, and sampling are fixed.
"""

from __future__ import annotations

import copy
import hashlib
import json
import platform
import socket
import subprocess
import sys
import tempfile
import time
import traceback
import urllib.request
from contextlib import ExitStack
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable
from unittest.mock import patch

import agavai.orchestrator as orchestrator
import agavai.router as router
import agavai.tools as tools
from agavai.config import Config, load_config
from agavai.llm import chat as real_chat
from agavai.llm import health
from agavai.brain import create_brain
from agavai.ui import ChatUi

from evals.bindings import desktop as desktop_binding
from evals.cases import Case
from evals.graders import DONE, HARMFUL, HONEST, grade_turn, reply_rules
from evals.world import World, changes, load_world, set_path

ROOT = Path(__file__).resolve().parents[1]
CANARY_IDS = ("desktop.volume.up", "judgment.ask.reminder", "values.reminder.clock-time")
SEED = 42


def pinned_config() -> Config:
    """The user's configuration with routing local and sampling pinned."""
    cfg = load_config()
    cfg.router.backend = "keyword"
    cfg.router.fallback = "keyword"
    for model in (cfg.llm, cfg.small_brain, cfg.large_brain):
        if model is not None:
            model.temperature = 0
            model.seed = SEED
            model.cache_prompt = False
    return cfg


def product_config() -> Config:
    """The user's configuration as the product runs it, routing kept local."""
    cfg = load_config()
    cfg.router.backend = "keyword"
    cfg.router.fallback = "keyword"
    return cfg


def initial_state(case: Case) -> dict[str, Any]:
    state = load_world(case.world)
    for path, value in case.set.items():
        set_path(state, path, copy.deepcopy(value))
    return state


class Clock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def advance(self, hours: float) -> None:
        self.now = self.now + timedelta(hours=hours)


def _frozen_datetime(clock: Clock) -> type[datetime]:
    class Frozen(datetime):
        @classmethod
        def now(cls, tz=None):  # noqa: ARG003 - same signature as datetime.now
            return clock.now

    return Frozen


def _loopback(address: Any) -> bool:
    host = address[0] if isinstance(address, tuple) else str(address)
    return host in {"127.0.0.1", "::1", "localhost"} or str(host).startswith("127.")


class NetworkGuard:
    """Blocks and records any connection that would leave the machine."""

    def __init__(self) -> None:
        self.attempts: list[str] = []
        self._real = socket.socket.connect

    def __enter__(self) -> "NetworkGuard":
        guard = self

        def connect(sock, address):
            if sock.family == socket.AF_UNIX or _loopback(address):
                return guard._real(sock, address)
            guard.attempts.append(str(address))
            raise OSError("outbound connection blocked by the eval")

        self._patch = patch.object(socket.socket, "connect", connect)
        self._patch.start()
        return self

    def __exit__(self, *_exc) -> None:
        self._patch.stop()


_real_select_head_ids = orchestrator.select_head_ids


class RecordedBrain:
    def __init__(self, backend, recorder, cfg):
        self.backend, self.recorder, self.cfg = backend, recorder, cfg
        self.tool_only = backend.tool_only

    def ready(self):
        return self.backend.ready()

    def respond(self, messages, tools):
        return self.recorder.record_model(self.cfg, messages, tools,
                                          lambda: self.backend.respond(messages, tools))


class Recorder:
    """Watches the two places the eval can see without knowing a route:
    model exchanges and world operations. Tool calls and router heads are
    kept for the diagnostics only."""

    def __init__(self, world: World) -> None:
        self.world = world
        self.start_turn()

    def start_turn(self) -> None:
        self.model: list[dict[str, Any]] = []
        self.tools: list[dict[str, Any]] = []
        self.heads: list[list[str]] = []
        self.started = time.monotonic()
        self.first_change: float | None = None
        self.ops_at_start = len(self.world.ops)

    def _note_change(self) -> None:
        if self.first_change is None and any(op["op"] == "change" for op in self.world.ops[self.ops_at_start:]):
            self.first_change = time.monotonic() - self.started

    def chat(self, cfg, messages, *, tools):
        return self.record_model(cfg, messages, tools, lambda: real_chat(cfg, messages, tools=tools))

    def brain(self, cfg, *, chat, health):
        backend = create_brain(cfg, chat=real_chat, health=health)
        return RecordedBrain(backend, self, cfg)

    def record_model(self, cfg, messages, tools, invoke):
        kind = "context" if messages and messages[0].get("content") == orchestrator.CONTEXT_SYSTEM else "action"
        if messages and messages[0].get("content") == router.NEEDLE_ROUTER_SYSTEM:
            kind = "routing"
        start = time.monotonic()
        entry: dict[str, Any] = {"kind": kind, "backend": cfg.backend, "model": cfg.model_id,
                                 "offered": [t["function"]["name"] for t in tools or []]}
        try:
            message = invoke()
        except Exception as exc:
            entry.update(error=str(exc), seconds=round(time.monotonic() - start, 3))
            self.model.append(entry)
            raise
        calls = [
            {"name": (c.get("function") or {}).get("name"), "arguments": (c.get("function") or {}).get("arguments")}
            for c in message.get("tool_calls") or []
        ]
        entry.update(content=message.get("content"), tool_calls=calls, unsupported=message.get("unsupported"), seconds=round(time.monotonic() - start, 3))
        self.model.append(entry)
        return message

    def call_tool(self, name, arguments, cfg):
        result = tools.call_tool(name, arguments, cfg)
        self.tools.append({"name": name, "arguments": arguments if isinstance(arguments, str) else json.dumps(arguments), "result": str(result)[:600]})
        self._note_change()
        return result

    def select_head_ids(self, utterance, cfg):
        heads = _real_select_head_ids(utterance, cfg)
        self.heads.append(list(heads))
        return heads



def _shown(ui: ChatUi) -> list[str]:
    display = ui.data.get("display") or {}
    shown = [str(display.get("title") or "")]
    for item in display.get("items") or []:
        shown.extend(str(item.get(k) or "") for k in ("title", "path", "subtitle"))
    return [s for s in shown if s]


def _case_record(case: Case, shipped: bool) -> dict[str, Any]:
    return {
        "id": case.id,
        "section": case.section,
        "area": case.area,
        "needs": case.needs,
        "shipped": shipped,
        "cluster": case.cluster,
        "note": case.note,
        "says": [t["say"] for t in case.turns],
    }


def run_case(case: Case, base_cfg: Config, shipped_caps: set[str], *, spoken: Callable[[str], str] | None = None) -> dict[str, Any]:
    record = _case_record(case, case.shipped(shipped_caps))
    if case.exclude:
        return {**record, "outcome": "excluded", "reason": case.exclude, "turns": []}
    if not case.run:
        return {**record, "outcome": HONEST, "reason": "not built: nothing exists that this case could exercise", "turns": []}
    clock = Clock(case.clock)
    world = World(initial_state(case), clock.now)
    started = time.monotonic()
    observed: list[dict[str, Any]] = []
    outcome, reason = DONE, "done"
    with ExitStack() as stack:
        guard = stack.enter_context(NetworkGuard())
        desktop = stack.enter_context(desktop_binding.attached(world))
        runtime = Path(stack.enter_context(tempfile.TemporaryDirectory(prefix="agavai-eval-run-")))
        cfg = copy.deepcopy(base_cfg)
        cfg.runtime_dir = runtime
        cfg.files.roots = desktop.roots
        recorder = Recorder(world)
        stack.enter_context(patch("agavai.ui.summon_overlay", return_value=True))
        stack.enter_context(patch.object(orchestrator, "datetime", _frozen_datetime(clock)))
        stack.enter_context(patch.dict(tools.DISPATCH, {"clock_now": lambda _a, _c: clock.now.strftime("%A, %Y-%m-%d %H:%M")}))
        stack.enter_context(patch.object(orchestrator, "chat", recorder.chat))
        stack.enter_context(patch.object(orchestrator, "create_brain", recorder.brain))
        stack.enter_context(patch.object(router, "create_brain", recorder.brain))
        stack.enter_context(patch.object(orchestrator, "call_tool", recorder.call_tool))
        stack.enter_context(patch.object(orchestrator, "select_head_ids", recorder.select_head_ids))
        ui = ChatUi(cfg)
        ui.begin_session()
        in_session = 0
        for index, turn in enumerate(case.turns):
            if turn.get("new_session"):
                clock.advance(float(turn.get("advance_hours", 12)))
                world.now = clock.now
                ui = ChatUi(cfg)
                ui.begin_session()
                in_session = 0
            say = turn["say"]
            heard = spoken(say) if spoken and index == 0 else None
            before = world.snapshot()
            recorder.start_turn()
            outbound_before = len(guard.attempts)
            unknown_before = len(desktop.unknown)
            t0 = time.monotonic()
            error = ""
            try:
                reply = orchestrator.run_turn(heard if heard is not None else say, cfg, ui, continue_conversation=in_session > 0)
            except Exception:  # noqa: BLE001 - a harness or product crash must be visible, not scored as a miss
                reply = ""
                error = traceback.format_exc(limit=6)
            seconds = time.monotonic() - t0
            after = world.snapshot()
            changed = changes(before, after)
            shown = _shown(ui)
            unknown = desktop.unknown[unknown_before:]
            context = next((m.get("content") for m in recorder.model if m["kind"] == "context"), None)
            obs: dict[str, Any] = {
                "say": say,
                "heard": heard,
                "reply": reply,
                "seconds": round(seconds, 3),
                "first_change_s": round(recorder.first_change, 3) if recorder.first_change is not None else None,
                "model": recorder.model,
                "tools": recorder.tools,
                "heads": recorder.heads,
                "context": " ".join(str(context).split()) if context is not None else None,
                "changes": [{"path": c.path, "before": c.before, "after": c.after, "severity": c.severity} for c in changed],
                "shown": shown,
                "outbound": guard.attempts[outbound_before:],
                "rules": reply_rules(reply),
            }
            if error or unknown:
                obs["grade"] = {"outcome": "invalid", "reason": error.strip().splitlines()[-1] if error else f"unknown command {unknown[0]}", "failed": []}
                obs["error"] = error or f"unknown command {unknown[0]}"
                observed.append(obs)
                outcome, reason = "invalid", obs["grade"]["reason"]
                break
            grade = grade_turn(turn, before, after, changed, reply, shown)
            if obs["outbound"]:
                grade.outcome, grade.reason = HARMFUL, f"tried to reach {obs['outbound'][0]}"
            obs["grade"] = {"outcome": grade.outcome, "reason": grade.reason, "failed": grade.failed}
            observed.append(obs)
            if grade.outcome == HARMFUL:
                outcome, reason = HARMFUL, grade.reason
            elif grade.outcome == HONEST and outcome == DONE:
                outcome, reason = HONEST, grade.reason
            in_session += 1
    return {**record, "outcome": outcome, "reason": reason, "seconds": round(time.monotonic() - started, 2), "turns": observed}


def regrade(case: Case, result: dict[str, Any]) -> dict[str, Any]:
    """Grade stored observations again, so a grader fix needs no new model run."""
    if result["outcome"] in {"excluded", "invalid"} or not result.get("turns"):
        return result
    state = initial_state(case)
    outcome, reason = DONE, "done"
    for turn, obs in zip(case.turns, result["turns"]):
        before = copy.deepcopy(state)
        for change in obs["changes"]:
            set_path(state, change["path"], copy.deepcopy(change["after"]))
        changed = changes(before, state)
        grade = grade_turn(turn, before, state, changed, obs["reply"], obs["shown"])
        if obs["outbound"]:
            grade.outcome, grade.reason = HARMFUL, f"tried to reach {obs['outbound'][0]}"
        obs["grade"] = {"outcome": grade.outcome, "reason": grade.reason, "failed": grade.failed}
        obs["rules"] = reply_rules(obs["reply"])
        if grade.outcome == HARMFUL:
            outcome, reason = HARMFUL, grade.reason
        elif grade.outcome == HONEST and outcome == DONE:
            outcome, reason = HONEST, grade.reason
    return {**result, "outcome": outcome, "reason": reason}


def canary(cases: list[Case], cfg: Config, shipped_caps: set[str]) -> list[str]:
    """Run a few cases twice. Any difference means sampling is not pinned."""
    by_id = {c.id: c for c in cases}
    problems = []
    for case_id in CANARY_IDS:
        case = by_id[case_id]
        runs = [run_case(case, cfg, shipped_caps) for _ in range(2)]
        keys = [[(t["reply"], [m.get("tool_calls") for m in t["model"]]) for t in r["turns"]] for r in runs]
        if keys[0] != keys[1]:
            problems.append(f"{case_id}: {keys[0]} != {keys[1]}")
    return problems


def _git(*args: str) -> str:
    proc = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=False)
    return proc.stdout.strip()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _server_props(cfg: Config) -> dict[str, Any]:
    try:
        with urllib.request.urlopen(f"{cfg.llm.base_url}/props", timeout=3) as resp:
            return json.loads(resp.read())
    except (OSError, ValueError):
        return {}


def fingerprint(cfg: Config, bindings: dict[str, Any]) -> dict[str, Any]:
    small = cfg.small_brain or cfg.llm
    from dataclasses import replace
    props = _server_props(replace(cfg, llm=small)) if small.backend == "llama-server" else {}
    model_path = Path(props.get("model_path") or small.model_path).expanduser()
    cpu = next((line.split(":", 1)[1].strip() for line in Path("/proc/cpuinfo").read_text().splitlines() if line.startswith("model name")), platform.processor())
    return {
        "git_commit": _git("rev-parse", "HEAD"),
        # A run writes into evals/results while it runs; that is not a change to what is measured.
        "git_dirty": bool(_git("status", "--porcelain", "--", "src", "evals", ":(exclude)evals/results")),
        "model_path": str(model_path),
        "model_sha256": _sha256(model_path) if model_path.is_file() else "",
        "llama_server_build": props.get("build_info", ""),
        "router": f"{cfg.router.backend} (fallback {cfg.router.fallback})",
        "bindings": bindings,
        "max_tool_rounds": small.max_tool_rounds,
        "max_tools": cfg.router.max_tools,
        "max_tokens": small.max_tokens,
        "sampling": {"temperature": small.temperature, "seed": small.seed, "cache_prompt": small.cache_prompt},
        "cpu": cpu,
        "python": sys.version.split()[0],
        "speech_engine": {
            "backend": cfg.asr.backend, "endpoint": cfg.asr.endpoint, "mode": cfg.asr.mode,
            "chunk_ms": cfg.asr.chunk_ms, "device": cfg.asr.device,
            "vad": {key: getattr(cfg.vad, key) for key in ("backend", "rate", "frame_ms", "silence_ms", "min_speech_ms",
                     "open_threshold_dbfs", "close_threshold_dbfs", "noise_margin_db", "start_timeout_ms", "max_record_ms")}
                     if cfg.asr.endpoint == "vad" else None,
            "model_sha256": {p.name: _sha256(p) for p in ([cfg.asr.model_path] if cfg.asr.backend == "whistle-cactus" else
                                [cfg.asr.model_dir / name for name in ("encoder.onnx", "decoder_joint.onnx", "vocab.txt")]) if p.is_file()},
            "runtime_sha256": _sha256(cfg.asr.runtime_library) if cfg.asr.runtime_library and cfg.asr.runtime_library.is_file() else "",
        },
        "brain_engines": {role: {
            "backend": model.backend, "model_path": str(model.model_path), "tool_selection": model.tool_selection,
            "model_sha256": _sha256(model.model_path) if model.model_path.is_file() else "",
            "endpoint": model.base_url if model.backend == "llama-server" else "worker",
            "runtime_sha256": _sha256(model.runtime_library) if model.runtime_library and model.runtime_library.is_file() else "",
            "temperature": model.temperature, "seed": model.seed, "max_tokens": model.max_tokens,
            "timeout_secs": model.timeout_secs,
        } for role, model in (("small", cfg.small_brain or cfg.llm), ("large", cfg.large_brain),
                              ("router", cfg.router.needle if cfg.router.backend == "needle-cactus" else None)) if model is not None},
    }


def server_ready(cfg: Config) -> bool:
    return create_brain(cfg.small_brain or cfg.llm, chat=real_chat, health=health).ready()
