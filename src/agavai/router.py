"""Select tool heads. Jev via OpenRouter by default; keyword fallback; local stub."""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from typing import Protocol

from agavai.config import Config
from agavai.heads import HEADS, JEV_HEAD_CRITERIA


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
    return JevRouter(cfg)


def select_head_ids(utterance: str, cfg: Config) -> list[str]:
    router = make_router(cfg)
    try:
        heads = router.select(utterance)
    except Exception:
        if cfg.router.fallback == "none":
            return []
        heads = KeywordRouter().select(utterance)
    out = []
    for hid in heads:
        if hid in {"chat", ""}:
            continue
        if hid not in out:
            out.append(hid)
    # Jev may call a screensaver or wallpaper request chit-chat. The words still
    # name a head, and without its tools the model can only talk.
    if not out and cfg.router.fallback != "none":
        for hid in KeywordRouter().select(utterance):
            if hid not in out:
                out.append(hid)
    return out[:2]
