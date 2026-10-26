from __future__ import annotations

import logging
import os
import sys
import tempfile
from unittest.mock import patch
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from agavai import journal  # noqa: E402


class RequestLog(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.lines: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append(self.format(record))


def before_all(context):
    # With a handler in place, journal.setup leaves the user's journal alone.
    context.request_log = RequestLog()
    logging.getLogger("agavai").addHandler(journal.tagged(context.request_log))


def before_scenario(context, scenario):
    folder = tempfile.TemporaryDirectory(prefix="agavai-session-bdd-")
    context.add_cleanup(folder.cleanup)
    storage = patch.dict(os.environ, AGAVAI_SESSION_DIR=folder.name)
    storage.start()
    context.add_cleanup(storage.stop)
    context.request_log.lines.clear()
    logging.getLogger("agavai").setLevel(logging.INFO)
    # A listen process starts outside any request; scenarios share one process.
    journal._request = "-"
