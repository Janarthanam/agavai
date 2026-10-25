"""Tool groups and schemas for agents configured to use routing."""

from __future__ import annotations

from dataclasses import dataclass

from agavai.tools import OPENAPI_TOOLS


@dataclass(frozen=True)
class ToolHead:
    id: str
    criteria: str
    keywords: tuple[str, ...]
    tools: tuple[str, ...]


HEADS: tuple[ToolHead, ...] = (
    ToolHead(
        "wallpaper",
        "Wallpaper, desktop background, or screensaver images, including showing the pictures and setting the one the user names.",
        ("wallpaper", "background", "backdrop", "desktop picture", "wall paper", "screensaver", "screen saver"),
        ("wallpaper_current", "wallpaper_list", "wallpaper_set", "wallpaper_next", "wallpaper_picker"),
    ),
    ToolHead(
        "appearance",
        "Omarchy theme, night light, fonts, appearance (not wallpaper).",
        ("theme", "nightlight", "night light", "font", "appearance", "dark mode"),
        ("list_themes", "set_theme", "toggle_nightlight"),
    ),
    ToolHead(
        "audio",
        "Speaker volume, mute, microphone mute, bluetooth power.",
        ("volume", "mute", "mic", "microphone", "quiet", "louder", "softer", "bluetooth"),
        ("set_volume", "mute_microphone", "bluetooth"),
    ),
    ToolHead(
        "windows",
        "Windows, workspaces, focus, close, fullscreen.",
        ("window", "workspace", "fullscreen", "close", "focus", "monitor"),
        (
            "list_windows",
            "focus_window",
            "close_window",
            "to_workspace",
            "workspace_step",
            "toggle_fullscreen",
        ),
    ),
    ToolHead(
        "system",
        "Lock, idle/stay awake, do-not-disturb, battery, network, brightness.",
        ("lock", "battery", "wifi", "network", "brightness", "awake", "idle", "disturb", "dnd"),
        (
            "lock_screen",
            "stay_awake",
            "dnd",
            "battery_status",
            "network_status",
            "set_brightness",
        ),
    ),
    ToolHead(
        "launch",
        "Open or launch apps, browser, urls.",
        ("open", "launch", "start app", "firefox", "browser", "spotify", "youtube", "url"),
        ("launch", "open_app", "play_url"),
    ),
    ToolHead(
        "files",
        "Find files on disk by name.",
        ("file", "find", "search", "document", "folder"),
        ("search_files",),
    ),
    ToolHead(
        "capture",
        "Screenshot or read what is on screen.",
        ("screenshot", "screen", "ocr", "capture", "what's on"),
        ("screenshot", "screen_context"),
    ),
    ToolHead(
        "recordings",
        "Record the microphone to keep the audio and a transcript (take notes, transcribe a meeting), or list past recordings.",
        ("record", "recording", "recordings", "take notes", "transcribe", "transcript"),
        ("start_recording", "list_recordings"),
    ),
    ToolHead(
        "reminders",
        "Reminders, notifications, current time.",
        ("remind", "reminder", "notify", "notification", "time", "clock", "date"),
        ("reminder", "list_reminders", "clear_reminders", "send_notification", "clock_now"),
    ),
    ToolHead(
        "agents",
        "List installed assistant agents and their capabilities.",
        ("agents", "available agents", "installed agents"),
        ("list_agents",),
    ),
)

HEAD_BY_ID = {h.id: h for h in HEADS}
TOOL_TO_HEAD = {name: h.id for h in HEADS for name in h.tools}

JEV_HEAD_CRITERIA = {h.id: h.criteria for h in HEADS}
JEV_HEAD_CRITERIA["chat"] = "Chit-chat, greetings, or questions that need no desktop action."


def schemas_for_names(names: list[str], *, limit: int = 8) -> list[dict]:
    by_name = {item["function"]["name"]: item for item in OPENAPI_TOOLS}
    out = []
    seen: set[str] = set()
    for name in names:
        if name in seen or name not in by_name:
            continue
        seen.add(name)
        out.append(by_name[name])
        if len(out) >= limit:
            break
    return out


def schemas_for_heads(head_ids: list[str], *, limit: int = 8) -> list[dict]:
    names: list[str] = []
    for hid in head_ids:
        head = HEAD_BY_ID.get(hid)
        if head:
            names.extend(head.tools)
    return schemas_for_names(names, limit=limit)


def head_for_tool(name: str) -> str | None:
    return TOOL_TO_HEAD.get(name)
