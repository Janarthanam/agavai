from __future__ import annotations

import argparse
import logging
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from agavai import journal
from agavai.a2a import write_card
from agavai.asr import AsrError, open_stream
from agavai.config import dump_llm_env, load_config, set_model_id
from agavai.feedback import finish, hide_listen, prepare_listen
from agavai.llm import health
from agavai.mcp_server import serve_stdio
from agavai.orchestrator import control_command, run_turn
from agavai.state import read_state, write_state
from agavai.tts import cue_listen, cue_start, cue_think, speak
from agavai.ui import ChatUi, cancel_ui

log = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="agavai", description="Local Omarchy voice assistant")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("listen", help="Listen and submit when the utterance ends")
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
    dump = sub.add_parser("dump-llm", help="Print llama-server env for the launcher script")
    dump.add_argument("--role", choices=["service", "small", "large"], default="service")
    app_cmd = sub.add_parser("app", help="Start Agavai listening (app launcher)")
    app_cmd.description = "Start Agavai listening in the single voice widget"
    model = sub.add_parser("model", help="Show, list, or select the on-device GGUF")
    model.add_argument("action", nargs="?", default="show", choices=["show", "list", "set"])
    model.add_argument("name", nargs="?", help="Model id for 'set'")
    services = sub.add_parser("services", help="Show or sync the llama-server services that config.toml needs")
    services.add_argument("action", nargs="?", default="status", choices=["status", "sync"])
    args = parser.parse_args(argv)
    # The hotkey and the detached listener have no terminal, so a bad config
    # must reach the journal before the configured level is known.
    journal.setup("info")
    if args.cmd == "services":
        return _services_cmd(args.action)
    try:
        cfg = load_config()
    except Exception:
        log.exception("config could not be loaded")
        raise
    journal.setup(cfg.log.level)
    cfg.runtime_dir.mkdir(parents=True, exist_ok=True)
    write_card(cfg)

    if args.cmd == "ui-open":
        from agavai.ui import open_result
        return 0 if open_result(cfg, args.index, args.session) else 1

    if args.cmd == "mcp":
        serve_stdio()
        return 0
    if args.cmd == "dump-llm":
        sys.stdout.write(dump_llm_env(cfg, args.role))
        return 0
    if args.cmd in {"app", "invoke"}:
        from agavai.app import run as run_app

        return run_app()
    if args.cmd == "model":
        return _model_cmd(cfg, args.action, args.name)
    if args.cmd == "status":
        from agavai.brain import create_brain
        from agavai.llm import LlmError, chat
        model = cfg.small_brain or cfg.llm
        spec = model.active_spec()
        try:
            available = create_brain(model, chat=chat, health=health).ready()
        except LlmError:
            available = False
        print(f"state={read_state(cfg)}")
        print(f"asr_backend={cfg.asr.backend} endpoint={cfg.asr.endpoint} mode={cfg.asr.mode}")
        print(f"brain_backend={model.backend}")
        print(f"llm={'up' if available else 'down'} {model.base_url if model.backend == 'llama-server' else 'worker'}")
        print(f"model_id={model.model_id}")
        print(f"model_path={model.model_path}")
        print(f"model_present={model.model_path.is_file()}")
        if spec and spec.description:
            print(f"model_desc={spec.description}")
        if model.path_overridden:
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
        journal.start_request(str(ui.data["session_id"]))
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
        return listen_session(cfg, ChatUi(cfg))
    if args.cmd == "stop":
        if _signal_listener(cfg):
            return 0
        print("agavai: no listener is running", file=sys.stderr)
        return 1
    return 2


def _services_cmd(action: str) -> int:
    from agavai.services import ServiceError, service_config, status_lines, sync

    try:
        cfg = service_config()
        lines = sync(cfg) if action == "sync" else status_lines(cfg)
    except (ServiceError, ValueError) as exc:
        print(f"agavai services: {exc}", file=sys.stderr)
        return 1
    print("\n".join(lines))
    return 0


def _apply_services() -> None:
    """Bring the model services in line after this CLI changed config.toml."""
    from agavai.services import ServiceError, service_config, sync

    try:
        for line in sync(service_config()):
            print(line)
    except (ServiceError, ValueError) as exc:
        print(f"services not updated: {exc}", file=sys.stderr)


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
        _apply_services()
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


def start_session(cfg) -> bool:
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
            [sys.executable, "-m", "agavai", "listen"],
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


