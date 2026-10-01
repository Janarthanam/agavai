"""Normalize full tool output into bounded, typed native result previews."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from agavai.richtext import rich_text

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".avif"}
VIDEO_EXTS = {".mp4", ".webm", ".mkv", ".mov", ".m4v", ".avi"}
TEXT_EXTS = {".md", ".txt", ".rst", ".json", ".toml", ".yaml", ".yml", ".csv", ".log"}
OPEN_EXTS = IMAGE_EXTS | VIDEO_EXTS | TEXT_EXTS | {".pdf", ".docx", ".xlsx", ".pptx", ".odt", ".ods"}
MAX_ITEMS = 40


def file_item(raw: Any, index: int) -> dict[str, Any] | None:
    row = raw if isinstance(raw, dict) else {"path": raw}
    path = Path(str(row.get("path") or ""))
    if not path.is_absolute():
        return None
    suffix = path.suffix.lower()
    kind = "folder" if path.is_dir() else "image" if suffix in IMAGE_EXTS else "video" if suffix in VIDEO_EXTS else "file"
    item = {"id": str(index), "kind": kind, "title": str(row.get("name") or path.name),
            "subtitle": str(path.parent), "path": str(path), "uri": path.as_uri(),
            "openable": kind == "folder" or suffix in OPEN_EXTS, "extension": "DIR" if kind == "folder" else suffix.lstrip(".").upper() or "FILE"}
    item["preview_html"] = text_preview(item)
    return item


def display_for(tool: str, result: str) -> dict[str, Any] | None:
    try:
        data = json.loads(result)
    except (ValueError, TypeError):
        data = None
    if tool in {"search_files", "wallpaper_list", "wallpaper_current", "wallpaper_picker", "screenshot"}:
        rows = data if isinstance(data, list) else []
        if isinstance(data, dict):
            rows = data.get("results") or ([data] if data.get("path") or data.get("file") else [])
            if data.get("file") and not data.get("path"):
                rows = [{"path": data["file"]}]
        if data is None and tool == "search_files":
            rows = [line for line in result.splitlines() if line.startswith("/")]
        if data is None and tool == "screenshot":
            pieces = result.split(" ", 2)
            rows = [{"path": pieces[2]}] if len(pieces) == 3 and pieces[0] == "screenshot" else []
        items = [item for i, row in enumerate(rows[:MAX_ITEMS]) if (item := file_item(row, i))]
        if items or tool == "search_files" and isinstance(data, list):
            title = "Images" if tool == "wallpaper_list" else "Wallpapers" if tool.startswith("wallpaper") else "Screenshot" if tool == "screenshot" else "Files"
            return {"kind": "files", "title": title, "items": items}
    if tool == "list_themes" and isinstance(data, (dict, list)):
        names = data if isinstance(data, list) else data.get("available") or data.get("themes") or []
        return {"kind": "list", "title": "Themes", "items": [
            {"id": str(i), "kind": "text", "title": str(name), "subtitle": "Current theme" if isinstance(data, dict) and name == data.get("current") else "Theme", "openable": False}
            for i, name in enumerate(names[:MAX_ITEMS])]}
    if tool == "list_windows" and isinstance(data, (list, dict)):
        rows = data if isinstance(data, list) else data.get("windows") or []
        return {"kind": "list", "title": "Windows", "items": [
            {"id": str(i), "kind": "text", "title": str(row.get("title") or row.get("class") or "Window") if isinstance(row, dict) else str(row),
             "subtitle": str(row.get("class") or "") if isinstance(row, dict) else "", "openable": False}
            for i, row in enumerate(rows[:MAX_ITEMS])]}
    if tool in {"battery_status", "network_status"} and isinstance(data, dict):
        return {"kind": "cards", "title": tool.replace("_", " ").title(), "items": [
            {"id": str(i), "kind": "text", "title": str(key), "subtitle": str(value), "openable": False}
            for i, (key, value) in enumerate(data.items()) if not isinstance(value, (dict, list))][:MAX_ITEMS]}
    if tool == "list_reminders" and isinstance(data, list):
        return {"kind": "list", "title": "Reminders", "items": [
            {"id": str(i), "kind": "text", "title": str(row.get("text") or row.get("message") or row) if isinstance(row, dict) else str(row), "subtitle": "Reminder", "openable": False}
            for i, row in enumerate(data[:MAX_ITEMS])]}
    if isinstance(data, dict) and data.get("kind") in {"markdown", "html"} and isinstance(data.get("text"), str):
        return {"kind": "answer", "title": str(data.get("title") or "Answer"), "text": data["text"], "html": rich_text(data["text"], data["kind"])}
    return None


_PATH = re.compile(r"(?<![\w@])/(?:[\w.@+-]+/){1,}[\w.@+-]*")
_NAMED = {"folder", "file", "image", "video"}


def spoken_name(item: dict[str, Any]) -> str:
    """What to say for one typed result. Files, folders, images, and videos use their name, never the path."""
    kind = str(item.get("kind") or "text")
    title = " ".join(str(item.get("title") or "").split())
    if kind in _NAMED:
        return title
    detail = " ".join(str(item.get("subtitle") or "").split())
    if detail.startswith("/"):
        detail = ""
    if title and detail:
        return f"{title}, {detail}"
    return title or detail


def model_view(tool: str, result: str) -> str:
    """Tool text for the model: kind and spoken name, without filesystem paths."""
    block = display_for(tool, result)
    items = (block or {}).get("items") or []
    if not items:
        return result
    rows = []
    for item in items:
        kind = str(item.get("kind") or "text")
        row: dict[str, str] = {"kind": kind, "name": spoken_name(item) if kind in _NAMED else str(item.get("title") or "")}
        if kind == "text":
            detail = str(item.get("subtitle") or "")
            if detail and not detail.startswith("/"):
                row["detail"] = detail
        rows.append(row)
    return json.dumps({"type": block.get("title") or block.get("kind"), "count": len(rows), "items": rows}, ensure_ascii=False)


def read_aloud(reply: str, block: dict[str, Any] | None) -> str:
    """Replace paths in a spoken line with the name chosen for that result type."""
    text = str(reply or "")
    pairs: list[tuple[str, str]] = []
    for item in (block or {}).get("items") or []:
        path = str(item.get("path") or "")
        label = spoken_name(item)
        if not path.startswith("/") or not label:
            continue
        bare = path.rstrip("/")
        pairs.append((bare + "/", label))
        pairs.append((bare, label))
    for path, label in sorted(pairs, key=lambda pair: len(pair[0]), reverse=True):
        text = text.replace(path, label)
    text = _PATH.sub(lambda match: match.group(0).strip("/").rsplit("/", 1)[-1], text)
    return " ".join(text.split())


def text_preview(item: dict[str, Any]) -> str:
    path = Path(str(item.get("path") or ""))
    if path.suffix.lower() not in TEXT_EXTS or not path.is_file():
        return ""
    try:
        with path.open("rb") as stream:
            blob = stream.read(8192)
        if b"\0" in blob:
            return ""
        return rich_text(blob.decode("utf-8", errors="replace"), "markdown" if path.suffix.lower() == ".md" else "plain")
    except OSError:
        return ""
