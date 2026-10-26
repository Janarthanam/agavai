"""Durable session inspection and explicit native session selection."""
from __future__ import annotations

import json
from pathlib import Path
import time

from agavai.harness import Harness
from agavai.harness.session import _cancel_path, _signal_listener, read_listener, start_session
from agavai.harness.storage import SessionRepository, encoded
from agavai.ui import cancel_ui, summon_overlay


def stop_listener(cfg, *, matching: str | None = None):
    if read_listener(cfg) is None:
        return
    if matching:
        snapshot = json.loads((cfg.runtime_dir / "ui.json").read_text())
        if snapshot.get("session_id") != matching:
            raise ValueError("A different voice session is active. Dismiss it before changing this session.")
    cancel_ui(cfg)
    _cancel_path(cfg).touch()
    _signal_listener(cfg)
    deadline = time.monotonic() + 5
    while read_listener(cfg) is not None:
        if time.monotonic() >= deadline:
            raise ValueError("The voice session is still stopping. Wait for its action/audio to finish and retry.")
        time.sleep(0.05)


def allow_resume(cfg, session_id):
    marker = cfg.runtime_dir / "dismissed-session"
    if marker.is_file() and marker.read_text() == session_id:
        marker.unlink()


def run(cfg, args):
    if not cfg.sessions.enabled:
        raise ValueError("Session persistence is disabled in [sessions].")
    repository = SessionRepository(cfg.sessions.dir)
    action = args.session_cmd
    if action == "list":
        print(encoded(repository.list()))
    elif action == "show":
        print(encoded(repository.inspect(args.id)))
    elif action == "export":
        repository.export(args.id, Path(args.destination).expanduser())
        print(args.destination)
    elif action in {"delete", "prune"}:
        if not args.yes:
            raise ValueError("Deletion requires --yes. Inspect/export the session first.")
        if action == "delete":
            repository.delete(args.id)
        else:
            days = args.older_than_days if args.older_than_days is not None else cfg.sessions.retention_days
            print(encoded(repository.prune(days)))
    elif action == "close":
        stop_listener(cfg, matching=args.id)
        with_session = Harness(cfg, session_id=args.id)
        with_session.close()
    elif action in {"new", "resume"}:
        sid = args.id if action == "resume" else None
        if sid:
            repository.get(sid)
            if repository.active(sid):
                snapshot = cfg.runtime_dir / "ui.json"
                local = read_listener(cfg) is not None and snapshot.is_file() and json.loads(snapshot.read_text()).get("session_id") == sid
                if not local:
                    raise ValueError("This session is active in another process.")
        if action == "resume" or args.listen:
            stop_listener(cfg)
            if sid:
                with repository.claim(sid):
                    pass
                allow_resume(cfg, sid)
            if not summon_overlay():
                raise ValueError("Could not open Agavai; the native shell must be running.")
            if not start_session(cfg, session_id=sid):
                raise ValueError("Another voice session is starting; retry after it is ready.")
        else:
            harness = Harness(cfg)
            print(harness.context.session_id)
            harness.close()
    return 0
