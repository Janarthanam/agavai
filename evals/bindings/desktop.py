"""SimDesktop: the binding for Agavai's built-in tools.

Tools start every desktop command through `agavai.tools._run`. This binding
stands in for it and for the few other things tools touch directly (the home
directory, `shutil.which`, grim and tesseract), and serves each command from
the World. It is the only eval code that knows those commands.
"""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import subprocess
import tempfile
import types
from datetime import timedelta
from pathlib import Path
from typing import Any, Iterator
from unittest.mock import patch

import agavai.tools
from agavai.config import Config

from evals.world import World, changes, get_path

LAUNCHERS = {
    "omarchy-launch-browser": "browser",
    "omarchy-launch-terminal": "terminal",
    "omarchy-launch-nautilus": "files",
    "omarchy-launch-editor": "editor",
    "omarchy-launch-about": "about",
    "omarchy-launch-spotify": "spotify",
    "omarchy-launch-signal": "signal",
    "omarchy-launch-discord-community": "discord",
}
ALWAYS_PRESENT = {"omarchy", "hyprctl", "fd", "gtk-launch", "omarchy-system-lock", "omarchy-launch-webapp", "grim", "tesseract", "systemctl"}


class UnknownCommand(Exception):
    pass


def _slug(name: str) -> str:
    return name.replace(" ", "-")


def _name(stem: str) -> str:
    return stem.replace("-", " ").replace("_", " ").lower()


