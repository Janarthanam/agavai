"""Transactional session facts and checkpoints; audio remains in separate files."""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3

from agavai import __version__
from agavai.harness.context import ContextStore


def timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def encoded(value) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def configuration(cfg) -> dict:
    roles = {name: asdict(value) if value else None for name, value in {
        "asr": cfg.asr, "vad": cfg.vad, "router": cfg.router,
        "primary": cfg.small_brain or cfg.llm, "fallback": cfg.large_brain,
        "speech": cfg.tts, "sessions": cfg.sessions}.items()}
    return {"version": __version__, "effective": json.loads(encoded(roles)),
            "sha256": hashlib.sha256(encoded(roles).encode()).hexdigest()}


class SessionRepository:
    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.database = root / "sessions.sqlite3"
        fd = os.open(self.database, os.O_CREAT | os.O_WRONLY, 0o600)
        os.close(fd)
        with self.connect() as db:
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version not in {0, 1}:
                raise ValueError(f"Unsupported session schema version {version}; expected 1.")
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY, title TEXT NOT NULL, created TEXT NOT NULL,
                    updated TEXT NOT NULL, status TEXT NOT NULL, config TEXT NOT NULL,
                    checkpoint TEXT NOT NULL, sequence INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS events (
                    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                    sequence INTEGER NOT NULL, timestamp TEXT NOT NULL, kind TEXT NOT NULL,
                    task_id TEXT NOT NULL, request_id TEXT NOT NULL, data TEXT NOT NULL,
                    PRIMARY KEY(session_id, sequence));
                CREATE TABLE IF NOT EXISTS turns (
                    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                    request_id TEXT NOT NULL, task_id TEXT NOT NULL, input TEXT NOT NULL,
                    mode TEXT NOT NULL, status TEXT NOT NULL, started TEXT NOT NULL,
                    finished TEXT, audio TEXT, PRIMARY KEY(session_id, request_id));
                CREATE TABLE IF NOT EXISTS executions (
                    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                    request_id TEXT NOT NULL, call_id TEXT NOT NULL, task_id TEXT NOT NULL,
                    name TEXT NOT NULL, arguments TEXT NOT NULL, status TEXT NOT NULL,
                    result TEXT, PRIMARY KEY(session_id, request_id, call_id));
                CREATE TABLE IF NOT EXISTS sources (
                    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                    path TEXT NOT NULL, revision TEXT NOT NULL, data TEXT NOT NULL,
                    PRIMARY KEY(session_id, path, revision));
                PRAGMA user_version=1;
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.database, timeout=5)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA synchronous=FULL")
        try:
            with db:
                yield db
        finally:
            db.close()

    def folder(self, session_id: str) -> Path:
        if not re.fullmatch(r"[0-9a-f]{32}", session_id):
            raise ValueError("Session ID must be 32 lowercase hexadecimal characters.")
        return self.root / "sessions" / session_id

    def claim(self, session_id: str):
        folder = self.folder(session_id)
        folder.mkdir(mode=0o700, parents=True, exist_ok=True)
        lease = (folder / ".lock").open("a")
        try:
            fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            lease.close()
            raise ValueError("This session is active in another process.") from None
        return lease

    def create(self, context: ContextStore, cfg) -> None:
        now = timestamp()
        with self.connect() as db:
            db.execute("INSERT INTO sessions(id,title,created,updated,status,config,checkpoint) VALUES(?,?,?,?,?,?,?)",
                (context.session_id, "New session", now, now, "open", encoded(configuration(cfg)), encoded(context.checkpoint())))

    def _session(self, db, session_id: str) -> dict:
        row = db.execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone()
        if row is None:
            raise ValueError(f"Session {session_id} does not exist.")
        result = dict(row)
        result["config"] = json.loads(result["config"])
        result["checkpoint"] = json.loads(result["checkpoint"])
        return result

    def get(self, session_id: str) -> dict:
        self.folder(session_id)
        with self.connect() as db:
            return self._session(db, session_id)

    def list(self, limit: int = 30) -> list[dict]:
        with self.connect() as db:
            return [dict(row) for row in db.execute(
                "SELECT id,title,created,updated,status FROM sessions WHERE status != 'deleting' ORDER BY updated DESC LIMIT ?", (limit,))]

    def save(self, context: ContextStore) -> None:
        with self.connect() as db:
            db.execute("UPDATE sessions SET checkpoint=?, updated=? WHERE id=?",
                       (encoded(context.checkpoint()), timestamp(), context.session_id))

    def record(self, event, context: ContextStore, *, mode: str) -> None:
        if event.kind in {"partial", "level"} or (event.kind == "recording" and not event.data["summon"]):
            return
        sid, rid, tid, data = event.session_id, event.request_id, event.task_id, event.data
        with self.connect() as db:
            db.execute("INSERT INTO events VALUES(?,?,?,?,?,?,?)",
                (sid, event.sequence, event.timestamp, event.kind, tid, rid, encoded(data)))
            db.execute("UPDATE sessions SET sequence=?,updated=?,checkpoint=? WHERE id=?",
                       (event.sequence, event.timestamp, encoded(context.checkpoint()), sid))
            if event.kind == "request_committed":
                db.execute("INSERT INTO turns VALUES(?,?,?,?,?,?,?,NULL,NULL)",
                           (sid, rid, tid, data["text"], mode, "pending", event.timestamp))
                db.execute("UPDATE sessions SET title=? WHERE id=? AND title='New session'", (data["text"][:100], sid))
            elif event.kind == "task_started":
                db.execute("UPDATE turns SET task_id=? WHERE session_id=? AND request_id=?", (tid, sid, rid))
            elif event.kind == "task_status":
                db.execute("UPDATE turns SET status=?,finished=? WHERE session_id=? AND request_id=?",
                           (data["status"], event.timestamp, sid, rid))
            elif event.kind == "tool_started":
                db.execute("INSERT INTO executions VALUES(?,?,?,?,?,?,?,NULL)",
                           (sid, rid, data["call_id"], tid, data["name"], data["arguments"], "running"))
            elif event.kind == "tool_completed":
                db.execute("UPDATE executions SET status=?,result=? WHERE session_id=? AND request_id=? AND call_id=?",
                           (data["status"], data["result"], sid, rid, data["call_id"]))
            elif event.kind == "source_changed":
                source = data["source"]
                db.execute("INSERT OR REPLACE INTO sources VALUES(?,?,?,?)",
                           (sid, source["path"], source.get("revision", ""), encoded(source)))
            elif event.kind == "session_closed":
                db.execute("UPDATE sessions SET status='closed' WHERE id=?", (sid,))

    def resume(self, session_id: str) -> tuple[ContextStore, int, bool]:
        saved = self.get(session_id)
        if saved["status"] == "deleting":
            raise ValueError("Session deletion is incomplete; finish deletion before resuming.")
        context = ContextStore.from_checkpoint(saved["checkpoint"])
        recovered = False
        with self.connect() as db:
            turns = db.execute("SELECT * FROM turns WHERE session_id=? AND status='pending'", (session_id,)).fetchall()
            for turn in turns:
                recovered = True
                db.execute("UPDATE executions SET status='unknown',result='Process interrupted; execution outcome unknown. Do not automatically retry.' WHERE session_id=? AND request_id=? AND status='running'",
                           (session_id, turn["request_id"]))
                records = db.execute("SELECT * FROM executions WHERE session_id=? AND request_id=? ORDER BY rowid", (session_id, turn["request_id"])).fetchall()
                if context.remembered_request_id == turn["request_id"]:
                    # The exchange may have been checkpointed just before reply delivery failed.
                    last_user = next((i for i in range(len(context.messages) - 1, -1, -1)
                                      if context.messages[i]["role"] == "user"), len(context.messages))
                    context.messages = context.messages[:last_user]
                context.messages.append({"role": "user", "content": turn["input"]})
                if records:
                    context.messages.append({"role": "assistant", "content": None, "tool_calls": [
                        {"id": r["call_id"], "type": "function", "function": {"name": r["name"], "arguments": r["arguments"]}} for r in records]})
                    context.messages.extend({"role": "tool", "tool_call_id": r["call_id"], "content": r["result"]} for r in records)
                context.messages.append({"role": "assistant", "content": "The previous request was interrupted. Review recorded outcomes before giving a new instruction."})
                db.execute("UPDATE turns SET status='interrupted',finished=? WHERE session_id=? AND request_id=?",
                           (timestamp(), session_id, turn["request_id"]))
            rows = db.execute("SELECT * FROM executions WHERE session_id=? ORDER BY rowid", (session_id,)).fetchall()
            context.execution.records = [{"id": r["call_id"], **{key: r[key] for key in ("request_id", "task_id", "name", "arguments", "status", "result")}} for r in rows]
            for row in db.execute("SELECT request_id,audio FROM turns WHERE session_id=? AND audio IS NOT NULL", (session_id,)).fetchall():
                audio = json.loads(row["audio"])
                if audio["status"] == "writing":
                    audio["status"] = "incomplete"
                    db.execute("UPDATE turns SET audio=? WHERE session_id=? AND request_id=?", (encoded(audio), session_id, row["request_id"]))
            if context.turn_status == "awaiting_confirmation" or recovered:
                context.recovery_required = True
                context.turn_status = "needs_input"
            db.execute("UPDATE sessions SET status='open',checkpoint=?,updated=? WHERE id=?",
                       (encoded(context.checkpoint()), timestamp(), session_id))
        return context, saved["sequence"], recovered

    def set_audio(self, sid: str, rid: str, metadata: dict) -> None:
        with self.connect() as db:
            db.execute("UPDATE turns SET audio=? WHERE session_id=? AND request_id=?", (encoded(metadata), sid, rid))

    def reserve_audio(self, sid: str, rid: str, metadata: dict, max_mb: int) -> bool:
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            attachments = [json.loads(row[0]) for row in db.execute("SELECT audio FROM turns WHERE audio IS NOT NULL")]
            total = sum(audio["bytes"] for audio in attachments if audio["status"] in {"ready", "writing", "incomplete", "failed"})
            if max_mb and total + metadata["bytes"] > max_mb * 1024 * 1024:
                return False
            db.execute("UPDATE turns SET audio=? WHERE session_id=? AND request_id=?", (encoded(metadata), sid, rid))
            return True

    def attachment(self, sid: str, relative: str) -> Path:
        path = (self.root / relative).resolve()
        if not path.is_relative_to(self.folder(sid).resolve()):
            raise ValueError("Audio attachment escapes its session directory.")
        return path

    def inspect(self, session_id: str) -> dict:
        self.folder(session_id)
        with self.connect() as db:
            db.execute("BEGIN")
            result = self._session(db, session_id)
            for table in ("turns", "executions", "sources", "events"):
                result[table] = [dict(row) for row in db.execute(f"SELECT * FROM {table} WHERE session_id=? ORDER BY rowid", (session_id,))]
        for event in result["events"]:
            event["data"] = json.loads(event["data"])
            event["schema_version"] = 1
        active = result["active"] = self.active(session_id)
        for turn in result["turns"]:
            if turn["audio"]:
                audio = turn["audio"] = json.loads(turn["audio"])
                if audio["status"] == "ready" and not self.attachment(session_id, audio["path"]).is_file():
                    audio["status"] = "missing"
                elif audio["status"] == "writing" and not active:
                    audio["status"] = "incomplete"
            if turn["status"] == "pending" and not active:
                turn["status"] = "interrupted"
        if not active:
            for record in result["executions"]:
                if record["status"] == "running":
                    record.update(status="unknown", result="Process interrupted; execution outcome unknown.")
        for row in result["sources"]:
            row["data"] = json.loads(row["data"])
            row["available"] = Path(row["path"]).is_dir()
        return result

    def active(self, session_id: str) -> bool:
        try:
            lease = self.claim(session_id)
        except ValueError:
            return True
        lease.close()
        return False

    def export(self, session_id: str, destination: Path) -> None:
        data = self.inspect(session_id)
        destination.mkdir(mode=0o700, parents=True, exist_ok=False)
        for turn in data["turns"]:
            audio = turn["audio"]
            if audio and audio["status"] == "ready":
                source = self.attachment(session_id, audio["path"])
                target = destination / audio["path"]
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
        (destination / "session.json").write_text(encoded(data) + "\n")

    def delete(self, session_id: str) -> None:
        self.get(session_id)
        with self.claim(session_id):
            with self.connect() as db:
                db.execute("UPDATE sessions SET status='deleting' WHERE id=?", (session_id,))
            folder = self.folder(session_id)
            for item in folder.iterdir():
                if item.name != ".lock":
                    shutil.rmtree(item) if item.is_dir() else item.unlink()
            with self.connect() as db:
                db.execute("DELETE FROM sessions WHERE id=?", (session_id,))
            (folder / ".lock").unlink()
            folder.rmdir()

    def prune(self, days: int) -> list[str]:
        if days <= 0:
            raise ValueError("Pruning requires a positive retention_days or --older-than-days.")
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        with self.connect() as db:
            ids = [row[0] for row in db.execute("SELECT id FROM sessions WHERE updated < ?", (cutoff,))]
        deleted = []
        for sid in ids:
            if self.active(sid):
                continue
            self.delete(sid)
            deleted.append(sid)
        return deleted
