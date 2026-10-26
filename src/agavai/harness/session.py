"""Microphone session lifecycle and local control transport."""
from __future__ import annotations

import logging
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from agavai import journal
from agavai.asr import AsrError, open_stream
from agavai.feedback import finish, hide_listen, prepare_listen
from agavai.harness.engine import control_command
from agavai.harness import Harness
from agavai.recording import Recorder, control as recording_control, correct, recover
from agavai.state import read_state, write_state
from agavai.tts import cue_listen, cue_record, cue_start, cue_think, speak
from agavai.harness.events import EventDeliveryError, HarnessOutput

log = logging.getLogger(__name__)

def _pid_marker(pid: int) -> str:
    try:
        return Path(f"/proc/{pid}/stat").read_text().split(" ", 22)[21]
    except (OSError, IndexError):
        return ""


def _live_identity(pid: int, marker: str) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return bool(marker) and _pid_marker(pid) == marker


def _pid_path(cfg) -> Path:
    return cfg.runtime_dir / "listen.pid"


def _lock_path(cfg) -> Path:
    return cfg.runtime_dir / "listen.lock"


def _cancel_path(cfg) -> Path:
    return cfg.runtime_dir / "listen.cancel"


def _record_request_path(cfg) -> Path:
    return cfg.runtime_dir / "record.request"


class _RecordRequests:
    """Actions from `agavai record`: appended to a file, then SIGUSR1 to the listener."""

    def __init__(self, cfg) -> None:
        self.path = _record_request_path(cfg)
        self.signalled = False

    def take(self) -> list[str]:
        if not self.signalled:
            return []
        self.signalled = False
        taking = self.path.with_suffix(".taking")
        try:
            # Renaming first means an action appended meanwhile waits for the next signal.
            self.path.replace(taking)
        except FileNotFoundError:
            return []
        actions = taking.read_text().split()
        taking.unlink(missing_ok=True)
        return actions


def request_recording(cfg, action: str) -> int:
    """`agavai record`: hand the action to the running listener, or start a recording session."""
    pid = read_listener(cfg)
    state = read_state(cfg)
    if action != "toggle" and (pid is None or state != "recording"):
        print("agavai: no recording is running", file=sys.stderr)
        return 1
    if pid is not None:
        # A listener still starting has no SIGUSR1 handler yet, and the signal would end it.
        if state not in {"listening", "thinking", "speaking", "recording"}:
            return 0
        with _record_request_path(cfg).open("a") as requests:
            requests.write(action + "\n")
        os.kill(pid, signal.SIGUSR1)
        return 0
    from agavai.app import open_session
    return open_session(cfg, record=True)


def read_listener(cfg) -> int | None:
    """Live, identity-matched listener PID, or None when stale/absent."""
    try:
        pid_s, marker = _pid_path(cfg).read_text().split()
        pid = int(pid_s)
    except (OSError, ValueError):
        return None
    return pid if _live_identity(pid, marker) else None


def _publish_pid(cfg, pid: int) -> None:
    cfg.runtime_dir.mkdir(parents=True, exist_ok=True)
    _pid_path(cfg).write_text(f"{pid} {_pid_marker(pid)}")


def _correct_cmd(cfg, folder: Path, line: int, text: str) -> int:
    # The overlay passes a path from the snapshot; only recordings in the configured folder change.
    folder = folder.expanduser().resolve()
    if folder.parent != cfg.recordings.dir.resolve():
        print(f"agavai: {folder} is not a recording in {cfg.recordings.dir}", file=sys.stderr)
        return 1
    try:
        correct(folder, line, text)
    except ValueError as exc:
        print(f"agavai: {exc}", file=sys.stderr)
        return 1
    return 0


