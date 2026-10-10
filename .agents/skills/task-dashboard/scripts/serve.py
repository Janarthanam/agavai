#!/usr/bin/env python3
"""Read Markdown task checklists and serve a live local dashboard."""

import argparse
import hashlib
import json
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from schema import validate_schema


SKILL_DIR = Path(__file__).resolve().parent.parent
CHECKBOX = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+\[([ xX~!])\]\s+(.+?)\s*$")
HEADING = re.compile(r"^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$")
LINK = re.compile(r"\[([^\]]+)\]\([^)]*\)")
STATUS = {" ": "todo", "~": "in_progress", "!": "blocked", "x": "done"}
ARCHIVE_DIR = "archive"
ASSETS = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/app.css": ("app.css", "text/css; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
}


def read_tasks(project: Path) -> dict:
    tasks_dir = project / "tasks"
    if not tasks_dir.is_dir():
        raise FileNotFoundError(f"No tasks/ folder in {project}")

    tasks = []
    files = []
    for path in sorted(tasks_dir.rglob("*.md")):
        relative_parts = path.relative_to(tasks_dir).parts
        if path.name.lower() == "readme.md" or ARCHIVE_DIR in relative_parts or any(part.startswith(".") for part in relative_parts):
            continue
        relative = path.relative_to(project).as_posix()
        heading = path.stem.replace("-", " ")
        file_tasks = []
        in_fence = False
        current_item = None
        continuation_indent = 0
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if re.match(r"^\s*(```|~~~)", line):
                in_fence = not in_fence
                current_item = None
                continue
            if in_fence:
                continue
            match = HEADING.match(line)
            if match:
                heading = match.group(1).strip()
                current_item = None
                continue
            match = CHECKBOX.match(line)
            if not match:
                if (current_item and line.startswith(" " * continuation_indent) and line.strip()
                        and not re.match(r"^\s*(?:[-*+]|\d+[.)])\s+", line)):
                    current_item["title"] += " " + plain_text(line.strip())
                else:
                    current_item = None
                continue
            item = {
                "id": f"{relative}:{line_number}",
                "file": relative,
                "line": line_number,
                "section": heading,
                "status": STATUS[match.group(1).lower()],
                "title": plain_text(match.group(2).strip()),
            }
            tasks.append(item)
            file_tasks.append(item)
            current_item = item
            continuation_indent = len(line) - len(line.lstrip()) + 6
        files.append({
            "path": relative,
            "name": path.stem.replace("-", " "),
            "count": len(file_tasks),
        })

    schema = read_schema(project)
    for item in tasks:
        item["priority"], item["tag"] = task_fields(item["title"], schema)

    counts = {status: sum(item["status"] == status for item in tasks) for status in STATUS.values()}
    payload = {"project": project.name, "tasks": tasks, "files": files, "counts": counts, "schema": schema}
    payload["version"] = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    return payload


def read_schema(project: Path) -> dict:
    path = project / "tasks" / "schema.json"
    if not path.is_file():
        return {"priority": [], "tag": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(f"Invalid tasks/schema.json: {error}") from error
    return validate_schema(data)


def task_fields(title: str, schema: dict) -> tuple[str | None, list[str]]:
    priority = None
    priority_at = None
    for value in schema["priority"]:
        match = re.search(rf"\b{re.escape(value)}\b", title, re.IGNORECASE)
        if match and (priority_at is None or match.start() < priority_at):
            priority = value
            priority_at = match.start()
    tags = [value for value in schema["tag"] if re.search(rf"\b{re.escape(value)}\b", title, re.IGNORECASE)]
    return priority, tags


def plain_text(value: str) -> str:
    return LINK.sub(r"\1", value).replace("`", "").replace("**", "")


def archive_task_file(project: Path, relative: str) -> None:
    if not isinstance(relative, str):
        raise ValueError("Expected a task file path")
    project = project.resolve()
    source = (project / relative).resolve()
    tasks_dir = (project / "tasks").resolve()
    try:
        source_relative = source.relative_to(project).as_posix()
    except ValueError as error:
        raise ValueError("Only a checklist file directly in tasks/ can be archived") from error
    if source_relative != relative or source.parent != tasks_dir or source.name.lower() == "readme.md" or source.suffix.lower() != ".md":
        raise ValueError("Only a checklist file directly in tasks/ can be archived")
    if not source.is_file():
        raise ValueError("Task file does not exist")
    file_tasks = [task for task in read_tasks(project)["tasks"] if task["file"] == relative]
    if not file_tasks or any(task["status"] != "done" for task in file_tasks):
        raise ValueError("Every task in the file must be done before it can be archived")
    archive_dir = tasks_dir / ARCHIVE_DIR
    destination = archive_dir / source.name
    if destination.exists():
        raise ValueError("An archived file with that name already exists")
    archive_dir.mkdir(exist_ok=True)
    source.rename(destination)


def make_handler(project: Path):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            if self.path != "/api/tasks":
                super().log_message(format, *args)

        def do_GET(self):
            route = urlsplit(self.path).path
            if route == "/api/tasks":
                try:
                    body = json.dumps(read_tasks(project)).encode("utf-8")
                except (OSError, UnicodeError, ValueError) as error:
                    self.send_error(500, str(error))
                    return
                content_type = "application/json; charset=utf-8"
            elif route in ASSETS:
                filename, content_type = ASSETS[route]
                body = (SKILL_DIR / "assets" / filename).read_bytes()
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            route = urlsplit(self.path).path
            if route != "/api/archive":
                self.send_error(404)
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                self.send_json(400, {"error": "Invalid request"})
                return
            if length < 0 or length > 4096:
                self.send_json(400, {"error": "Invalid request"})
                return
            try:
                body = json.loads(self.rfile.read(length) or b"{}")
                archive_task_file(project, body["file"] if isinstance(body, dict) else None)
            except (KeyError, TypeError, json.JSONDecodeError, ValueError, OSError) as error:
                message = "Invalid request" if isinstance(error, (KeyError, TypeError, json.JSONDecodeError)) else str(error)
                self.send_json(400, {"error": message})
                return
            try:
                self.send_json(200, read_tasks(project))
            except (OSError, UnicodeError, ValueError) as error:
                self.send_error(500, str(error))

        def send_json(self, status, payload):
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, default=Path.cwd(), help="Project root containing tasks/")
    parser.add_argument("--port", type=int, default=8765, help="Local port (use 0 for an available port)")
    args = parser.parse_args()
    project = args.project.resolve()
    read_tasks(project)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(project))
    print(f"Task dashboard: http://127.0.0.1:{server.server_port}/", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
