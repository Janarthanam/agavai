"""Bind recording requests to durable, corrected transcript revisions."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

from agavai.recording import _read_meta, correct, line_text, recordings


class SourceError(ValueError):
    pass


def load_recording(cfg, context, text):
    rows = recordings(cfg)
    if re.search(r"\b(last|latest|most recent)\s+(?:recording|transcript|transcription)\b", text, re.I) and rows:
        folder = Path(rows[0]["path"])
    elif context.recording:
        folder = context.recording
    elif len(rows) == 1:
        folder = Path(rows[0]["path"])
    else:
        raise SourceError("Which recording should I use? Say the last recording to select the newest one.")
    context.recording = folder
    return refresh_recording(cfg, context)


def refresh_recording(cfg, context):
    folder = context.recording
    if folder.resolve().parent != cfg.recordings.dir.resolve():
        raise SourceError("That recording is outside the configured recordings folder.")
    meta = _read_meta(folder)
    if not meta or meta.get("status") != "ready":
        raise SourceError("That recording is not ready to read.")
    context.source_active = True
    context.source_revision = hashlib.sha256(json.dumps(meta["segments"], ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    return meta


def transcript(meta):
    return "\n".join(f"Line {s['id']}: {line_text(s)}" for s in meta["segments"])


def correct_transcript(cfg, context, text):
    meta = load_recording(cfg, context, text)
    line = re.search(r"\bline\s+(\d+)\b", text, re.I)
    line_id = int(line[1]) if line else None
    edit = re.sub(r"\s+in (?:the )?(?:transcript|recording|line \d+)[.!?]?$", "", text, flags=re.I)
    replacement = re.search(r'\breplace\s+["“]?(.+?)["”]?\s+with\s+["“]?(.+?)["”]?[.!?]?$', edit, re.I)
    full_line = re.search(r"\bcorrect\s+line\s+\d+\s+to\s+(.+)$", text, re.I)
    candidates = [s for s in meta["segments"] if line_id is None or s["id"] == line_id]
    if full_line and line_id is not None:
        updated = full_line[1].strip()
    elif replacement:
        before = replacement[1].strip(' "“”')
        after = replacement[2].strip(' "“”')
        candidates = [s for s in candidates if before in line_text(s)]
        if len(candidates) != 1 or line_text(candidates[0]).count(before) != 1:
            raise SourceError("That wording is not unique. Specify the line and its complete corrected text.")
        updated = line_text(candidates[0]).replace(before, after, 1)
    else:
        raise SourceError("Give an exact edit, such as replace cube flow with Kubeflow, or correct line 2 to the full corrected text.")
    if len(candidates) != 1:
        raise SourceError("Which transcript line should I correct?")
    correct(context.recording, candidates[0]["id"], updated, expected_text=line_text(candidates[0]))
    refresh_recording(cfg, context)
    return f"Corrected line {candidates[0]['id']}. The original heard words are kept."
