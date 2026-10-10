"""Load cases and know where each section belongs.

A case states what was said and what must hold afterwards. It names no tool
and no route; `needs` names capabilities, not mechanisms.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

CASE_DIR = Path(__file__).with_name("cases")
DEFAULT_NOW = "2026-10-09T16:45"

AREAS: dict[str, list[str]] = {
    "understand": ["phrasing", "values", "messy_speech", "conversation", "judgment"],
    "do": ["desktop", "files", "mail", "calendar", "people", "notes", "lookups", "multi_step"],
    "reach": ["mcp", "computer_use", "screen_reading"],
    "remember": ["within_session", "across_sessions", "updating", "habits"],
    "trust": ["truthfulness", "safety", "consequences", "privacy"],
    "voice": ["hearing", "turn_taking", "spoken_tasks", "reply_contract", "speech_output"],
    "practical": ["speed", "efficiency", "interruption", "reliability", "footprint"],
}
SECTION_AREA = {section: area for area, sections in AREAS.items() for section in sections}
TITLES = {
    "phrasing": "Phrasing", "values": "Values", "messy_speech": "Messy speech", "conversation": "Conversation",
    "judgment": "Judgment", "desktop": "Desktop", "files": "Files and documents", "mail": "Mail",
    "calendar": "Calendar", "people": "People and messages", "notes": "Notes, lists, tasks",
    "lookups": "Lookups and media", "multi_step": "Multi-step", "mcp": "MCP tools", "computer_use": "Computer use",
    "screen_reading": "Screen reading", "within_session": "Within a session", "across_sessions": "Across sessions",
    "updating": "Updating and forgetting", "habits": "Habits and initiative", "truthfulness": "Truthfulness",
    "safety": "Safety", "consequences": "Consequences", "privacy": "Privacy", "hearing": "Hearing",
    "turn_taking": "Turn taking", "spoken_tasks": "Spoken tasks", "reply_contract": "Reply contract",
    "speech_output": "Speech output", "speed": "Speed", "efficiency": "Efficiency", "interruption": "Interruption",
    "reliability": "Reliability", "footprint": "Footprint",
}
AREA_TITLES = {area: area.capitalize() for area in AREAS}
MEASURED = {"speed", "interruption", "reliability", "footprint"}
DERIVED = {"reply_contract", "efficiency"}

# Capabilities a case may need. One counts as shipped when a binding for it
# exists and passes its self-check; none of these has one yet.
CAPABILITIES = {
    "mail", "calendar", "contacts", "messages", "notes", "files", "lookup", "media", "mcp",
    "computer_use", "memory", "initiative", "barge_in", "long_reminders",
}

TURN_KEYS = {
    "say", "kind", "checks", "reply_any", "reply_all", "reply_none", "number", "harm_reply", "never_say", "claims",
    "allow", "shown", "abstain", "new_session", "advance_hours", "max_model_calls", "context",
}
CASE_KEYS = {"id", "section", "needs", "now", "world", "set", "cluster", "exclude", "note", "turns", "run", "spoken"}
KINDS = {"act", "ask", "decline", "ignore", "answer"}


@dataclass
class Case:
    id: str
    section: str
    turns: list[dict[str, Any]]
    needs: list[str] = field(default_factory=list)
    now: str = DEFAULT_NOW
    world: str = "default"
    set: dict[str, Any] = field(default_factory=dict)
    cluster: str = ""
    exclude: str = ""
    note: str = ""
    run: bool = True
    spoken: dict[str, Any] = field(default_factory=dict)

    @property
    def area(self) -> str:
        return SECTION_AREA[self.section]

    @property
    def clock(self) -> datetime:
        return datetime.fromisoformat(self.now)

    def shipped(self, capabilities: set[str]) -> bool:
        return set(self.needs) <= capabilities


def _turn(raw: dict[str, Any], where: str) -> dict[str, Any]:
    unknown = set(raw) - TURN_KEYS
    if unknown:
        raise ValueError(f"{where}: unknown turn keys {sorted(unknown)}")
    if raw.get("kind") not in KINDS:
        raise ValueError(f"{where}: kind must be one of {sorted(KINDS)}")
    if not isinstance(raw.get("say"), str):
        raise ValueError(f"{where}: say is required")
    return raw


def parse(raw: dict[str, Any], source: str) -> Case:
    where = f"{source}:{raw.get('id', '?')}"
    turns = raw.get("turns")
    single = {k: v for k, v in raw.items() if k in TURN_KEYS}
    unknown = set(raw) - CASE_KEYS - TURN_KEYS
    if unknown:
        raise ValueError(f"{where}: unknown case keys {sorted(unknown)}")
    if turns and single:
        raise ValueError(f"{where}: use either turns or a single say")
    turns = [_turn(t, where) for t in (turns or [single])]
    case = Case(
        id=raw["id"],
        section=raw["section"],
        turns=turns,
        needs=list(raw.get("needs", [])),
        now=raw.get("now", DEFAULT_NOW),
        world=raw.get("world", "default"),
        set=dict(raw.get("set", {})),
        cluster=raw.get("cluster", raw["id"]),
        exclude=raw.get("exclude", ""),
        note=raw.get("note", ""),
        run=raw.get("run", True),
        spoken=dict(raw.get("spoken", {})),
    )
    if case.section not in SECTION_AREA:
        raise ValueError(f"{where}: unknown section {case.section}")
    if set(case.needs) - CAPABILITIES:
        raise ValueError(f"{where}: unknown capability {sorted(set(case.needs) - CAPABILITIES)}")
    return case


def load_cases(directory: Path = CASE_DIR) -> list[Case]:
    cases: list[Case] = []
    for path in sorted(directory.glob("*.toml")):
        data = tomllib.loads(path.read_text(encoding="utf-8"))
        cases.extend(parse(raw, path.name) for raw in data.get("case", []))
    ids = [c.id for c in cases]
    duplicates = sorted({i for i in ids if ids.count(i) > 1})
    if duplicates:
        raise ValueError(f"duplicate case ids {duplicates}")
    return cases
