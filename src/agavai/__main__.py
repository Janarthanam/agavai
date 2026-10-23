from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import traceback
from pathlib import Path

from agavai.a2a import write_card
from agavai.asr import AsrError, open_stream
from agavai.config import dump_llm_env, load_config, set_model_id
from agavai.feedback import finish, hide_listen, prepare_listen
from agavai.llm import health
from agavai.mcp_server import serve_stdio
from agavai.orchestrator import control_command, run_turn
from agavai.recording import Recorder, control as recording_control, recover
from agavai.state import read_state, write_state
from agavai.tts import cue_listen, cue_record, cue_start, cue_think, speak
from agavai.ui import ChatUi, cancel_ui, summon_overlay


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="agavai", description="Local Omarchy voice assistant")
    sub = parser.add_subparsers(dest="cmd", required=True)
    listen = sub.add_parser("listen", help="Listen and submit when the utterance ends")
    listen.add_argument("--record", action="store_true", help="Record instead; the microphone closes when the recording stops")
    record = sub.add_parser("record", help="Start or stop a recording, or pause, resume, or mark it")
    record.add_argument("action", nargs="?", default="toggle", choices=["toggle", "stop", "pause", "resume", "mark"])
    sub.add_parser("invoke", help="Open the single voice widget and start automatic listening")
    sub.add_parser("stop", help="Stop listening and run the agent")
    sub.add_parser("cancel", help="Abort listening")
    ui_open = sub.add_parser("ui-open", help="Open a selected document or media result")
    ui_open.add_argument("index", type=int)
    ui_open.add_argument("--session", required=True)
    ask = sub.add_parser("ask", help="Run a typed request (no microphone)")
    ask.add_argument("text", nargs="+")
    say = sub.add_parser("speak", help="Speak text with Kokoro (no LLM)")
    say.add_argument("text", nargs="+")
    sub.add_parser("status")
    sub.add_parser("mcp", help="Run the MCP stdio server")
    sub.add_parser("dump-llm", help="Print llama-server env for the launcher script")
    app_cmd = sub.add_parser("app", help="Start Agavai listening (app launcher)")
    app_cmd.description = "Start Agavai listening in the single voice widget"
    model = sub.add_parser("model", help="Show, list, or select the on-device GGUF")
    model.add_argument("action", nargs="?", default="show", choices=["show", "list", "set"])
    model.add_argument("name", nargs="?", help="Model id for 'set'")
    args = parser.parse_args(argv)
    cfg = load_config()
    cfg.runtime_dir.mkdir(parents=True, exist_ok=True)
    write_card(cfg)

    if args.cmd == "ui-open":
        from agavai.ui import open_result
        return 0 if open_result(cfg, args.index, args.session) else 1

    if args.cmd == "mcp":
        serve_stdio()
        return 0
    if args.cmd == "dump-llm":
        sys.stdout.write(dump_llm_env(cfg))
        return 0
    if args.cmd in {"app", "invoke"}:
        from agavai.app import run as run_app

        return run_app()
    if args.cmd == "model":
        return _model_cmd(cfg, args.action, args.name)
    if args.cmd == "status":
        spec = cfg.llm.active_spec()
        print(f"state={read_state(cfg)}")
        print(f"llm={'up' if health(cfg.llm) else 'down'} {cfg.llm.base_url}")
        print(f"model_id={cfg.llm.model_id}")
        print(f"model_path={cfg.llm.model_path}")
        print(f"model_present={cfg.llm.model_path.is_file()}")
        if spec and spec.description:
            print(f"model_desc={spec.description}")
        if cfg.llm.path_overridden:
            print("model_path_overridden=true")
        return 0
    if args.cmd == "speak":
        engine = speak(" ".join(args.text), cfg)
        print(engine)
        return 0 if engine in {"kokoro", "espeak"} else 1
    if args.cmd == "ask":
        text = " ".join(args.text)
        ui = ChatUi(cfg)
        ui.begin_session()
        cue_think(cfg)
        write_state(cfg, "thinking")
        reply = run_turn(text, cfg, ui)
        if ui.cancelled():
            write_state(cfg, "idle")
            return 0
        write_state(cfg, "speaking")
        speak(reply, cfg)
        ui.idle()
        write_state(cfg, "idle")
        print(reply)
        return 0
    if args.cmd == "cancel":
        cancel_ui(cfg)
        # Publish the marker before SIGTERM; the listener reads it in its handler.
        _cancel_path(cfg).touch()
        if _signal_listener(cfg):
            return 0
        _cancel_path(cfg).unlink(missing_ok=True)
        finish(cfg)
        write_state(cfg, "idle")
        return 0
    if args.cmd == "listen":
        return listen_session(cfg, ChatUi(cfg), record=args.record)
    if args.cmd == "record":
        return request_recording(cfg, args.action)
    if args.cmd == "stop":
        if _signal_listener(cfg):
            return 0
        print("agavai: no listener is running", file=sys.stderr)
        return 1
    return 2


