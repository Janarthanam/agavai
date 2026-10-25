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
from agavai.config import dump_llm_env, load_config, set_model_id
from agavai.feedback import finish
from agavai.llm import health
from agavai.mcp_server import serve_stdio
from agavai.harness import Harness
from agavai.setup import ROUTERS, SPEECH
from agavai.state import read_state, write_state
from agavai.tts import cue_think, speak
from agavai.ui import ChatUi, cancel_ui
from agavai.harness.session import _cancel_path, _correct_cmd, _signal_listener, listen_session, request_recording

# `python -m agavai` runs this file as "__main__", which is outside the agavai
# logger that journal.setup configures.
log = logging.getLogger("agavai.__main__")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="agavai", description="Local Omarchy voice assistant")
    sub = parser.add_subparsers(dest="cmd", required=True)
    listen = sub.add_parser("listen", help="Listen and submit when the utterance ends")
    listen.add_argument("--record", action="store_true", help="Record instead; the microphone closes when the recording stops")
    record = sub.add_parser("record", help="Start or stop a recording, or pause, resume, or mark it")
    record.add_argument("action", nargs="?", default="toggle", choices=["toggle", "stop", "pause", "resume", "mark"])
    saved = sub.add_parser("recording", help="Change a saved recording")
    saved_cmd = saved.add_subparsers(dest="recording_cmd", required=True)
    corrected = saved_cmd.add_parser("correct", help="Correct one line; the heard words are kept")
    corrected.add_argument("folder")
    corrected.add_argument("line", type=int)
    corrected.add_argument("text")
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
    setup = sub.add_parser("setup", help="Choose, download and configure the speech and brain models")
    setup.add_argument("--speech", choices=SPEECH)
    setup.add_argument("--small", metavar="needle|GGUF-ID", help="the first model to handle each request")
    setup.add_argument("--large", metavar="none|GGUF-ID", help="the model that takes over when the small one cannot")
    setup.add_argument("--router", choices=ROUTERS)
    setup.add_argument("--yes", action="store_true", help="apply without asking")
    setup.add_argument("--dry-run", action="store_true", help="show the plan and change nothing")
    download = sub.add_parser("download", help="List the models, or download the named ones")
    download.add_argument("ids", nargs="*", metavar="ID")
    sub.add_parser("explain", help="Explain what happens to a request with the current configuration")
    args = parser.parse_args(argv)
    # The hotkey and the detached listener have no terminal, so a bad config
    # must reach the journal before the configured level is known.
    journal.setup("info")
    if args.cmd == "services":
        return _services_cmd(args.action)
    if args.cmd in {"setup", "download", "explain"}:
        return _setup_cmd(args)
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
        reply = Harness(cfg, ui).run_turn(text)
        if ui.cancelled():
            write_state(cfg, "idle")
            return 0
        write_state(cfg, "speaking")
        ui.speech(speak(reply, cfg))
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
    if args.cmd == "recording":
        return _correct_cmd(cfg, Path(args.folder), args.line, args.text)
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


def _setup_cmd(args) -> int:
    from agavai import setup

    try:
        if args.cmd == "setup":
            choices = {"speech": args.speech, "small": args.small, "large": args.large, "router": args.router}
            return setup.run_setup(choices, yes=args.yes, dry_run=args.dry_run, interactive=sys.stdin.isatty())
        cfg = load_config()
        if args.cmd == "explain":
            print("\n".join(setup.walkthrough(cfg)))
        elif not args.ids:
            print("\n".join(setup.download_list(cfg)))
        else:
            unknown = [mid for mid in args.ids if mid not in setup.downloads(cfg)]
            if unknown:
                raise setup.SetupError(f"unknown model {', '.join(unknown)}; run agavai download to list them")
            for command in setup.run_downloads(cfg, args.ids):
                print(f"ran scripts/{command}")
        return 0
    except (setup.SetupError, ValueError) as exc:
        print(f"agavai {args.cmd}: {exc}", file=sys.stderr)
        return 1


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
        from agavai.services import apply_config_change
        print("\n".join(apply_config_change()))
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


if __name__ == "__main__":
    raise SystemExit(main())