def listen_session(cfg, ui: ChatUi) -> int:
    """One listen process. Partials update the overlay; end of utterance runs the turn.

    The mic stays open until the user dismisses it or the capture ends.
    A finished action returns to listening with the results still on screen.
    Native EOU or Enter ends input; final decoding completes before submission.
    """
    _cancel_path(cfg).unlink(missing_ok=True)
    _publish_pid(cfg, os.getpid())
    stop_requested = False
    cancel_requested = False

    def on_sigterm(signum, frame):
        nonlocal stop_requested, cancel_requested
        stop_requested = True
        cancel_requested = _cancel_path(cfg).exists()

    prev_handler = signal.signal(signal.SIGTERM, on_sigterm)
    reply: str | None = None
    followups = 0
    stream = None
    ended = "crashed"
    try:
        log.info("session start")
        try:
            stream = open_stream(cfg)
        except AsrError as exc:
            ui.error(str(exc))
            write_state(cfg, "error")
            log.error("asr did not start: %s", exc)
            ended = "recognizer did not start"
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
            )
            if heard == "error":
                ended = "error"
                return 1
            if heard == "cancel" or ui.cancelled():
                ended = "cancel" if heard == "cancel" else "dismissed"
                return 0
            if heard == "ignore":
                stop_requested = False
                cancel_requested = False
                continue
            if heard != "speech":
                if ui.data.get("phase") != "listening" and not ui.cancelled():
                    ui.continue_listening()
                ended = "stream ended"
                return 0
            if not text.strip():
                speak("I did not hear anything.", cfg)
                if ui.cancelled():
                    ended = "dismissed"
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
                ended = "cancel during the turn"
                return 0
            if ui.cancelled():
                ended = "dismissed"
                return 0
            followups += 1
            stop_requested = False
            cancel_requested = False
            ui.continue_listening()
    except Exception:
        log.exception("session crashed")
        raise
    finally:
        log.info("session end reason=%s", ended)
        if stream is not None:
            stream.close()
        from agavai.brain import close_brains
        close_brains()
        from agavai.tts import sweep_playback_wavs

        sweep_playback_wavs()
        try:
            _pid_path(cfg).unlink()
        except OSError:
            pass
        if read_state(cfg) == "listening":
            write_state(cfg, "idle")
        signal.signal(signal.SIGTERM, prev_handler)
    print(reply or "")
    return 0


def _await_utterance(cfg, ui: ChatUi, stream, *, fresh: bool, stop_requested, cancel_requested) -> tuple[str, str]:
    """Capture one utterance. Returns (speech|cancel|error|ended, text)."""
    try:
        prepare_listen(cfg)
        if fresh:
            ui.listening()
        cue_listen(cfg)
    except Exception as exc:
        finish(cfg)
        ui.error(str(exc))
        write_state(cfg, "error")
        log.exception("listen failed: %s", exc)
        return "error", ""
    journal.start_request(str(ui.data["session_id"]))
    write_state(cfg, "listening")
    started = time.monotonic()

    def captured(reason: str, line: str = "") -> None:
        log.info("asr end reason=%s words=%d secs=%.2f", reason, len(line.split()), time.monotonic() - started)

    try:
        for kind, text in stream.events(
            on_level=lambda db: ui.level(db, "active" if cfg.asr.endpoint == "vad" else "off",
                                         cfg.vad.backend if cfg.asr.endpoint == "vad" else "off"),
            should_stop=stop_requested,
            should_cancel=lambda: stop_requested() and cancel_requested(),
        ):
            if kind == "finishing":
                ui.transcribing()
                write_state(cfg, "transcribing")
            elif kind == "interim" and text:
                ui.partial(text)
            elif kind == "eob" and text:
                ui.partial(text)
            elif kind == "eou":
                if stop_requested() and cancel_requested():
                    break
                line = text.strip()
                if not line:
                    captured("empty")
                    return "ignore", ""
                captured("enter" if stop_requested() else "eou", line)
                ui.partial(line)
                return "speech", line
    except AsrError as exc:
        finish(cfg)
        ui.error(str(exc))
        write_state(cfg, "error")
        log.error("asr failed: %s", exc)
        return "error", ""
    if stop_requested() and cancel_requested():
        captured("cancel")
        ui.partial("")
        finish(cfg)
        ui.idle()
        write_state(cfg, "idle")
        return "cancel", ""
    captured("stream_ended")
    return "ended", ""


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
        log.exception("turn failed")
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
