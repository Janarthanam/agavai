#!/usr/bin/env python3
"""Create the task schema used by the dashboard."""

import argparse
import json
import re
from pathlib import Path


TOKEN = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*$")


def parse_values(text: str) -> list[str]:
    return [part.strip() for part in text.split(",") if part.strip()]


def validate_schema(data) -> dict:
    if not isinstance(data, dict) or set(data) != {"priority", "tag"}:
        raise ValueError("tasks/schema.json must contain only priority and tag arrays")
    priority = field_values(data["priority"], "priority")
    tag = field_values(data["tag"], "tag")
    overlap = {item.lower() for item in priority} & {item.lower() for item in tag}
    if overlap:
        names = ", ".join(sorted(overlap))
        raise ValueError(f"priority and tag cannot share values: {names}")
    return {"priority": priority, "tag": tag}


def field_values(values, name: str) -> list[str]:
    if not isinstance(values, list):
        raise ValueError(f"{name} must be an array of tokens")
    seen = set()
    cleaned = []
    for value in values:
        if not isinstance(value, str) or not TOKEN.fullmatch(value):
            raise ValueError(f"{name} values must be tokens such as P0 or mvp")
        key = value.lower()
        if key in seen:
            raise ValueError(f"duplicate {name} value: {value}")
        seen.add(key)
        cleaned.append(value)
    return cleaned


def create_schema(project: Path, priority: list[str], tag: list[str], force: bool = False) -> Path:
    project = project.resolve()
    tasks_dir = project / "tasks"
    if not tasks_dir.is_dir():
        raise FileNotFoundError(f"No tasks/ folder in {project}")
    schema = validate_schema({"priority": priority, "tag": tag})
    path = tasks_dir / "schema.json"
    if path.exists() and not force:
        raise FileExistsError(f"{path} already exists")
    path.write_text(json.dumps(schema, indent=2) + "\n", encoding="utf-8")
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, default=Path.cwd(), help="Project root containing tasks/")
    parser.add_argument("--priority", default="P0,P1,P2", help="Comma-separated priority tokens")
    parser.add_argument("--tag", default="", help="Comma-separated tag tokens")
    parser.add_argument("--force", action="store_true", help="Replace an existing schema")
    args = parser.parse_args()
    try:
        path = create_schema(args.project, parse_values(args.priority), parse_values(args.tag), args.force)
    except (OSError, ValueError) as error:
        raise SystemExit(str(error))
    print(path)


if __name__ == "__main__":
    main()
