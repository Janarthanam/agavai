#!/usr/bin/env python3
"""CPU-only Kokoro-82M synthesis. Run with the Agavai TTS venv, not system Python."""

from __future__ import annotations

import argparse
import json
import os
import socket
import sys
from pathlib import Path


def _load(model: str, voices: str):
    import numpy as np
    import soundfile as sf
    from kokoro_onnx import Kokoro

    try:
        kokoro = Kokoro(model, voices, providers=["CPUExecutionProvider"])
    except TypeError:
        kokoro = Kokoro(model, voices)
    return kokoro, np, sf


def _synth(kokoro, np, sf, text: str, voice: str, out: str) -> None:
    samples, sample_rate = kokoro.create(text, voice=voice)
    audio = np.asarray(samples)
    if audio.ndim > 1:
        audio = audio.reshape(-1)
    sf.write(out, audio, int(sample_rate))


def serve(model: str, voices: str, voice: str, sock_path: str, ack_path: str | None) -> int:
    kokoro, np, sf = _load(model, voices)
    if ack_path:
        try:
            _synth(kokoro, np, sf, "On it.", voice, ack_path)
        except Exception as exc:  # noqa: BLE001
            print(f"ack synth failed: {exc}", file=sys.stderr)
    path = Path(sock_path)
    if path.exists():
        path.unlink()
    path.parent.mkdir(parents=True, exist_ok=True)
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(sock_path)
    srv.listen(4)
    srv.settimeout(600)
    print("agavai-tts: ready", flush=True)
    while True:
        try:
            conn, _ = srv.accept()
        except TimeoutError:
            break
        with conn:
            raw = b""
            while not raw.endswith(b"\n"):
                chunk = conn.recv(4096)
                if not chunk:
                    break
                raw += chunk
            try:
                req = json.loads(raw.decode() or "{}")
            except json.JSONDecodeError:
                conn.sendall(b'{"ok":false,"error":"bad json"}\n')
                continue
            if req.get("cmd") == "ping":
                conn.sendall(b'{"ok":true,"ready":true}\n')
                continue
            text = str(req.get("text") or "").strip()
            out = str(req.get("out") or "")
            v = str(req.get("voice") or voice)
            if not text or not out:
                conn.sendall(b'{"ok":false,"error":"need text and out"}\n')
                continue
            try:
                _synth(kokoro, np, sf, text, v, out)
                conn.sendall(b'{"ok":true}\n')
            except Exception as exc:  # noqa: BLE001
                err = json.dumps({"ok": False, "error": str(exc)})
                conn.sendall((err + "\n").encode())
    return 0


def main() -> int:
    os.environ["CUDA_VISIBLE_DEVICES"] = ""
    os.environ["ORT_DISABLE_ALL_GPU"] = "1"
    parser = argparse.ArgumentParser(description="Synthesize speech with Kokoro-82M on CPU")
    parser.add_argument("--model", required=True)
    parser.add_argument("--voices", required=True)
    parser.add_argument("--voice", default="af_bella")
    parser.add_argument("--out")
    parser.add_argument("--serve", metavar="SOCKET", help="Keep the model warm on a Unix socket")
    parser.add_argument("--ack", metavar="WAV", help="Pre-render On it. after load")
    parser.add_argument("text", nargs="*")
    args = parser.parse_args()
    if args.serve:
        return serve(args.model, args.voices, args.voice, args.serve, args.ack)
    text = " ".join(args.text).strip()
    if not args.out or not text:
        print("need --out and text (or --serve SOCKET)", file=sys.stderr)
        return 2
    kokoro, np, sf = _load(args.model, args.voices)
    _synth(kokoro, np, sf, text, args.voice, args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