def _model_cmd(cfg, action: str, name: str | None) -> int:
    if action == "list":
        for mid, spec in sorted(cfg.llm.models.items()):
            mark = "*" if mid == cfg.llm.model_id else " "
            here = "yes" if spec.present() else "no"
            print(f"{mark} {mid:24} on_disk={here:3} {spec.path}")
            if spec.description:
                print(f"    {spec.description}")
        return 0
    if action == "set":
        if not name:
            print("usage: agavai model set <id>", file=sys.stderr)
            return 2
        try:
            cfg = set_model_id(name)
        except ValueError as exc:
            print(exc, file=sys.stderr)
            return 1
        print(f"model_id={cfg.llm.model_id}")
        print(f"model_path={cfg.llm.model_path}")
        print("restart the runner: systemctl --user restart agavai-llm")
        return 0
    spec = cfg.llm.active_spec()
    print(f"model_id={cfg.llm.model_id}")
    print(f"model_path={cfg.llm.model_path}")
    print(f"model_present={cfg.llm.model_path.is_file()}")
    print(f"ctx_size={cfg.llm.ctx_size}")
    print(f"n_gpu_layers={cfg.llm.n_gpu_layers}")
    if spec and spec.description:
        print(f"description={spec.description}")
    return 0


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
    if not summon_overlay():
        print("Could not open Agavai. Ensure the Omarchy shell and janar.agavai plugin are running.", file=sys.stderr)
        return 1
    return 0 if start_session(cfg, record=True) else 1


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


def start_session(cfg, *, record: bool = False) -> bool:
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
            [sys.executable, "-m", "agavai", "listen", *(["--record"] if record else [])],
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


def listen_session(cfg, ui: ChatUi, *, record: bool = False) -> int:
    """One listen process. Partials update the overlay; end of utterance runs the turn.

    The mic stays open until the user dismisses it or the capture ends.
    A finished action returns to listening with the results still on screen.
    The recognizer, not a silence timer, decides when the line is finished.
    With record, the session records first and ends when the recording stops.
    """
    _cancel_path(cfg).unlink(missing_ok=True)
    _record_request_path(cfg).unlink(missing_ok=True)
    _publish_pid(cfg, os.getpid())
    stop_requested = False
    cancel_requested = False
    requests = _RecordRequests(cfg)

    def on_sigterm(signum, frame):
        nonlocal stop_requested, cancel_requested
        stop_requested = True
        cancel_requested = _cancel_path(cfg).exists()

    def on_record_request(signum, frame):
        requests.signalled = True

    prev_handler = signal.signal(signal.SIGTERM, on_sigterm)
    prev_record_handler = signal.signal(signal.SIGUSR1, on_record_request)
    reply: str | None = None
    followups = 0
    stream = None
    try:
        if record:
            ui.begin_session()
            return 1 if _record_session(cfg, ui, requests, lambda: stop_requested) == "error" else 0
        try:
            stream = open_stream(cfg)
        except AsrError as exc:
            ui.error(str(exc))
            write_state(cfg, "error")
            print(exc, file=sys.stderr)
            return 1
        cue_start(cfg)
        while True:
            heard, text = _await_utterance(
                cfg,
                ui,
                stream,
                fresh=followups == 0,
                stop_requested=lambda: stop_requested,
                cancel_requested=lambda: cancel_requested,
                record_requested=lambda: requests.signalled,
            )
            if heard == "error":
                return 1
            if heard == "record":
                # Only a toggle starts a recording; stop, pause, and mark need one running.
                if "toggle" in requests.take():
                    if _record_session(cfg, ui, requests, lambda: stop_requested) == "cancel":
                        return 0
                    stop_requested = False
                    followups += 1
                ui.continue_listening()
                continue
            if heard == "cancel" or ui.cancelled():
                return 0
            if heard == "ignore":
                stop_requested = False
                cancel_requested = False
                continue
            if heard != "speech":
                if ui.data.get("phase") != "listening" and not ui.cancelled():
                    ui.continue_listening()
                return 0
            if not text.strip():
                speak("I did not hear anything.", cfg)
                if ui.cancelled():
                    return 0
                stop_requested = False
                cancel_requested = False
                ui.continue_listening()
                continue
            reply = _run_stop_body(
                cfg,
                ui,
                lambda: stop_requested and cancel_requested,
                continue_conversation=followups > 0,
                text=text,
            )
            if reply is None:  # cancelled mid-turn
                finish(cfg)
                ui.idle()
                write_state(cfg, "idle")
                return 0
            if ui.cancelled():
                return 0
            followups += 1
            stop_requested = False
            cancel_requested = False
            ui.continue_listening()
    finally:
        if stream is not None:
            stream.close()
        from agavai.tts import sweep_playback_wavs

        sweep_playback_wavs()
        try:
            _pid_path(cfg).unlink()
        except OSError:
            pass
        if read_state(cfg) in {"listening", "recording"}:
            write_state(cfg, "idle")
        signal.signal(signal.SIGTERM, prev_handler)
        signal.signal(signal.SIGUSR1, prev_record_handler)
    print(reply or "")
    return 0


