#!/usr/bin/env python3
"""CPU-only Kokoro-82M synthesis. Run with the Agavai TTS venv, not system Python."""

from __future__ import annotations

import argparse
import os
import sys


def main() -> int:
    os.environ["CUDA_VISIBLE_DEVICES"] = ""
    os.environ["ORT_DISABLE_ALL_GPU"] = "1"
    parser = argparse.ArgumentParser(description="Synthesize speech with Kokoro-82M on CPU")
    parser.add_argument("--model", required=True)
    parser.add_argument("--voices", required=True)
    parser.add_argument("--voice", default="af_bella")
    parser.add_argument("--out", required=True)
    parser.add_argument("text", nargs="+")
    args = parser.parse_args()
    text = " ".join(args.text).strip()
    if not text:
        print("empty text", file=sys.stderr)
        return 2

    import numpy as np
    import soundfile as sf
    from kokoro_onnx import Kokoro

    kwargs = {"providers": ["CPUExecutionProvider"]}
    try:
        kokoro = Kokoro(args.model, args.voices, **kwargs)
    except TypeError:
        kokoro = Kokoro(args.model, args.voices)

    samples, sample_rate = kokoro.create(text, voice=args.voice)
    audio = np.asarray(samples)
    if audio.ndim > 1:
        audio = audio.reshape(-1)
    sf.write(args.out, audio, int(sample_rate))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
