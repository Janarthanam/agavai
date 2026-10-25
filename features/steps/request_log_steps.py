from __future__ import annotations

import io
import json
import logging
import os
import re
import socket
import tempfile
from pathlib import Path
from unittest.mock import patch

from behave import given, then, when

from agavai import journal
from agavai.__main__ import listen_session, main
from agavai.router import select_head_ids


def _start(context, patcher):
    patcher.start()
    context.add_cleanup(patcher.stop)


@given("a journal socket")
def journal_socket(context):
    path = Path(tempfile.mkdtemp()) / "log"
    context.journal_socket = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    context.journal_socket.bind(str(path))
    context.journal_socket.settimeout(2)
    context.add_cleanup(context.journal_socket.close)
    context.journal_path = path


@when('the request log is set up and request 1 of session "{session}" logs "{line}"')
def log_to_socket(context, session, line):
    logger = logging.getLogger("agavai")
    # The capture handler from environment.py would stop setup from adding the journal.
    kept = list(logger.handlers)
    for handler in kept:
        logger.removeHandler(handler)
    try:
        with patch("agavai.journal.JOURNAL_SOCKET", str(context.journal_path)):
            journal.setup("info")
        journal.start_request(session)
        logging.getLogger("agavai.router").info(line)
    finally:
        for handler in list(logger.handlers):
            logger.removeHandler(handler)
            handler.close()
        for handler in kept:
            logger.addHandler(handler)


@then('the journal socket receives "{datagram}"')
def socket_receives(context, datagram):
    # SysLogHandler ends each message with a NUL byte.
    received = context.journal_socket.recv(65536).decode().removesuffix("\x00")
    assert received == datagram, repr(received)


@given("debug logging")
def debug_logging(context):
    context.cfg.log.level = "debug"


@given('llama-server calls "{tool}" and then replies "{reply}"')
def llama_server(context, tool, reply):
    bodies = [
        {
            "choices": [{"message": {"content": None, "tool_calls": [
                {"id": "call-1", "type": "function", "function": {"name": tool, "arguments": '{"query": "budget notes"}'}}
            ]}}],
            "usage": {"prompt_tokens": 120, "completion_tokens": 12},
        },
        {
            "choices": [{"message": {"content": reply}}],
            "usage": {"prompt_tokens": 180, "completion_tokens": 9},
        },
    ]

    def urlopen(request, timeout):
        return io.BytesIO(json.dumps(bodies.pop(0)).encode())

    _start(context, patch("agavai.orchestrator.health", return_value=True))
    _start(context, patch("agavai.llm.urllib.request.urlopen", side_effect=urlopen))


@given('file search finds "{path}"')
def file_search(context, path):
    found = json.dumps([{"path": path, "kind": "file"}])
    _start(context, patch.dict("agavai.tools.DISPATCH", {"search_files": lambda args, cfg: found}))


@when('I ask "{text}"')
def ask(context, text):
    with patch("agavai.__main__.load_config", return_value=context.cfg), patch("agavai.__main__.write_card"), patch("agavai.__main__.cue_think"), patch("agavai.tts._kokoro", return_value="/tmp/reply.wav"):
        context.exit_code = main(["ask", text])
    assert context.exit_code == 0


def _lines(context):
    return context.request_log.lines


@then("the request log for request {number:d} reads")
def request_reads(context, number):
    expected = [row["line"] for row in context.table]
    lines = _lines(context)
    ids = {line.split(" ", 1)[0] for line in lines}
    assert len(ids) == 1 and re.fullmatch(rf"request=[0-9a-f]{{8}}-{number}", ids.pop()), lines
    assert len(lines) == len(expected), "\n".join(lines)
    for line, want in zip(lines, expected):
        assert line.split(" ", 1)[1].startswith(want), (line, want)


@then("the listen log reads")
def listen_reads(context):
    session = str(context.ui.data["session_id"])[:8]
    lines = _lines(context)
    assert len(lines) == len(context.table.rows), "\n".join(lines)
    for line, row in zip(lines, context.table):
        request = "-" if row["request"] == "-" else f"{session}-{row['request']}"
        assert line.startswith(f"request={request} {row['line']}"), (line, row["line"])


@then('the request log contains "{text}"')
def contains(context, text):
    assert any(text in line for line in _lines(context)), "\n".join(_lines(context))


@then('the request log does not contain "{text}"')
def lacks(context, text):
    assert not any(text in line for line in _lines(context)), "\n".join(_lines(context))


class _Captures:
    """Recognizer stand-in. Each events() call plays the next capture."""

    def __init__(self, captures):
        self.captures = [list(capture) for capture in captures]

    def events(self, on_level, should_stop=None, should_cancel=None):
        yield from (self.captures.pop(0) if self.captures else [])

    def close(self):
        return None


def _listen(context, captures, turn):
    with patch("agavai.__main__.prepare_listen"), patch("agavai.__main__.cue_listen"), patch("agavai.__main__.cue_start"), patch("agavai.__main__.cue_think"), patch("agavai.__main__.hide_listen"), patch("agavai.__main__.finish"), patch("agavai.__main__._publish_pid"), patch("agavai.tts.sweep_playback_wavs"), patch("agavai.tts._interruptible_speak", return_value="completed"), patch("agavai.__main__.open_stream", return_value=_Captures(captures)), patch("agavai.__main__.run_turn", side_effect=turn):
        context.listen_result = listen_session(context.cfg, context.ui)


@when("an automatic session hears a request, noise, and a follow-up")
def request_noise_followup(context):
    _listen(context, [[("eou", "find the notes")], [("eou", "")], [("eou", "open the first one")], []], lambda *args, **kwargs: "Done.")


@when("an automatic session's turn raises \"{error}\"")
def turn_raises(context, error):
    _listen(context, [[("eou", "find the notes")]], RuntimeError(error))


@given("the Jev router has no OpenRouter key")
def jev_without_key(context):
    context.cfg.router.backend = "jev"
    context.cfg.router.fallback = "keyword"
    _start(context, patch("agavai.router._api_key", return_value=""))


@when('the router picks heads for "{text}"')
def route(context, text):
    context.heads = select_head_ids(text, context.cfg)


@when("agavai status runs with that config")
def status_with_config(context):
    with patch.dict(os.environ, {"AGAVAI_CONFIG": str(context.config_path)}):
        try:
            main(["status"])
        except ValueError:
            return
    raise AssertionError("the config loaded")