class SimDesktop:
    def __init__(self, world: World, home: Path) -> None:
        self.world = world
        self.home = home
        self.commands: list[list[str]] = []
        self.unknown: list[list[str]] = []
        self._materialize()

    # -- fixture home -----------------------------------------------------

    @property
    def wallpaper_dir(self) -> Path:
        return self.home / ".local/state/omarchy/current/theme/backgrounds"

    @property
    def applications_dir(self) -> Path:
        return self.home / ".local/share/applications"

    @property
    def roots(self) -> list[Path]:
        return [self.home / name for name in ("Documents", "Downloads", "Projects", "Work")]

    def _materialize(self) -> None:
        state = self.world.state
        for rel in state["files"]["paths"]:
            path = self.home / rel
            if rel.endswith("/"):
                path.mkdir(parents=True, exist_ok=True)
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(state["files"].get("contents", {}).get(rel, ""), encoding="utf-8")
        self.wallpaper_dir.mkdir(parents=True, exist_ok=True)
        for image in state["wallpaper"]["images"]:
            (self.wallpaper_dir / f"{_slug(image)}.jpg").write_bytes(b"")
        self._write_theme_name()
        self._link_background()
        self.applications_dir.mkdir(parents=True, exist_ok=True)
        for app in state["apps"]:
            (self.applications_dir / f"{app['id']}.desktop").write_text(
                f"[Desktop Entry]\nName={app['name']}\nExec={app['id']}\nType=Application\n", encoding="utf-8"
            )

    def _write_theme_name(self) -> None:
        name_file = self.home / ".local/state/omarchy/current/theme.name"
        name_file.write_text(self.world.state["theme"]["current"], encoding="utf-8")

    def _link_background(self) -> None:
        link = self.home / ".local/state/omarchy/current/background"
        if link.is_symlink() or link.exists():
            link.unlink()
        link.symlink_to(self.wallpaper_dir / f"{_slug(self.world.state['wallpaper']['current'])}.jpg")

    # -- what tools see ----------------------------------------------------

    def which(self, name: str) -> str | None:
        if name in LAUNCHERS:
            return f"/usr/bin/{name}" if self.world.state["launchers"].get(LAUNCHERS[name]) else None
        return f"/usr/bin/{name}" if name in ALWAYS_PRESENT else None

    def subprocess_run(self, argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess:
        """Only screen_context calls subprocess.run itself, for grim and tesseract."""
        self.commands.append(list(argv))
        if argv[0] == "grim":
            return subprocess.CompletedProcess(argv, 0, b"\x89PNG fixture", b"")
        if argv[0] == "tesseract":
            self.world.read("screen", "ocr")
            return subprocess.CompletedProcess(argv, 0, self.world.state["screen"]["ocr"].encode(), b"")
        self.unknown.append(list(argv))
        raise UnknownCommand(argv)

    def run(self, argv: list[str], timeout: int = 15) -> subprocess.CompletedProcess:
        # Tools may start a command by the full path `which` returned.
        argv = [Path(str(argv[0])).name, *(str(a) for a in argv[1:])]
        self.commands.append(argv)
        area = self._area(argv)
        faults = self.world.state.get("faults", {})
        if area in faults.get("timeout", []):
            raise subprocess.TimeoutExpired(argv, timeout)
        if area in faults.get("fail", {}):
            return self._done(argv, faults["fail"][area], code=1)
        try:
            out = self._serve(argv)
        except UnknownCommand:
            self.unknown.append(argv)
            raise
        if isinstance(out, subprocess.CompletedProcess):
            return out
        return self._done(argv, out or "")

    @staticmethod
    def _done(argv: list[str], text: str, code: int = 0) -> subprocess.CompletedProcess:
        if code:
            return subprocess.CompletedProcess(argv, code, "", text)
        return subprocess.CompletedProcess(argv, 0, text, "")

    @staticmethod
    def _area(argv: list[str]) -> str:
        head = argv[0]
        if head == "hyprctl":
            return "windows"
        if head in LAUNCHERS or head in {"gtk-launch", "omarchy-launch-webapp"}:
            return "launched"
        if head == "omarchy-system-lock":
            return "system"
        if head == "fd":
            return "files"
        if head == "omarchy" and len(argv) > 1:
            return {
                "theme": "wallpaper" if len(argv) > 2 and argv[2].startswith("bg") else "theme",
                "toggle": {"nightlight": "display", "idle": "system", "notification": "system"}.get(argv[2] if len(argv) > 2 else "", "system"),
                "reminder": "reminders",
                "audio": "audio",
                "brightness": "display",
                "battery": "battery",
                "network": "network",
                "bluetooth": "bluetooth",
                "capture": "screenshots",
                "notification": "notifications",
                "menu": "pickers",
            }.get(argv[1], argv[1])
        return head

    # -- commands ------------------------------------------------------------

    def _serve(self, argv: list[str]) -> str | subprocess.CompletedProcess:
        head, rest = argv[0], argv[1:]
        if head == "hyprctl":
            return self._hyprctl(rest)
        if head in LAUNCHERS:
            target = LAUNCHERS[head]
            if rest:
                return self._open_url(rest[0])
            self._launch(target)
            return ""
        if head == "omarchy-launch-webapp":
            return self._open_url(rest[0])
        if head == "gtk-launch":
            app = next((a for a in self.world.state["apps"] if a["id"] == rest[0]), None)
            if app is None:
                return self._done(argv, f"gtk-launch: no such application {rest[0]}", code=1)
            self._launch(app["name"].lower())
            return ""
        if head == "omarchy-system-lock":
            self._set("system", "locked", True)
            return ""
        if head == "fd":
            return self._fd(rest)
        if head == "systemctl":
            return "active"
        if head == "omarchy":
            return self._omarchy(rest)
        raise UnknownCommand(argv)

    def _set(self, area: str, key: str, value: Any) -> None:
        self.world.state[area][key] = value
        self.world.change(area, f"{key}={value}")

    def _append(self, area: str, item: Any) -> None:
        self.world.state[area].append(item)
        self.world.change(area, json.dumps(item))

    def _launch(self, target: str) -> None:
        self._append("launched", target)

    def _open_url(self, url: str) -> str:
        self._append("urls", url)
        return ""

    # Windows and workspaces

    def _windows(self) -> list[dict[str, Any]]:
        return self.world.state["windows"]

    def _client(self, window: dict[str, Any]) -> dict[str, Any]:
        return {
            "address": window["address"],
            "class": window["class"],
            "title": window["title"],
            "workspace": {"id": window["workspace"], "name": str(window["workspace"])},
            "mapped": True,
        }

    def _focus_first_on(self, workspace: int) -> None:
        window = next((w for w in self._windows() if w["workspace"] == workspace), None)
        self._set("focus", "window", window["address"] if window else "")

    def _close(self, address: str) -> None:
        window = next(w for w in self._windows() if w["address"] == address)
        self.world.state["windows"] = [w for w in self._windows() if w["address"] != address]
        self.world.change("windows", f"closed {window['title']}")
        if self.world.state["focus"]["window"] == address:
            self._focus_first_on(window["workspace"])

    def _hyprctl(self, rest: list[str]) -> str | subprocess.CompletedProcess:
        if rest == ["clients", "-j"]:
            self.world.read("windows")
            return json.dumps([self._client(w) for w in self._windows()])
        if rest == ["activewindow", "-j"]:
            self.world.read("windows", "active")
            focused = next((w for w in self._windows() if w["address"] == self.world.state["focus"]["window"]), None)
            if focused is None:
                return "{}"
            return json.dumps({**self._client(focused), "at": [0, 0], "size": [1920, 1080]})
        if rest[:1] != ["dispatch"]:
            raise UnknownCommand(["hyprctl", *rest])
        action, args = rest[1], rest[2:]
        if action == "focuswindow":
            address = args[0].removeprefix("address:")
            window = next((w for w in self._windows() if w["address"] == address), None)
            if window is None:
                return self._done(["hyprctl", *rest], "No such window", code=1)
            self._set("focus", "window", address)
            if self.world.state["workspace"]["active"] != window["workspace"]:
                self._set("workspace", "active", window["workspace"])
            return "ok"
        if action == "workspace":
            current = self.world.state["workspace"]["active"]
            token = args[0]
            target = current + 1 if token == "e+1" else max(1, current - 1) if token == "e-1" else int(token)
            self._set("workspace", "active", target)
            self._focus_first_on(target)
            return "ok"
        if action == "killactive":
            focused = self.world.state["focus"]["window"]
            if focused:
                self._close(focused)
            return "ok"
        if action == "closewindow":
            address = args[0].removeprefix("address:")
            if any(w["address"] == address for w in self._windows()):
                self._close(address)
            return "ok"
        if action == "fullscreen":
            focused = self.world.state["focus"]["window"]
            current = self.world.state["fullscreen"]["window"]
            self._set("fullscreen", "window", "" if current == focused else focused)
            return "ok"
        raise UnknownCommand(["hyprctl", *rest])

    # Omarchy

    def _omarchy(self, rest: list[str]) -> str | subprocess.CompletedProcess:
        state = self.world.state
        group = rest[0]
        if group == "theme":
            return self._theme(rest[1:])
        if group == "toggle":
            kind = rest[1]
            if kind == "nightlight":
                self._set("display", "nightlight", not state["display"]["nightlight"])
                return ""
            if kind == "idle":
                flag = rest[2]
                if flag == "status":
                    self.world.read("system", "stay_awake")
                    return "stay awake" if state["system"]["stay_awake"] else "idle allowed"
                value = {"stay-awake": True, "allow-idle": False, "toggle": not state["system"]["stay_awake"]}[flag]
                self._set("system", "stay_awake", value)
                return ""
            if kind == "notification" and rest[2] == "silencing":
                mode = rest[3] if len(rest) > 3 else "toggle"
                value = {"on": True, "off": False, "toggle": not state["system"]["dnd"]}[mode]
                self._set("system", "dnd", value)
                return ""
        if group == "reminder":
            return self._reminder(rest[1:])
        if group == "audio":
            if rest[1:3] == ["output", "volume"]:
                action = rest[3]
                if action == "mute-toggle":
                    self._set("audio", "muted", not state["audio"]["muted"])
                else:
                    step = 5 if action == "raise" else -5
                    self._set("audio", "volume", min(100, max(0, state["audio"]["volume"] + step)))
                return ""
            if rest[1:3] == ["input", "mute"]:
                self._set("audio", "mic_muted", not state["audio"]["mic_muted"])
                return ""
        if group == "brightness" and rest[1] == "display":
            if len(rest) == 2:
                self.world.read("display", "brightness")
                return f"{state['display']['brightness']}%"
            spec = rest[2]
            level = state["display"]["brightness"]
            if spec == "+5%":
                level = min(100, level + 5)
            elif spec == "5%-":
                level = max(1, level - 5)
            else:
                level = int(spec.rstrip("%"))
            self._set("display", "brightness", level)
            return ""
        if group == "battery" and rest[1:] == ["status"]:
            self.world.read("battery")
            battery = state["battery"]
            if not battery["present"]:
                return self._done(["omarchy", *rest], "No battery found", code=1)
            return f"{battery['percent']}% {battery['state']} ({battery['watts']} W)"
        if group == "network" and rest[1:] == ["status"]:
            self.world.read("network")
            net = state["network"]
            return f"{net['kind']}\t{net['ssid']}\t{net['signal']}\t5180.0"
        if group == "bluetooth" and rest[1] == "power":
            if not state["bluetooth"]["adapter"]:
                return self._done(["omarchy", *rest], "No default controller available", code=1)
            action = rest[2]
            if action == "is-on":
                self.world.read("bluetooth")
                return "on" if state["bluetooth"]["power"] else "off"
            value = {"on": True, "off": False, "toggle": not state["bluetooth"]["power"]}[action]
            self._set("bluetooth", "power", value)
            return ""
        if group == "capture" and rest[1] == "screenshot":
            self._append("screenshots", {"mode": rest[2], "dest": rest[3]})
            return ""
        if group == "notification" and rest[1] == "send":
            self._append("notifications", {"headline": rest[2], "body": rest[3] if len(rest) > 3 else ""})
            return ""
        if group == "menu":
            self._append("pickers", rest[1])
            return ""
        if group == "plugin" and rest[1:] == ["list"]:
            return ""
        raise UnknownCommand(["omarchy", *rest])

    def _theme(self, rest: list[str]) -> str | subprocess.CompletedProcess:
        theme = self.world.state["theme"]
        wallpaper = self.world.state["wallpaper"]
        if rest == ["list"]:
            self.world.read("theme")
            return "\n".join(theme["available"])
        if rest == ["current"]:
            self.world.read("theme")
            return theme["current"]
        if rest[:1] == ["set"]:
            if rest[1] not in theme["available"]:
                return self._done(["omarchy", "theme", *rest], f"Theme not found: {rest[1]}", code=1)
            self._set("theme", "current", rest[1])
            self._write_theme_name()
            return ""
        if rest == ["bg", "current"]:
            self.world.read("wallpaper")
            return wallpaper["current"].title()
        if rest[:2] == ["bg", "set"]:
            name = _name(Path(rest[2]).stem)
            if name not in wallpaper["images"] and not Path(rest[2]).is_file():
                return self._done(["omarchy", "theme", *rest], "No such background", code=1)
            self._set("wallpaper", "current", name)
            self._link_background()
            return ""
        if rest == ["bg", "next"]:
            images = wallpaper["images"]
            index = images.index(wallpaper["current"]) if wallpaper["current"] in images else -1
            self._set("wallpaper", "current", images[(index + 1) % len(images)])
            self._link_background()
            return ""
        if rest == ["bg-switcher"]:
            self._append("pickers", "wallpaper")
            return ""
        raise UnknownCommand(["omarchy", "theme", *rest])

    def _reminder(self, rest: list[str]) -> str:
        reminders = self.world.state["reminders"]
        if rest == ["show", "--json"]:
            self.world.read("reminders")
            items = [
                {
                    "minutes": r["minutes"],
                    "message": r["text"],
                    "label": f"{r['minutes']}-min reminder",
                    "atTime": r["due"][11:16],
                }
                for r in reminders
            ]
            return json.dumps({"count": len(items), "active": bool(items), "tooltip": "Set Reminder", "reminders": items})
        if rest == ["clear"]:
            self.world.state["reminders"] = []
            self.world.change("reminders", "cleared")
            return ""
        minutes = int(rest[0])
        due = self.world.now + timedelta(minutes=minutes)
        self._append("reminders", {"minutes": minutes, "due": due.strftime("%Y-%m-%dT%H:%M"), "text": rest[1] if len(rest) > 1 else ""})
        return ""

    def _fd(self, rest: list[str]) -> str:
        root = Path(rest[-1])
        query = rest[-2]
        self.world.read("files", query)
        if self.home not in root.parents and root != self.home:
            return ""
        proc = subprocess.run(["fd", *rest], capture_output=True, text=True, timeout=10, check=False)
        return proc.stdout


@contextlib.contextmanager
def attached(world: World) -> Iterator[SimDesktop]:
    """Point the built-in tools at the World for the length of one case."""
    with tempfile.TemporaryDirectory(prefix="agavai-eval-home-") as tmp:
        home = Path(tmp)
        desktop = SimDesktop(world, home)
        fake_shutil = types.SimpleNamespace(which=desktop.which)
        fake_subprocess = types.SimpleNamespace(
            run=desktop.subprocess_run,
            TimeoutExpired=subprocess.TimeoutExpired,
            CompletedProcess=subprocess.CompletedProcess,
        )
        dirs = (desktop.applications_dir,)
        with patch.object(agavai.tools, "_run", desktop.run), \
                patch.object(agavai.tools, "shutil", fake_shutil), \
                patch.object(agavai.tools, "subprocess", fake_subprocess), \
                patch.object(agavai.tools, "DESKTOP_DIRS", dirs), \
                patch.dict(os.environ, {"HOME": str(home)}):
            yield desktop


SELF_CHECK = (
    ("set_volume", {"action": "raise"}, "audio.volume", 55),
    ("reminder", {"minutes": 10, "message": "tea"}, "reminders", [{"minutes": 10, "due": "2026-10-09T16:55", "text": "tea"}]),
    ("set_theme", {"name": "gruvbox"}, "theme.current", "Gruvbox"),
    ("wallpaper_set", {"name": "ship at sea"}, "wallpaper.current", "ship at sea"),
    ("close_window", {"title": "signal"}, "windows", None),
    ("to_workspace", {"workspace": 3}, "workspace.active", 3),
    ("launch", {"target": "browser"}, "launched", ["browser"]),
    ("dnd", {"action": "on"}, "system.dnd", True),
    ("lock_screen", {}, "system.locked", True),
)


def self_check(make_world) -> list[str]:
    """Send known operations down the product's own tool functions. Empty means the binding is sound."""
    problems: list[str] = []
    for tool, args, path, expected in SELF_CHECK:
        world = make_world()
        before = world.snapshot()
        with attached(world) as desktop:
            cfg = Config()
            cfg.files.roots = desktop.roots
            result = agavai.tools.call_tool(tool, args, cfg)
            if desktop.unknown:
                problems.append(f"{tool}: unknown command {desktop.unknown[0]}")
                continue
        changed = [c.path for c in changes(before, world.state)]
        if path not in changed:
            problems.append(f"{tool}: expected {path} to change, changed {changed}, result {result!r}")
        elif expected is not None and get_path(world.state, path) != expected:
            problems.append(f"{tool}: {path} is {get_path(world.state, path)!r}, expected {expected!r}")
    world = make_world()
    with attached(world) as desktop:
        cfg = Config()
        cfg.files.roots = desktop.roots
        found = agavai.tools.call_tool("search_files", {"query": "budget"}, cfg)
    if "Budget Notes 2026.md" not in found:
        problems.append(f"search_files: budget notes not found: {found[:200]}")
    if shutil.which("fd") is None:
        problems.append("fd is not installed; file search cannot be simulated")
    return problems