def start_session(cfg, *, record: bool = False, session_id: str | None = None) -> bool:
    """Shared detached-start guard: O_EXCL lock → existence check → publish.

    Returns True when this caller spawned the listener; False when a session
    already exists or another process is mid-start (the press is a no-op).
    """
    cfg.runtime_dir.mkdir(parents=True, exist_ok=True)
    try:
        lock_fd = os.open(_lock_path(cfg), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        try:
            lock_owner = _lock_path(cfg).read_text().split()
            if len(lock_owner) == 2 and _live_identity(int(lock_owner[0]), lock_owner[1]):
                return False  # another starter is mid-critical-section
        except (OSError, ValueError):
            pass
        # stale lock: reclaimed by removing and retrying once
        try:
            _lock_path(cfg).unlink()
        except OSError:
            return False
        try:
            lock_fd = os.open(_lock_path(cfg), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            return False
    try:
        if read_listener(cfg) is not None:
            return False
        proc = subprocess.Popen(
            [sys.executable, "-m", "agavai", "listen", *(["--record"] if record else []), *(["--session", session_id] if session_id else [])],
            start_new_session=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        _publish_pid(cfg, proc.pid)
        return True
    finally:
        os.close(lock_fd)
        _lock_path(cfg).unlink(missing_ok=True)


def _signal_listener(cfg) -> bool:
    pid = read_listener(cfg)
    if pid is None:
        return False
    os.kill(pid, signal.SIGTERM)
    return True


def listen_session(cfg, *, harness: Harness, record: bool = False) -> int:
    """One listen process. Partials update the overlay; end of utterance runs the turn.

    The mic stays open until the user dismisses it or the capture ends.
    A finished action returns to listening with the results still on screen.
    Native EOU or Enter ends input; final decoding completes before submission.
    With record, the session records first and ends when the recording stops.
    """
    output = harness.output
    external_cancel = harness.should_cancel
    _cancel_path(cfg).unlink(missing_ok=True)
    _record_request_path(cfg).unlink(missing_ok=True)
    _publish_pid(cfg, os.getpid())
    stop_requested = False
    cancel_requested = False
    requests = _RecordRequests(cfg)
    harness.should_cancel = lambda: external_cancel() or (stop_requested and cancel_requested) or requests.signalled

    def on_sigterm(signum, frame):
        nonlocal stop_requested, cancel_requested
        stop_requested = True
        cancel_requested = _cancel_path(cfg).exists()

    def on_record_request(signum, frame):
        requests.signalled = True

    prev_handler = signal.signal(signal.SIGTERM, on_sigterm)
    prev_record_handler = signal.signal(signal.SIGUSR1, on_record_request)
    reply: str | None = None
    followups = len(harness.context.committed_requests)
    harness.input_mode = "spoken"
    capture = None
    stream = None
    ended = "crashed"
    try:
        log.info("session start")
        if record:
            ended = _record_session(cfg, output, requests, lambda: stop_requested, harness=harness, dismissed=external_cancel)
            return 1 if ended == "error" else 0
        try:
            stream = open_stream(cfg)
        except AsrError as exc:
            output.error(str(exc))
            write_state(cfg, "error")
            log.error("asr did not start: %s", exc)
            ended = "recognizer did not start"
            return 1
        cue_start(cfg)
        while True:
            if capture is not None:
                capture.discard()
            harness.poll_audio()
            capture = harness.capture_audio()
            heard, text = _await_utterance(
                cfg,
                output,
                stream,
                audio=capture,
                poll_audio=harness.poll_audio,
                fresh=followups == 0,
                stop_requested=lambda: stop_requested or external_cancel(),
                cancel_requested=lambda: cancel_requested or external_cancel(),
                record_requested=lambda: requests.signalled,
            )
            if heard == "error":
                ended = "error"
                return 1
            if heard == "record":
                # Only a toggle starts a recording; stop, pause, and mark need one running.
                if "toggle" in requests.take():
                    if _record_session(cfg, output, requests, lambda: stop_requested, harness=harness, dismissed=external_cancel) == "cancel":
                        return 0
                    stop_requested = False
                    followups += 1
                output.continue_listening()
                continue
            if heard == "cancel" or external_cancel():
                ended = "cancel" if heard == "cancel" else "dismissed"
                return 0
            if heard == "ignore":
                stop_requested = False
                cancel_requested = False
                continue
            if heard != "speech":
                if output.phase != "listening" and not external_cancel():
                    output.continue_listening()
                ended = "stream ended"
                return 0
            if not text.strip():
                speak("I did not hear anything.", cfg)
                if external_cancel():
                    ended = "dismissed"
                    return 0
                stop_requested = False
                cancel_requested = False
                output.continue_listening()
                continue
            reply = _run_stop_body(
                cfg,
                output,
                lambda: external_cancel() or (stop_requested and cancel_requested),
                continue_conversation=followups > 0,
                text=text,
                harness=harness,
                audio=capture,
            )
            if reply is None:  # cancelled mid-turn
                finish(cfg)
                output.idle()
                write_state(cfg, "idle")
                ended = "cancel during the turn"
                return 0
            if external_cancel():
                ended = "dismissed"
                return 0
            followups += 1
            stop_requested = False
            cancel_requested = False
            output.continue_listening()
    except Exception:
        log.exception("session crashed")
        raise
    finally:
        if capture is not None:
            capture.discard()
        log.info("session end reason=%s", ended)
        try:
            if stream is not None:
                stream.close()
            from agavai.brain import close_brains
            close_brains()
            from agavai.tts import sweep_playback_wavs
            sweep_playback_wavs()
        finally:
            try:
                harness.close()
            finally:
                _pid_path(cfg).unlink(missing_ok=True)
                if read_state(cfg) in {"listening", "recording"}:
                    write_state(cfg, "idle")
                harness.should_cancel = external_cancel
                signal.signal(signal.SIGTERM, prev_handler)
                signal.signal(signal.SIGUSR1, prev_record_handler)
    print(reply or "")
    return 0


def _await_utterance(
    cfg, output: HarnessOutput, stream, *, fresh: bool, stop_requested, cancel_requested, record_requested=lambda: False, audio=None, poll_audio=lambda: None
) -> tuple[str, str]:
    """Capture one utterance. Returns (speech|cancel|record|error|ended, text)."""
    try:
        prepare_listen(cfg)
        if fresh:
            output.listening()
        cue_listen(cfg)
    except Exception as exc:
        finish(cfg)
        output.error(str(exc))
        write_state(cfg, "error")
        log.exception("listen failed: %s", exc)
        return "error", ""
    journal.start_request(output.context.session_id)
    write_state(cfg, "listening")
    started = time.monotonic()

    def captured(reason: str, line: str = "") -> None:
        log.info("asr end reason=%s words=%d secs=%.2f", reason, len(line.split()), time.monotonic() - started)

    def on_level(db):
        poll_audio()
        output.level(db, "active" if cfg.asr.endpoint == "vad" else "off",
                     cfg.vad.backend if cfg.asr.endpoint == "vad" else "off")

    try:
        for kind, text in stream.events(
            **({"audio_tap": audio.write} if audio is not None else {}),
            on_level=on_level,
            should_stop=lambda: stop_requested() or record_requested(),
            should_cancel=lambda: record_requested() or (stop_requested() and cancel_requested()),
        ):
            if kind == "finishing":
                output.transcribing()
                write_state(cfg, "transcribing")
            elif kind == "interim" and text:
                output.partial(text)
            elif kind == "eob" and text:
                output.partial(text)
            elif kind == "eou":
                if stop_requested() and cancel_requested():
                    break
                line = text.strip()
                if not line:
                    captured("empty")
                    return "ignore", ""
                captured("enter" if stop_requested() else "eou", line)
                output.partial(line)
                return "speech", line
            if record_requested():
                break
    except AsrError as exc:
        finish(cfg)
        output.error(str(exc))
        write_state(cfg, "error")
        log.error("asr failed: %s", exc)
        return "error", ""
    if stop_requested() and cancel_requested():
        captured("cancel")
        output.partial("")
        finish(cfg)
        output.idle()
        write_state(cfg, "idle")
        return "cancel", ""
    if record_requested():
        output.partial("")
        return "record", ""
    captured("stream_ended")
    return "ended", ""


def _record_session(cfg, output: HarnessOutput, requests: _RecordRequests, stopping, *, harness: Harness, dismissed) -> str:
    """One recording. Every way of stopping saves it: SIGTERM, "Agavai stop", and `agavai record`.

    Returns "saved", "cancel" when the overlay was dismissed (the recording is
    still saved), or "error" when recording could not start.
    """
    recover(cfg)
    try:
        stream = open_stream(cfg, continuous=True)
    except AsrError as exc:
        output.error(str(exc))
        write_state(cfg, "error")
        print(exc, file=sys.stderr)
        return "error"
    try:
        try:
            prepare_listen(cfg)
            recorder = Recorder(cfg)
        except OSError as exc:
            message = f"Could not start recording: {exc.strerror or exc}."
            output.error(message)
            write_state(cfg, "error")
            print(message, file=sys.stderr)
            return "error"
        cue_record(cfg, starting=True)
        write_state(cfg, "recording")
        output.end_recording()
        output.recording(recorder.live("", True), summon=True)
        ended = ""
        partial = ""
        transcribing = True
        problem = ""

        def act(action: str) -> None:
            nonlocal ended
            if action in {"stop", "toggle"}:
                ended = "stop"
            elif action == "pause":
                recorder.pause()
            elif action == "resume":
                recorder.resume()
            elif action == "mark":
                recorder.mark()

        try:
            for msg in stream.record(recorder.audio, should_stop=lambda: bool(ended) or stopping() or dismissed()):
                kind = msg["kind"]
                if kind == "level":
                    output.level(msg["db"], "off", "off")
                elif kind in {"interim", "eob"}:
                    partial = msg.get("text") or ""
                elif kind == "eou":
                    partial = ""
                    line = msg.get("text") or ""
                    action = recording_control(line)
                    if action:
                        act(action)
                    else:
                        recorder.add_line(line, int(msg.get("start_ms") or 0), int(msg.get("end_ms") or 0))
                elif kind == "asr_lost":
                    transcribing = False
                for action in requests.take():
                    act(action)
                if recorder.error:
                    ended = "error"
                output.recording(recorder.live(partial, transcribing))
        except AsrError as exc:
            problem = str(exc)
        if not ended and not stopping() and not problem:
            problem = "The microphone stopped, so the recording was saved."
    finally:
        stream.close()
        finish(cfg)
    if recorder.discard_if_empty():
        output.end_recording()
        output.error(problem or "Nothing was recorded.")
        write_state(cfg, "error")
        return "error"
    folder = recorder.finish()
    harness.context.recording = folder
    harness.context.source_active = True
    from agavai.harness.sources import refresh_recording
    refresh_recording(cfg, harness.context)
    output.source_changed({"kind": "recording", "path": str(folder), "revision": harness.context.source_revision,
                           "derived_stale": bool(harness.context.derived_revision and harness.context.derived_revision != harness.context.source_revision)})
    cue_record(cfg, starting=False)
    output.end_recording()
    if dismissed():
        return "cancel"
    output.display({"kind": "recording", "title": recorder.meta["title"], "path": str(folder), "duration_ms": recorder.meta["duration_ms"]})
    problem = recorder.error or problem
    if problem:
        output.error(problem)
    else:
        output.idle()
    write_state(cfg, "idle")
    return "saved"


def _run_stop_body(
    cfg,
    output: HarnessOutput,
    stop_requested: bool,
    *,
    continue_conversation: bool = False,
    text: str = "",
    harness: Harness,
    audio=None,
) -> str | None:
    """Run one committed line. The text is already final."""

    def aborted() -> bool:
        return stop_requested() if callable(stop_requested) else stop_requested

    if aborted():
        return None
    resetting = control_command(text) == "agavai"
    hide_listen(cfg)
    if not resetting:
        cue_think(cfg)
    if aborted():
        return None
    if not text.strip():
        speak("I did not hear anything.", cfg)
        return ""
    if not resetting:
        write_state(cfg, "thinking")
    try:
        reply = harness.run_turn(text, continue_conversation=continue_conversation, audio=audio)
    except EventDeliveryError:
        raise
    except Exception:
        log.exception("turn failed")
        reply = "The local agent hit an error."
        output.error(reply)
    if aborted():
        return None
    if not reply:
        finish(cfg)
        write_state(cfg, "listening")
        return reply
    write_state(cfg, "speaking")
    finish(cfg)
    from agavai.tts import _interruptible_speak

    result = _interruptible_speak(reply, cfg, stop_requested=lambda: aborted(), on_engine=output.speech)
    if result in {"cancelled", "silent"}:
        return None if result == "cancelled" else reply
    return reply

