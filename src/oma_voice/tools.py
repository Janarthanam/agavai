"""Allowlisted desktop tools. No generic shell."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from typing import Any, Callable
from urllib.parse import urlparse

from oma_voice.config import Config

ToolFn = Callable[[dict[str, Any], Config], str]

LAUNCH_TARGETS = {
    "browser": ["omarchy-launch-browser"],
    "terminal": ["omarchy-launch-terminal"],
    "files": ["omarchy-launch-nautilus"],
    "editor": ["omarchy-launch-editor"],
    "about": ["omarchy-launch-about"],
}

def _run(argv: list[str], timeout: int = 15) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        argv,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _ok(text: str) -> str:
    return text.strip() or "ok"


def list_windows(_args: dict[str, Any], _cfg: Config) -> str:
    proc = _run(["hyprctl", "clients", "-j"])
    if proc.returncode != 0:
        return f"hyprctl failed: {proc.stderr.strip()}"
    try:
        clients = json.loads(proc.stdout or "[]")
    except json.JSONDecodeError:
        return proc.stdout[:2000]
    slim = []
    for c in clients:
        slim.append(
            {
                "class": c.get("class"),
                "title": c.get("title"),
                "workspace": (c.get("workspace") or {}).get("id"),
                "address": c.get("address"),
                "mapped": c.get("mapped"),
            }
        )
    return json.dumps(slim)


def focus_window(args: dict[str, Any], _cfg: Config) -> str:
    title = str(args.get("title") or "").strip()
    klass = str(args.get("class") or "").strip()
    if not title and not klass:
        return "need title or class"
    proc = _run(["hyprctl", "clients", "-j"])
    clients = json.loads(proc.stdout or "[]")
    match = None
    for c in clients:
        if title and title.lower() not in str(c.get("title") or "").lower():
            continue
        if klass and klass.lower() not in str(c.get("class") or "").lower():
            continue
        match = c
        break
    if not match:
        return "no matching window"
    addr = match.get("address")
    _run(["hyprctl", "dispatch", "focuswindow", f"address:{addr}"])
    return f"focused {match.get('title')}"


def to_workspace(args: dict[str, Any], _cfg: Config) -> str:
    n = int(args.get("workspace") or 0)
    if n < 1 or n > 20:
        return "workspace must be 1-20"
    proc = _run(["hyprctl", "dispatch", "workspace", str(n)])
    if proc.returncode != 0:
        return proc.stderr.strip() or "hyprctl failed"
    return f"switched to workspace {n}"


def launch(args: dict[str, Any], _cfg: Config) -> str:
    target = str(args.get("target") or "").lower().strip()
    argv = LAUNCH_TARGETS.get(target)
    if not argv:
        allowed = ", ".join(sorted(LAUNCH_TARGETS))
        return f"unknown target {target!r}; allowed: {allowed}"
    bin_path = shutil.which(argv[0])
    if not bin_path:
        return f"{argv[0]} not on PATH"
    proc = _run(argv, timeout=20)
    if proc.returncode != 0:
        return (proc.stderr or proc.stdout or "launch failed")[:500]
    return f"launched {target}"


def list_themes(_args: dict[str, Any], _cfg: Config) -> str:
    proc = _run(["omarchy", "theme", "list"])
    current = _run(["omarchy", "theme", "current"])
    return json.dumps(
        {
            "current": current.stdout.strip(),
            "available": [ln.strip() for ln in proc.stdout.splitlines() if ln.strip()],
        }
    )


def set_theme(args: dict[str, Any], _cfg: Config) -> str:
    name = str(args.get("name") or "").strip()
    if not name:
        return "need theme name"
    listed = _run(["omarchy", "theme", "list"])
    names = [ln.strip() for ln in listed.stdout.splitlines() if ln.strip()]
    match = next((n for n in names if n.lower() == name.lower()), None)
    if not match:
        return f"unknown theme {name!r}. available: {', '.join(names)}"
    proc = _run(["omarchy", "theme", "set", match], timeout=30)
    if proc.returncode != 0:
        return (proc.stderr or proc.stdout or "theme set failed")[:500]
    return f"theme set to {match}"


def toggle_nightlight(_args: dict[str, Any], _cfg: Config) -> str:
    proc = _run(["omarchy", "toggle", "nightlight"])
    if proc.returncode != 0:
        return (proc.stderr or proc.stdout or "toggle failed")[:500]
    return _ok(proc.stdout) or "toggled night light"


def reminder(args: dict[str, Any], _cfg: Config) -> str:
    minutes = int(args.get("minutes") or 0)
    message = str(args.get("message") or "Reminder").strip() or "Reminder"
    if minutes < 1 or minutes > 24 * 60:
        return "minutes must be 1-1440"
    proc = _run(["omarchy", "reminder", str(minutes), message])
    if proc.returncode != 0:
        return (proc.stderr or proc.stdout or "reminder failed")[:500]
    return f"reminder in {minutes} minutes: {message}"


def search_files(args: dict[str, Any], cfg: Config) -> str:
    query = str(args.get("query") or "").strip()
    if not query or len(query) < 2:
        return "need a query of at least 2 characters"
    if not shutil.which("fd"):
        return "fd not installed"
    hits: list[str] = []
    for root in cfg.files.roots:
        if not root.is_dir():
            continue
        proc = _run(
            [
                "fd",
                "-i",
                "--max-results",
                str(cfg.files.max_results),
                query,
                str(root),
            ],
            timeout=10,
        )
        hits.extend(ln for ln in proc.stdout.splitlines() if ln.strip())
        if len(hits) >= cfg.files.max_results:
            break
    return json.dumps(hits[: cfg.files.max_results])


def play_url(args: dict[str, Any], _cfg: Config) -> str:
    url = str(args.get("url") or "").strip()
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return "url must be http(s)"
    if shutil.which("omarchy-launch-webapp"):
        proc = _run(["omarchy-launch-webapp", url], timeout=20)
    else:
        proc = _run(["omarchy-launch-browser", url], timeout=20)
    if proc.returncode != 0:
        return (proc.stderr or proc.stdout or "open failed")[:500]
    return f"opened {url}"


def screen_context(_args: dict[str, Any], _cfg: Config) -> str:
    win = _run(["hyprctl", "activewindow", "-j"])
    try:
        active = json.loads(win.stdout or "{}")
    except json.JSONDecodeError:
        active = {}
    title = active.get("title")
    klass = active.get("class")
    workspace = (active.get("workspace") or {}).get("id")
    ocr = ""
    at = active.get("at") or [0, 0]
    size = active.get("size") or [0, 0]
    if shutil.which("grim") and shutil.which("tesseract") and size[0] > 0:
        geom = f"{int(at[0])},{int(at[1])} {int(size[0])}x{int(size[1])}"
        grim = subprocess.run(
            ["grim", "-g", geom, "-"],
            check=False,
            capture_output=True,
            timeout=8,
        )
        if grim.returncode == 0 and grim.stdout:
            tess = subprocess.run(
                [
                    "tesseract",
                    "stdin",
                    "stdout",
                    "--oem",
                    "1",
                    "--psm",
                    "6",
                    "-l",
                    "eng",
                ],
                input=grim.stdout,
                check=False,
                capture_output=True,
                timeout=15,
            )
            ocr = (tess.stdout or b"").decode("utf-8", "replace")[:4000]
    return json.dumps(
        {
            "title": title,
            "class": klass,
            "workspace": workspace,
            "ocr": ocr.strip(),
        }
    )


def list_agents(_args: dict[str, Any], cfg: Config) -> str:
    def unit_active(name: str) -> str:
        proc = _run(["systemctl", "--user", "is-active", name])
        return proc.stdout.strip() or "unknown"

    plugins = _run(["omarchy", "plugin", "list"])
    default_agent = ""
    agent_file = os.path.expanduser("~/.config/omarchy/defaults/agent")
    if os.path.isfile(agent_file):
        default_agent = Path_read(agent_file)
    cards = []
    if cfg.a2a_dir.is_dir():
        for p in sorted(cfg.a2a_dir.glob("*.json")):
            try:
                cards.append(json.loads(p.read_text()))
            except json.JSONDecodeError:
                cards.append({"path": str(p), "error": "invalid json"})
    return json.dumps(
        {
            "voxtype": unit_active("voxtype.service"),
            "oma_voice_llm": unit_active("oma-voice-llm.service"),
            "default_agent_name": default_agent,
            "note": "v1 lists local units only; it does not call remote agents",
            "plugins": plugins.stdout.strip().splitlines()[:40],
            "a2a_cards": cards,
        }
    )


def Path_read(path: str) -> str:
    with open(path, encoding="utf-8") as f:
        return f.read().strip()


OPENAPI_TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "list_windows",
            "description": "List open Hyprland windows (class, title, workspace).",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "focus_window",
            "description": "Focus a window by title substring and/or class.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "class": {"type": "string"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "to_workspace",
            "description": "Switch to a Hyprland workspace number.",
            "parameters": {
                "type": "object",
                "properties": {"workspace": {"type": "integer"}},
                "required": ["workspace"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "launch",
            "description": "Launch a desktop app. target is one of: browser, terminal, files, editor, about.",
            "parameters": {
                "type": "object",
                "properties": {
                    "target": {
                        "type": "string",
                        "enum": ["browser", "terminal", "files", "editor", "about"],
                    }
                },
                "required": ["target"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_themes",
            "description": "List Omarchy themes and the current theme.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_theme",
            "description": "Apply an Omarchy theme by name.",
            "parameters": {
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "toggle_nightlight",
            "description": "Toggle night light / blue light filter.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "reminder",
            "description": "Set a desktop reminder in minutes from now.",
            "parameters": {
                "type": "object",
                "properties": {
                    "minutes": {"type": "integer"},
                    "message": {"type": "string"},
                },
                "required": ["minutes"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_files",
            "description": "Search filenames under configured home roots with fd.",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "play_url",
            "description": "Open an http(s) URL in a browser or web app (YouTube, etc.).",
            "parameters": {
                "type": "object",
                "properties": {"url": {"type": "string"}},
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "screen_context",
            "description": "Describe the focused window: title, class, workspace, and OCR of its pixels.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_agents",
            "description": "List local voice/LLM units, Omarchy plugins, and A2A cards. Does not call remote models.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
]

DISPATCH: dict[str, ToolFn] = {
    "list_windows": list_windows,
    "focus_window": focus_window,
    "to_workspace": to_workspace,
    "launch": launch,
    "list_themes": list_themes,
    "set_theme": set_theme,
    "toggle_nightlight": toggle_nightlight,
    "reminder": reminder,
    "search_files": search_files,
    "play_url": play_url,
    "screen_context": screen_context,
    "list_agents": list_agents,
}


def call_tool(name: str, arguments: dict[str, Any] | str | None, cfg: Config) -> str:
    fn = DISPATCH.get(name)
    if not fn:
        return f"unknown tool {name}"
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments) if arguments else {}
        except json.JSONDecodeError:
            return "invalid tool arguments json"
    if arguments is None:
        arguments = {}
    if not isinstance(arguments, dict):
        return "tool arguments must be an object"
    try:
        return fn(arguments, cfg)
    except subprocess.TimeoutExpired:
        return f"{name} timed out"
    except Exception as exc:  # noqa: BLE001 — surface to the model, don't crash the loop
        return f"{name} error: {exc}"
