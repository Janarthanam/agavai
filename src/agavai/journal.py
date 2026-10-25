"""Request log in the user journal: `journalctl --user -t agavai`.

Each line names the request it belongs to, so one utterance can be followed
through recognition, routing, the model, tools and speech. What the user said,
replies, and tool arguments and results are logged only at debug level.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from contextvars import ContextVar
import logging.handlers

JOURNAL_SOCKET = "/dev/log"
TEXT_CHARS = 500

_request = "-"
_bound_request = ContextVar("agavai_request", default=None)
_session = ""
_count = 0


def setup(level: str) -> None:
    """Send the agavai loggers to the journal. Later calls only change the level."""
    logger = logging.getLogger("agavai")
    logger.setLevel(level.upper())
    if logger.handlers:
        return
    handler = logging.handlers.SysLogHandler(address=JOURNAL_SOCKET)
    handler.ident = "agavai: "
    logger.addHandler(tagged(handler))


def tagged(handler: logging.Handler) -> logging.Handler:
    """Prefix every line with its request id."""
    handler.addFilter(_stamp_request)
    handler.setFormatter(logging.Formatter("request=%(request)s %(message)s"))
    return handler


def _stamp_request(record: logging.LogRecord) -> bool:
    record.request = _bound_request.get() or _request
    return True


def start_request(session_id: str) -> None:
    """Number each capture in a session: a2bd4d6f-1, a2bd4d6f-2, …"""
    global _request, _session, _count
    if session_id != _session:
        _session, _count = session_id, 0
    _count += 1
    _request = f"{session_id[:8]}-{_count}"


def clip(text: object) -> str:
    """One line of user text for a debug record."""
    line = " ".join(str(text).split())
    return line if len(line) <= TEXT_CHARS else line[: TEXT_CHARS - 1] + "…"


@contextmanager
def request_scope(request):
    token = _bound_request.set(request)
    try:
        yield
    finally:
        _bound_request.reset(token)
