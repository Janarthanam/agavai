"""Allowlisted desktop tools. No generic shell."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

from agavai.config import Config

ToolFn = Callable[[dict[str, Any], Config], str]

LAUNCH_TARGETS = {
    "browser": ["omarchy-launch-browser"],
    "terminal": ["omarchy-launch-terminal"],
    "files": ["omarchy-launch-nautilus"],
    "editor": ["omarchy-launch-editor"],
    "about": ["omarchy-launch-about"],
    "spotify": ["omarchy-launch-spotify"],
    "signal": ["omarchy-launch-signal"],
    "discord": ["omarchy-launch-discord-community"],
    "clipboard": ["omarchy", "menu", "clipboard"],
    "emoji": ["omarchy", "menu", "emoji"],
}

DESKTOP_DIRS = (
    Path.home() / ".local/share/applications",
    Path("/usr/share/applications"),
    Path("/usr/local/share/applications"),
)

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


_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}


def _wallpaper_roots() -> list[Path]:
    roots: list[Path] = []
    current_theme = Path.home() / ".local/state/omarchy/current/theme/backgrounds"
    roots.append(current_theme)
    theme_name = ""
    name_file = Path.home() / ".local/state/omarchy/current/theme.name"
    if name_file.is_file():
        theme_name = name_file.read_text(encoding="utf-8").strip()
    if theme_name:
        roots.append(Path.home() / ".config/omarchy/backgrounds" / theme_name)
    roots.append(Path.home() / "Pictures")
    roots.append(Path.home() / "Downloads")
    return roots


def _list_wallpaper_files() -> list[Path]:
    found: list[Path] = []
    seen: set[Path] = set()
    for root in _wallpaper_roots():
        if not root.is_dir():
            continue
        try:
            entries = sorted(root.iterdir())
        except OSError:
            continue
        for path in entries:
            if not path.is_file() or path.suffix.lower() not in _IMAGE_EXTS:
                continue
            resolved = path.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            found.append(path)
    return found


def wallpaper_current(_args: dict[str, Any], _cfg: Config) -> str:
    proc = _run(["omarchy", "theme", "bg", "current"])
    link = Path.home() / ".local/state/omarchy/current/background"
    target = ""
    if link.exists():
        try:
            target = str(link.resolve())
        except OSError:
            target = str(link)
    return json.dumps({"name": proc.stdout.strip(), "path": target})


def wallpaper_list(_args: dict[str, Any], _cfg: Config) -> str:
    rows = []
    for path in _list_wallpaper_files()[:40]:
        rows.append({"name": path.stem.replace("-", " ").replace("_", " "), "path": str(path)})
    return json.dumps(rows)


def wallpaper_set(args: dict[str, Any], _cfg: Config) -> str:
    raw = str(args.get("name") or args.get("path") or "").strip()
    if not raw:
        return "need wallpaper name or path"
    if ".." in raw:
        return "invalid wallpaper path"
    files = _list_wallpaper_files()
    needle = raw.lower()
    match = None
    for path in files:
        hay = f"{path.name} {path.stem} {path.stem.replace('-', ' ')}".lower()
        if needle in hay or needle in str(path).lower():
            match = path
            break
    if match is None and Path(raw).expanduser().is_file():
        candidate = Path(raw).expanduser().resolve()
        allowed = [p.resolve() for p in _wallpaper_roots() if p.exists()]
        if any(candidate == r or r in candidate.parents for r in allowed) and candidate.suffix.lower() in _IMAGE_EXTS:
            match = candidate
    if match is None:
        names = [p.stem.replace("-", " ") for p in files[:12]]
        return f"unknown wallpaper {raw!r}. try: {', '.join(names)}"
    proc = _run(["omarchy", "theme", "bg", "set", str(match.resolve())], timeout=20)
    if proc.returncode != 0:
        return (proc.stderr or proc.stdout or "wallpaper set failed")[:500]
    return f"wallpaper set to {match.stem.replace('-', ' ')}"


def wallpaper_next(_args: dict[str, Any], _cfg: Config) -> str:
    proc = _run(["omarchy", "theme", "bg", "next"], timeout=20)
    if proc.returncode != 0:
        return (proc.stderr or proc.stdout or "wallpaper next failed")[:500]
    current = _run(["omarchy", "theme", "bg", "current"])
    return current.stdout.strip() or _ok(proc.stdout) or "next wallpaper"


def wallpaper_picker(_args: dict[str, Any], _cfg: Config) -> str:
    proc = _run(["omarchy", "theme", "bg-switcher"], timeout=20)
    if proc.returncode != 0:
        return (proc.stderr or proc.stdout or "wallpaper picker failed")[:500]
    return "opened wallpaper picker"


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
            "agavai_llm": unit_active("agavai-llm.service"),
            "default_agent_name": default_agent,
            "note": "v1 lists local units only; it does not call remote agents",
            "plugins": plugins.stdout.strip().splitlines()[:40],
            "a2a_cards": cards,
        }
    )


def set_volume(args: dict[str, Any], _cfg: Config) -> str:
    action = str(args.get("action") or "").strip().lower()
    allowed = {"raise", "lower", "mute", "mute-toggle"}
    if action == "mute":
        action = "mute-toggle"
    if action not in allowed:
        return "action must be raise, lower, or mute"
    proc = _run(["omarchy", "audio", "output", "volume", action])
    if proc.returncode != 0:
        return (proc.stderr or proc.stdout or "volume failed")[:500]
    return _ok(proc.stdout) or f"volume {action}"


def set_brightness(args: dict[str, Any], _cfg: Config) -> str:
    action = str(args.get("action") or "show").strip().lower()
    if action in {"show", "status", ""}:
        proc = _run(["omarchy", "brightness", "display"])
        return _ok(proc.stdout) or "brightness"
    if action in {"up", "raise"}:
        spec = "+5%"
    elif action in {"down", "lower"}:
        spec = "5%-"
    elif action == "set":
        pct = int(args.get("percent") or -1)
        if pct < 1 or pct > 100:
            return "percent must be 1-100"
        spec = f"{pct}%"
    else:
        return "action must be show, up, down, or set"
    proc = _run(["omarchy", "brightness", "display", spec])
    if proc.returncode != 0:
        return (proc.stderr or proc.stdout or "brightness failed")[:500]
    return _ok(proc.stdout) or f"brightness {spec}"


def mute_microphone(_args: dict[str, Any], _cfg: Config) -> str:
    proc = _run(["omarchy", "audio", "input", "mute"])
    if proc.returncode != 0:
        return (proc.stderr or proc.stdout or "mic mute failed")[:500]
    return _ok(proc.stdout) or "toggled microphone mute"


def battery_status(_args: dict[str, Any], _cfg: Config) -> str:
    proc = _run(["omarchy", "battery", "status"])
    if proc.returncode != 0:
        return (proc.stderr or proc.stdout or "no battery")[:500]
    return _ok(proc.stdout) or "battery unknown"


def network_status(_args: dict[str, Any], _cfg: Config) -> str:
    proc = _run(["omarchy", "network", "status"])
    if proc.returncode != 0:
        return (proc.stderr or proc.stdout or "network status failed")[:500]
    return _ok(proc.stdout) or "network unknown"


def bluetooth(args: dict[str, Any], _cfg: Config) -> str:
    action = str(args.get("action") or "status").strip().lower()
    if action == "status":
        action = "is-on"
    if action not in {"on", "off", "toggle", "is-on"}:
        return "action must be on, off, toggle, or status"
    proc = _run(["omarchy", "bluetooth", "power", action])
    if proc.returncode != 0:
        return (proc.stderr or proc.stdout or "bluetooth failed")[:500]
    return _ok(proc.stdout) or f"bluetooth {action}"


def lock_screen(_args: dict[str, Any], _cfg: Config) -> str:
    lock = shutil.which("omarchy-system-lock")
    if not lock:
        return "omarchy-system-lock not on PATH"
    proc = _run([lock], timeout=10)
    if proc.returncode != 0:
        return (proc.stderr or proc.stdout or "lock failed")[:500]
    return "locked"


def stay_awake(args: dict[str, Any], _cfg: Config) -> str:
    action = str(args.get("action") or "status").strip().lower().replace("_", "-")
    if action in {"on", "stay-awake", "enable"}:
        flag = "stay-awake"
    elif action in {"off", "allow-idle", "disable"}:
        flag = "allow-idle"
    elif action in {"status", "toggle"}:
        flag = action
    else:
        return "action must be on, off, toggle, or status"
    proc = _run(["omarchy", "toggle", "idle", flag])
    if proc.returncode != 0:
        return (proc.stderr or proc.stdout or "idle toggle failed")[:500]
    return _ok(proc.stdout) or f"idle {flag}"


def dnd(args: dict[str, Any], _cfg: Config) -> str:
    action = str(args.get("action") or "toggle").strip().lower()
    argv = ["omarchy", "toggle", "notification", "silencing"]
    if action in {"on", "off", "toggle"}:
        argv.append(action)
    elif action != "toggle":
        return "action must be on, off, or toggle"
    proc = _run(argv)
    if proc.returncode != 0:
        return (proc.stderr or proc.stdout or "dnd failed")[:500]
    return _ok(proc.stdout) or "do-not-disturb toggled"


def screenshot(args: dict[str, Any], _cfg: Config) -> str:
    mode = str(args.get("mode") or "fullscreen").strip().lower()
    dest = str(args.get("dest") or "copy").strip().lower()
    if mode not in {"fullscreen", "windows"}:
        return "mode must be fullscreen or windows (region needs the pointer)"
    if dest not in {"copy", "save"}:
        return "dest must be copy or save"
    proc = _run(["omarchy", "capture", "screenshot", mode, dest], timeout=20)
    if proc.returncode != 0:
        return (proc.stderr or proc.stdout or "screenshot failed")[:500]
    return _ok(proc.stdout) or f"screenshot {mode} {dest}"


def list_reminders(_args: dict[str, Any], _cfg: Config) -> str:
    proc = _run(["omarchy", "reminder", "show", "--json"])
    if proc.returncode != 0:
        return (proc.stderr or proc.stdout or "reminder show failed")[:500]
    return _ok(proc.stdout) or "[]"


def clear_reminders(_args: dict[str, Any], _cfg: Config) -> str:
    proc = _run(["omarchy", "reminder", "clear"])
    if proc.returncode != 0:
        return (proc.stderr or proc.stdout or "reminder clear failed")[:500]
    return _ok(proc.stdout) or "reminders cleared"


def send_notification(args: dict[str, Any], _cfg: Config) -> str:
    headline = str(args.get("headline") or args.get("title") or "").strip()
    body = str(args.get("body") or args.get("message") or "").strip()
    if not headline:
        return "need a headline"
    argv = ["omarchy", "notification", "send", headline]
    if body:
        argv.append(body)
    proc = _run(argv)
    if proc.returncode != 0:
        return (proc.stderr or proc.stdout or "notify failed")[:500]
    return "notified"


def clock_now(_args: dict[str, Any], _cfg: Config) -> str:
    from datetime import datetime

    return datetime.now().strftime("%A, %Y-%m-%d %H:%M")


def close_window(args: dict[str, Any], _cfg: Config) -> str:
    title = str(args.get("title") or "").strip()
    if not title:
        proc = _run(["hyprctl", "dispatch", "killactive"])
        if proc.returncode != 0:
            return proc.stderr.strip() or "close failed"
        return "closed focused window"
    proc = _run(["hyprctl", "clients", "-j"])
    clients = json.loads(proc.stdout or "[]")
    match = next(
        (c for c in clients if title.lower() in str(c.get("title") or "").lower()),
        None,
    )
    if not match:
        return "no matching window"
    _run(["hyprctl", "dispatch", "closewindow", f"address:{match.get('address')}"])
    return f"closed {match.get('title')}"


def toggle_fullscreen(_args: dict[str, Any], _cfg: Config) -> str:
    proc = _run(["hyprctl", "dispatch", "fullscreen"])
    if proc.returncode != 0:
        return proc.stderr.strip() or "fullscreen failed"
    return "toggled fullscreen"


def workspace_step(args: dict[str, Any], _cfg: Config) -> str:
    direction = str(args.get("direction") or "").strip().lower()
    if direction in {"next", "right"}:
        token = "e+1"
    elif direction in {"prev", "previous", "left"}:
        token = "e-1"
    else:
        return "direction must be next or prev"
    proc = _run(["hyprctl", "dispatch", "workspace", token])
    if proc.returncode != 0:
        return proc.stderr.strip() or "workspace step failed"
    return f"workspace {direction}"


def open_app(args: dict[str, Any], _cfg: Config) -> str:
    name = str(args.get("name") or "").strip()
    if not name or "/" in name or ".." in name:
        return "need a simple app name"
    needle = name.lower()
    matches: list[tuple[str, str]] = []
    for folder in DESKTOP_DIRS:
        if not folder.is_dir():
            continue
        for path in folder.glob("*.desktop"):
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if "NoDisplay=true" in text:
                continue
            pretty = ""
            for line in text.splitlines():
                if line.startswith("Name="):
                    pretty = line.split("=", 1)[1].strip()
                    break
            hay = f"{path.stem} {pretty}".lower()
            if needle in hay:
                matches.append((pretty or path.stem, path.stem))
    if not matches:
        return f"no app matching {name!r}"
    exact = next((m for m in matches if m[0].lower() == needle or m[1].lower() == needle), matches[0])
    label, desktop_id = exact
    if not shutil.which("gtk-launch"):
        return "gtk-launch not installed"
    proc = _run(["gtk-launch", desktop_id], timeout=20)
    if proc.returncode != 0:
        return (proc.stderr or proc.stdout or "launch failed")[:500]
    return f"opened {label}"


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
            "description": "Launch a desktop app. target is one of: browser, terminal, files, editor, about, spotify, signal, discord, clipboard, emoji.",
            "parameters": {
                "type": "object",
                "properties": {
                    "target": {
                        "type": "string",
                        "enum": [
                            "browser",
                            "terminal",
                            "files",
                            "editor",
                            "about",
                            "spotify",
                            "signal",
                            "discord",
                            "clipboard",
                            "emoji",
                        ],
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
            "name": "wallpaper_current",
            "description": "Show the current desktop wallpaper name and path.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "wallpaper_list",
            "description": "List wallpaper and screensaver images (theme backgrounds and Pictures) so the user can see them and pick one.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "wallpaper_set",
            "description": "Set the desktop background by image name or filename (e.g. Ship At Sea). Use this when the user picks a wallpaper or screensaver image from the list.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "path": {"type": "string"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "wallpaper_next",
            "description": "Cycle to the next wallpaper for the current theme.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "wallpaper_picker",
            "description": "Open the Omarchy wallpaper switcher UI.",
            "parameters": {"type": "object", "properties": {}},
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
    {
        "type": "function",
        "function": {
            "name": "set_volume",
            "description": "Change speaker volume. action: raise, lower, or mute.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["raise", "lower", "mute"]},
                },
                "required": ["action"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_brightness",
            "description": "Show or change display brightness. action: show, up, down, or set with percent 1-100.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["show", "up", "down", "set"]},
                    "percent": {"type": "integer"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "mute_microphone",
            "description": "Toggle the microphone mute state.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "battery_status",
            "description": "Read battery percentage and power draw.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "network_status",
            "description": "Read Wi-Fi / network status.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "bluetooth",
            "description": "Control Bluetooth power. action: on, off, toggle, or status.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["on", "off", "toggle", "status"]},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "lock_screen",
            "description": "Lock the session and turn off the display.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "stay_awake",
            "description": "Keep the machine awake or allow idle. action: on, off, toggle, or status.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["on", "off", "toggle", "status"]},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "dnd",
            "description": "Do-not-disturb: silence notifications. action: on, off, or toggle.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["on", "off", "toggle"]},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "screenshot",
            "description": "Capture the screen. mode: fullscreen or windows. dest: copy or save.",
            "parameters": {
                "type": "object",
                "properties": {
                    "mode": {"type": "string", "enum": ["fullscreen", "windows"]},
                    "dest": {"type": "string", "enum": ["copy", "save"]},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_reminders",
            "description": "List pending desktop reminders.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "clear_reminders",
            "description": "Clear all pending desktop reminders.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "send_notification",
            "description": "Show a desktop notification.",
            "parameters": {
                "type": "object",
                "properties": {
                    "headline": {"type": "string"},
                    "body": {"type": "string"},
                },
                "required": ["headline"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "clock_now",
            "description": "Current local date and time.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "close_window",
            "description": "Close the focused window, or one whose title contains the given text.",
            "parameters": {
                "type": "object",
                "properties": {"title": {"type": "string"}},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "toggle_fullscreen",
            "description": "Toggle fullscreen on the focused window.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "workspace_step",
            "description": "Move to the next or previous Hyprland workspace. direction: next or prev.",
            "parameters": {
                "type": "object",
                "properties": {
                    "direction": {"type": "string", "enum": ["next", "prev"]},
                },
                "required": ["direction"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "open_app",
            "description": "Open an installed app by name (matches desktop file Name). Example: Firefox, Agavai, Spotify.",
            "parameters": {
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
            },
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
    "wallpaper_current": wallpaper_current,
    "wallpaper_list": wallpaper_list,
    "wallpaper_set": wallpaper_set,
    "wallpaper_next": wallpaper_next,
    "wallpaper_picker": wallpaper_picker,
    "toggle_nightlight": toggle_nightlight,
    "reminder": reminder,
    "search_files": search_files,
    "play_url": play_url,
    "screen_context": screen_context,
    "list_agents": list_agents,
    "set_volume": set_volume,
    "set_brightness": set_brightness,
    "mute_microphone": mute_microphone,
    "battery_status": battery_status,
    "network_status": network_status,
    "bluetooth": bluetooth,
    "lock_screen": lock_screen,
    "stay_awake": stay_awake,
    "dnd": dnd,
    "screenshot": screenshot,
    "list_reminders": list_reminders,
    "clear_reminders": clear_reminders,
    "send_notification": send_notification,
    "clock_now": clock_now,
    "close_window": close_window,
    "toggle_fullscreen": toggle_fullscreen,
    "workspace_step": workspace_step,
    "open_app": open_app,
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
