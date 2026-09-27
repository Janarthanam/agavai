from __future__ import annotations

import argparse
import sys
import traceback

from oma_voice.a2a import write_card
from oma_voice.config import dump_llm_env, load_config, set_model_id
from oma_voice.feedback import finish, hide_listen, prepare_listen
from oma_voice.llm import health
from oma_voice.mcp_server import serve_stdio
from oma_voice.orchestrator import run_turn
from oma_voice.state import read_state, write_state
from oma_voice.tts import speak
from oma_voice.ui import ChatUi
from oma_voice.voxtype import record_cancel, record_start, record_stop, wait_for_prompt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="oma-voice", description="Local Omarchy voice assistant")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("toggle", help="Start or stop a Voxtype-backed request")
    sub.add_parser("start", help="Start listening")
    sub.add_parser("stop", help="Stop listening and run the agent")
    sub.add_parser("cancel", help="Abort listening")
    ask = sub.add_parser("ask", help="Run a typed request (no microphone)")
    ask.add_argument("text", nargs="+")
    sub.add_parser("status")
    sub.add_parser("mcp", help="Run the MCP stdio server")
    sub.add_parser("dump-llm", help="Print llama-server env for the launcher script")
    app_cmd = sub.add_parser("app", help="Open the Agavai window (app launcher)")
    app_cmd.description = "Open the Agavai window"
    model = sub.add_parser("model", help="Show, list, or select the on-device GGUF")
    model.add_argument("action", nargs="?", default="show", choices=["show", "list", "set"])
    model.add_argument("name", nargs="?", help="Model id for 'set'")
    args = parser.parse_args(argv)
    cfg = load_config()
    cfg.runtime_dir.mkdir(parents=True, exist_ok=True)
    write_card(cfg)

    if args.cmd == "mcp":
        serve_stdio()
        return 0
    if args.cmd == "dump-llm":
        sys.stdout.write(dump_llm_env(cfg))
        return 0
    if args.cmd == "app":
        from oma_voice.app import run as run_app

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
    if args.cmd == "ask":
        text = " ".join(args.text)
        ui = ChatUi(cfg)
        write_state(cfg, "thinking")
        reply = run_turn(text, cfg, ui)
        write_state(cfg, "speaking")
        speak(reply, cfg)
        ui.idle()
        write_state(cfg, "idle")
        print(reply)
        return 0
    if args.cmd == "cancel":
        record_cancel()
        finish(cfg)
        ChatUi(cfg).idle()
        write_state(cfg, "idle")
        return 0
    if args.cmd == "start":
        return _start(cfg)
    if args.cmd == "stop":
        return _stop(cfg)
    if args.cmd == "toggle":
        state = read_state(cfg)
        if state == "listening":
            return _stop(cfg)
        if state in {"transcribing", "thinking", "speaking"}:
            record_cancel()
            finish(cfg)
            ChatUi(cfg).idle()
            write_state(cfg, "idle")
            return 0
        return _start(cfg)
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
            print("usage: oma-voice model set <id>", file=sys.stderr)
            return 2
        try:
            cfg = set_model_id(name)
        except ValueError as exc:
            print(exc, file=sys.stderr)
            return 1
        print(f"model_id={cfg.llm.model_id}")
        print(f"model_path={cfg.llm.model_path}")
        print("restart the runner: systemctl --user restart oma-voice-llm")
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


def _start(cfg) -> int:
    ui = ChatUi(cfg)
    try:
        prepare_listen(cfg)
        ui.listening()
        record_start(cfg)
    except Exception as exc:
        finish(cfg)
        ui.error(str(exc))
        write_state(cfg, "error")
        print(exc, file=sys.stderr)
        return 1
    write_state(cfg, "listening")
    return 0


def _stop(cfg) -> int:
    ui = ChatUi(cfg)
    try:
        record_stop()
    except Exception as exc:
        finish(cfg)
        ui.error(str(exc))
        write_state(cfg, "error")
        print(exc, file=sys.stderr)
        return 1
    hide_listen(cfg)
    write_state(cfg, "transcribing")
    ui.transcribing()
    text = wait_for_prompt(cfg.prompt_file)
    if not text:
        finish(cfg)
        ui.error("I did not hear anything.")
        ui.idle()
        write_state(cfg, "idle")
        speak("I did not hear anything.", cfg)
        return 1
    write_state(cfg, "thinking")
    try:
        reply = run_turn(text, cfg, ui)
    except Exception:
        traceback.print_exc()
        reply = "The local agent hit an error."
        ui.error(reply)
    write_state(cfg, "speaking")
    finish(cfg)
    speak(reply, cfg)
    ui.idle()
    write_state(cfg, "idle")
    print(reply)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
