"""GTK4 / libadwaita window you can open from the app launcher."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Gtk  # noqa: E402

from oma_voice.config import load_config
from oma_voice.llm import health
from oma_voice.state import read_state

APP_ID = "app.oma.voice"


def _cli() -> list[str]:
    exe = shutil.which("oma-voice")
    if exe:
        return [exe]
    return [sys.executable, "-m", "oma_voice"]


def _load_ui(path: Path) -> dict:
    if not path.is_file():
        return {"phase": "idle", "phase_label": "Idle", "model_id": "", "turns": []}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"phase": "idle", "phase_label": "Idle", "model_id": "", "turns": []}


def _esc(text: str) -> str:
    return GLib.markup_escape_text(str(text or ""), -1)


def _transcript_markup(data: dict) -> str:
    turns = data.get("turns") or []
    if not turns:
        phase = data.get("phase") or "idle"
        if phase == "listening":
            return "<i>Listening. Speak, then press Send.</i>"
        return "<i>Ask with your voice or type below.\nTool calls show up here as they run.</i>"
    parts: list[str] = []
    for turn in turns:
        user = (turn.get("user") or "").strip()
        if user:
            parts.append(f"<b>You</b>  {_esc(user)}")
        for tool in turn.get("tools") or []:
            name = _esc(tool.get("name") or "?")
            status = tool.get("status") or ""
            mark = "…" if status == "running" else "✓"
            args = tool.get("args") or ""
            line = f"<span foreground='#89b4fa'><b>{mark} {name}</b></span>"
            if args:
                line += f"  <tt>{_esc(args)}</tt>"
            parts.append(line)
            result = (tool.get("result") or "").strip()
            if result:
                parts.append(f"<span alpha='70%'>    {_esc(result)}</span>")
        asst = (turn.get("assistant") or "").strip()
        if asst:
            parts.append(f"<b>Agavai</b>  {_esc(asst)}")
    return "\n\n".join(parts)


class VoiceWindow(Adw.ApplicationWindow):
    def __init__(self, app: Adw.Application) -> None:
        super().__init__(application=app, title="Agavai")
        self.set_default_size(440, 640)
        self.cfg = load_config()
        self._busy = False

        header = Adw.HeaderBar()
        self.phase_label = Gtk.Label(label="Idle")
        self.phase_label.add_css_class("heading")
        header.set_title_widget(self.phase_label)

        self.listen_btn = Gtk.Button(label="Listen")
        self.listen_btn.add_css_class("suggested-action")
        self.listen_btn.connect("clicked", self._on_listen)
        header.pack_start(self.listen_btn)

        self.send_btn = Gtk.Button(label="Send")
        self.send_btn.connect("clicked", self._on_send)
        header.pack_end(self.send_btn)

        self.cancel_btn = Gtk.Button(label="Cancel")
        self.cancel_btn.connect("clicked", self._on_cancel)
        header.pack_end(self.cancel_btn)

        self.transcript = Gtk.Label(
            xalign=0,
            wrap=True,
            wrap_mode=Gtk.WrapMode.WORD_CHAR,
            selectable=True,
            use_markup=True,
        )
        self.transcript.set_margin_start(16)
        self.transcript.set_margin_end(16)
        self.transcript.set_margin_top(12)
        self.transcript.set_margin_bottom(12)
        self.transcript.set_hexpand(True)
        self.transcript.set_vexpand(False)

        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_child(self.transcript)
        scroll.set_vexpand(True)

        self.entry = Gtk.Entry()
        self.entry.set_placeholder_text("Type a request and press Ask")
        self.entry.set_hexpand(True)
        self.entry.connect("activate", self._on_ask)

        ask_btn = Gtk.Button(label="Ask")
        ask_btn.connect("clicked", self._on_ask)

        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        row.set_margin_start(12)
        row.set_margin_end(12)
        row.set_margin_bottom(8)
        row.append(self.entry)
        row.append(ask_btn)

        self.status = Gtk.Label(xalign=0)
        self.status.add_css_class("dim-label")
        self.status.set_margin_start(16)
        self.status.set_margin_end(16)
        self.status.set_margin_bottom(12)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        toolbar = Adw.ToolbarView()
        toolbar.add_top_bar(header)
        toolbar.set_content(scroll)
        box.append(toolbar)
        box.append(row)
        box.append(self.status)
        self.set_content(box)

        self._watch_ui()
        GLib.timeout_add_seconds(1, self._tick)
        self._refresh()

    def _ui_path(self) -> Path:
        return self.cfg.runtime_dir / "ui.json"

    def _watch_ui(self) -> None:
        self.cfg.runtime_dir.mkdir(parents=True, exist_ok=True)
        path = self._ui_path()
        if not path.exists():
            path.write_text("{}", encoding="utf-8")
        gfile = Gio.File.new_for_path(str(path))
        self._monitor = gfile.monitor_file(Gio.FileMonitorFlags.NONE, None)
        self._monitor.connect("changed", lambda *a: GLib.idle_add(self._refresh))

    def _tick(self) -> bool:
        self._refresh()
        return True

    def _refresh(self) -> None:
        data = _load_ui(self._ui_path())
        phase = read_state(self.cfg)
        label = data.get("phase_label") or phase
        self.phase_label.set_text(str(label))
        self.transcript.set_markup(_transcript_markup(data))
        model = data.get("model_id") or self.cfg.llm.model_id
        llm = "up" if health(self.cfg.llm) else "down"
        self.status.set_text(f"{model}  ·  llama-server {llm}  ·  {phase}")
        listening = phase == "listening"
        idle = phase == "idle"
        self.listen_btn.set_sensitive(idle and not self._busy)
        self.send_btn.set_sensitive(listening and not self._busy)
        self.cancel_btn.set_sensitive(not idle and not self._busy)
        self.entry.set_sensitive(idle and not self._busy)

    def _run_cli(self, args: list[str]) -> None:
        def work() -> None:
            try:
                subprocess.run(_cli() + args, check=False)
            finally:
                GLib.idle_add(self._done)

        self._busy = True
        self._refresh()
        threading.Thread(target=work, daemon=True).start()

    def _done(self) -> None:
        self._busy = False
        self._refresh()

    def _on_listen(self, *_a) -> None:
        self._run_cli(["start"])

    def _on_send(self, *_a) -> None:
        self._run_cli(["stop"])

    def _on_cancel(self, *_a) -> None:
        self._run_cli(["cancel"])

    def _on_ask(self, *_a) -> None:
        text = (self.entry.get_text() or "").strip()
        if not text:
            return
        self.entry.set_text("")
        self._run_cli(["ask", text])


def run() -> int:
    os.environ.setdefault("GDK_BACKEND", "wayland")
    Adw.init()
    app = Adw.Application(application_id=APP_ID)

    def on_activate(application: Adw.Application) -> None:
        win = application.get_active_window()
        if win is None:
            win = VoiceWindow(application)
        win.present()

    app.connect("activate", on_activate)
    return app.run(None)
