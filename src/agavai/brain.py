"""Task-specific brain adapters. Tools are always executed by the session."""
from __future__ import annotations

import atexit
import json
import logging
import os
from pathlib import Path
import time
from typing import Protocol

from agavai.llm import LlmError, parse_tool_calls
from agavai.config import LlmConfig
from agavai.worker import WorkerError, WorkerProcess

log = logging.getLogger(__name__)


def brain_label(tier: LlmConfig) -> str:
    label = f"{tier.model_id} · {tier.backend} · {tier.model_path.name}"
    return label + (f" · {tier.base_url} ({tier.alias})" if tier.backend == "llama-server" else "")


class BrainBackend(Protocol):
    tool_only: bool
    def ready(self) -> bool: ...
    def respond(self, messages: list[dict], tools: list[dict]) -> dict: ...


class LlamaBackend:
    tool_only = False

    def __init__(self, cfg, chat, health):
        self.cfg, self.chat, self.health = cfg, chat, health

    def ready(self):
        return self.health(self.cfg)

    def respond(self, messages, tools):
        return self.chat(self.cfg, messages, tools=tools)


class NeedleBackend:
    tool_only = True

    def __init__(self, cfg):
        self.cfg = cfg
        self.worker = None

    def ready(self):
        for name, path in (("model_path", self.cfg.model_path), ("runtime_library", self.cfg.runtime_library),
                           ("venv Python", self.cfg.venv / "bin/python")):
            if path is None or not Path(path).is_file():
                raise LlmError(f"Needle {name} is missing: {path}. Run scripts/setup-cactus.sh and configure the paths.")
        return True

    def respond(self, messages, tools):
        started = time.monotonic()
        try:
            self.ready()
            if self.worker is None:
                env = dict(os.environ, NEEDLE_TELEMETRY="0", NEEDLE3_LIB_PATH=str(self.cfg.runtime_library))
                self.worker = WorkerProcess([str(self.cfg.venv / "bin/python"),
                                             str(Path(__file__).with_name("needle_worker.py")), str(self.cfg.model_path)], env=env)
            self.worker.send(json.dumps({"messages": messages, "tools": tools, "max_tokens": self.cfg.max_tokens}).encode(),
                             timeout=min(2, self.cfg.timeout_secs))
            reply = self.worker.receive(max(0, self.cfg.timeout_secs - (time.monotonic() - started)))
            if not reply or reply.get("kind") != "result":
                raise LlmError("Needle response timed out or violated the worker protocol.")
            message = reply["message"]
            calls = [str((call.get("function") or {}).get("name")) for call in parse_tool_calls(message)]
            log.info("needle model=%s tools=%d calls=%s secs=%.2f", self.cfg.model_id, len(tools),
                     ",".join(calls) or "none", time.monotonic() - started)
            return message
        except (WorkerError, LlmError) as exc:
            self.close()
            raise LlmError(f"Needle inference failed: {exc}") from exc

    def close(self):
        if self.worker is not None:
            self.worker.close()
            self.worker = None


BRAIN_BACKENDS = {"llama-server": LlamaBackend, "needle-cactus": NeedleBackend}
_needles = {}


def create_brain(cfg, *, chat, health):
    try:
        factory = BRAIN_BACKENDS[cfg.backend]
    except KeyError as exc:
        raise LlmError(f"Unknown brain backend: {cfg.backend}") from exc
    if cfg.backend == "needle-cactus":
        key = (str(cfg.venv), str(cfg.runtime_library), str(cfg.model_path), cfg.max_tokens, cfg.timeout_secs)
        if key not in _needles:
            _needles[key] = factory(cfg)
        return _needles[key]
    return factory(cfg, chat=chat, health=health)


def close_brains():
    for backend in _needles.values():
        backend.close()
    _needles.clear()


atexit.register(close_brains)
