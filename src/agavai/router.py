"""Select tool heads using Jev, Needle or keywords, without executing calls."""

from __future__ import annotations

import json
import logging
import os
import re
import time
import urllib.error
import urllib.request
from typing import Callable, Protocol

from agavai.config import Config
from agavai.brain import create_brain
from agavai.heads import HEADS, JEV_HEAD_CRITERIA, head_for_tool
from agavai.llm import parse_tool_calls
from agavai.tools import OPENAPI_TOOLS

log = logging.getLogger(__name__)

NEEDLE_ROUTER_SYSTEM = (
    "Select tools relevant to the user's request. Do not invent arguments. "
    "Return no tool call if none matches. These are routing candidates only; "
    "another model will decide the final calls."
)


class ToolRouter(Protocol):
    def select(self, utterance: str) -> list[str]:
        """Return head ids. Empty means no tools."""


class KeywordRouter:
    def select(self, utterance: str) -> list[str]:
        blob = " " + re.sub(r"[^a-z0-9]+", " ", utterance.lower()) + " "
        scored: list[tuple[int, str]] = []
        for head in HEADS:
            hits = 0
            for kw in head.keywords:
                if f" {kw} " in blob or kw.replace(" ", "") in blob.replace(" ", ""):
                    hits += 1
                for tok in kw.split():
                    if len(tok) > 2 and f" {tok} " in blob:
                        hits += 1
            if hits:
                scored.append((hits, head.id))
        scored.sort(reverse=True)
        if not scored:
            return []
        top = scored[0][0]
        return [hid for hits, hid in scored if hits >= top][:2]


class LocalRouter:
    """Placeholder for a future on-device decision model. Same contract as Jev."""

    def select(self, utterance: str) -> list[str]:
        return KeywordRouter().select(utterance)


class NeedleRouter:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg

    def select(self, utterance: str) -> list[str]:
        if self.cfg.router.needle is None:
            raise ValueError("Needle router needs [router.needle] model/runtime configuration")
        brain = create_brain(self.cfg.router.needle, chat=None, health=None)
        message = brain.respond([
            {"role": "system", "content": NEEDLE_ROUTER_SYSTEM},
            {"role": "user", "content": utterance},
        ], list(OPENAPI_TOOLS))
        heads = []
        for call in parse_tool_calls(message):
            head = head_for_tool(call["function"].get("name"))
            if head and head not in heads:
                heads.append(head)
        return heads


class JevRouter:
    """Jev (System One decision model) answers one typed question: which head."""

    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg

    def select(self, utterance: str) -> list[str]:
        key = _api_key(self.cfg)
        if not key:
            raise RuntimeError("no OpenRouter key")
        body = {
            "model": self.cfg.router.jev_model,
            "state": {"utterance": utterance},
            "questions": {
                "head": {
                    "type": "choice",
                    "instructions": "Which Agavai tool head should handle this utterance?",
                    "criteria": dict(JEV_HEAD_CRITERIA),
                },
            },
        }
        data = json.dumps(body).encode()
        req = urllib.request.Request(
            self.cfg.router.jev_base_url,
            data=data,
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=self.cfg.router.timeout_secs) as resp:
            payload = json.loads(resp.read().decode())
        answers = payload.get("answers") or {}
        choice = str((answers.get("head") or {}).get("choice") or "chat")
        if choice in {"chat", ""}:
            return []
        return [choice]


def has_jev_key(cfg: Config) -> bool:
    """Without a key, every Jev selection falls back."""
    return bool(_api_key(cfg))


def _api_key(cfg: Config) -> str:
    env = os.environ.get(cfg.router.api_key_env) or os.environ.get("OPENROUTER_API_KEY") or ""
    if env.strip():
        return env.strip()
    secrets = cfg.config_dir / "secrets.toml"
    if secrets.is_file():
        try:
            import tomllib

            data = tomllib.loads(secrets.read_text())
            return str((data.get("openrouter") or {}).get("api_key") or "").strip()
        except Exception:
            return ""
    return ""


def make_router(cfg: Config) -> ToolRouter:
    backend = (cfg.router.backend or "jev").lower()
    if backend == "keyword":
        return KeywordRouter()
    if backend == "local":
        return LocalRouter()
    if backend == "needle-cactus":
        return NeedleRouter(cfg)
    return JevRouter(cfg)


def routes_itself(tier, cfg: Config) -> bool:
    """A Needle tier that is also the configured router picks its tools in its own call."""
    needle = cfg.router.needle
    return (
        cfg.router.backend == "needle-cactus" and needle is not None and tier.backend == "needle-cactus"
        and (tier.model_path, tier.runtime_library, tier.venv) == (needle.model_path, needle.runtime_library, needle.venv)
    )


def fallback_head_ids(utterance: str, cfg: Config) -> list[str]:
    """Heads used when routing failed or found nothing."""
    if cfg.router.fallback == "none":
        return []
    return KeywordRouter().select(utterance)[:2]


def select_head_ids(utterance: str, cfg: Config, *, report: Callable[[str], None] | None = None) -> list[str]:
    started = time.monotonic()
    if cfg.router.backend == "none":
        return []
    router = make_router(cfg)
    source = cfg.router.backend
    failure = ""
    try:
        heads = router.select(utterance)
    except Exception as exc:
        log.warning("router backend=%s failed (%s: %s); fallback=%s", cfg.router.backend, type(exc).__name__, exc, cfg.router.fallback)
        heads = []
        failure = f" ({type(exc).__name__})"
    out = []
    for hid in heads:
        if hid in {"chat", ""}:
            continue
        if hid not in out:
            out.append(hid)
    # Jev may call a screensaver or wallpaper request chit-chat. The words still
    # name a head, and without its tools the model can only talk.
    if not out:
        out = fallback_head_ids(utterance, cfg)
        source = cfg.router.fallback
    if report:
        report(f"{cfg.router.backend}{failure} → {source} · heads: {', '.join(out[:2]) or 'none'}")
    log.info("router backend=%s source=%s heads=%s secs=%.2f", cfg.router.backend, source, ",".join(out[:2]) or "none", time.monotonic() - started)
    return out[:2]