def _await_utterance(
    cfg, ui: ChatUi, stream, *, fresh: bool, stop_requested, cancel_requested, record_requested=lambda: False
) -> tuple[str, str]:
    """Capture one utterance. Returns (speech|cancel|record|error|ended, text)."""
    try:
        prepare_listen(cfg)
        if fresh:
            ui.listening()
        cue_listen(cfg)
    except Exception as exc:
        finish(cfg)
        ui.error(str(exc))
        write_state(cfg, "error")
        print(exc, file=sys.stderr)
        return "error", ""
    write_state(cfg, "listening")
    hypothesis = ""
    try:
        for kind, text in stream.events(
            on_level=ui.level,
            should_stop=lambda: stop_requested() or record_requested(),
        ):
            if kind == "interim" and text:
                hypothesis = text
                ui.partial(text)
            elif kind == "eob" and text:
                hypothesis = text
                ui.partial(text)
            elif kind == "eou":
                line = (text or hypothesis).strip()
                if not line:
                    return "ignore", ""
                ui.partial(line)
                return "speech", line
            if stop_requested() or record_requested():
                break
    except AsrError as exc:
        finish(cfg)
        ui.error(str(exc))
        write_state(cfg, "error")
        print(exc, file=sys.stderr)
        return "error", ""
    if stop_requested() and cancel_requested():
        ui.partial("")
        finish(cfg)
        ui.idle()
        write_state(cfg, "idle")
        return "cancel", ""
    if record_requested():
        ui.partial("")
        return "record", ""
    if stop_requested():
        return "speech", hypothesis.strip()
    return "ended", ""


def _record_session(cfg, ui: ChatUi, requests: _RecordRequests, stopping) -> str:
    """One recording. Every way of stopping saves it: SIGTERM, "Agavai stop", and `agavai record`.

    Returns "saved", "cancel" when the overlay was dismissed (the recording is
    still saved), or "error" when recording could not start.
    """
    recover(cfg)
    try:
        stream = open_stream(cfg, continuous=True)
    except AsrError as exc:
        ui.error(str(exc))
        write_state(cfg, "error")
        print(exc, file=sys.stderr)
        return "error"
    try:
        try:
            prepare_listen(cfg)
            recorder = Recorder(cfg)
        except OSError as exc:
            message = f"Could not start recording: {exc.strerror or exc}."
            ui.error(message)
            write_state(cfg, "error")
            print(message, file=sys.stderr)
            return "error"
        cue_record(cfg, starting=True)
        write_state(cfg, "recording")
        ui.end_recording()
        ui.recording(recorder.live("", True), summon=True)
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
            for msg in stream.record(recorder.audio, should_stop=lambda: bool(ended) or stopping()):
                kind = msg["kind"]
                if kind == "level":
                    ui.data["level_db"] = msg["db"]
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
                ui.recording(recorder.live(partial, transcribing))
        except AsrError as exc:
            problem = str(exc)
        if not ended and not stopping() and not problem:
            problem = "The microphone stopped, so the recording was saved."
    finally:
        stream.close()
        finish(cfg)
    if recorder.discard_if_empty():
        ui.end_recording()
        ui.error(problem or "Nothing was recorded.")
        write_state(cfg, "error")
        return "error"
    folder = recorder.finish()
    cue_record(cfg, starting=False)
    ui.end_recording()
    if ui.cancelled():
        return "cancel"
    ui.display({"kind": "recording", "title": recorder.meta["title"], "path": str(folder), "duration_ms": recorder.meta["duration_ms"]})
    problem = recorder.error or problem
    if problem:
        ui.error(problem)
    else:
        ui.idle()
    write_state(cfg, "idle")
    return "saved"


def _run_stop_body(
    cfg,
    ui: ChatUi,
    stop_requested: bool,
    *,
    continue_conversation: bool = False,
    text: str = "",
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
        reply = run_turn(text, cfg, ui, continue_conversation=continue_conversation)
    except Exception:
        traceback.print_exc()
        reply = "The local agent hit an error."
        ui.error(reply)
    if aborted():
        return None
    if not reply:
        finish(cfg)
        write_state(cfg, "listening")
        return reply
    write_state(cfg, "speaking")
    finish(cfg)
    from agavai.tts import _interruptible_speak

    result = _interruptible_speak(reply, cfg, stop_requested=lambda: aborted())
    if result in {"cancelled", "silent"}:
        return None if result == "cancelled" else reply
    return reply


if __name__ == "__main__":
    raise SystemExit(main())
