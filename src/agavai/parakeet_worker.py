"""Parakeet-Realtime-EOU-120M streaming worker.

Runs under the TTS venv (onnxruntime + numpy). The parent process stays
stdlib-only and speaks a length-prefixed PCM protocol on stdin:

    >I length, then that many s16le bytes
    length 0 resets the recognizer and asks for a reset acknowledgement

Stdout is JSON lines: ready, interim, eou, eob, reset, error.

The cache-aware encoder export steps 128 mel frames at a time (about 1.28 s
of audio). That is this ONNX file's step, not the model card's 80 ms lookahead.
"""

from __future__ import annotations

import json
import struct
import sys

import numpy as np
import onnxruntime as ort

SAMPLE_RATE = 16000
N_FFT = 512
WIN = 400
HOP = 160
N_MELS = 128
# center=True STFT: frames = samples/hop + 1, so 127 hops produce 128 frames.
CHUNK_SAMPLES = 127 * HOP
BLANK = 1026
EOU = 1024
EOB = 1025
MAX_SYMBOLS = 10
LOG_GUARD = np.float32(2**-24)


def emit(kind: str, text: str = "") -> None:
    sys.stdout.write(json.dumps({"kind": kind, "text": text}, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def read_exact(n: int) -> bytes | None:
    buf = b""
    while len(buf) < n:
        chunk = sys.stdin.buffer.read(n - len(buf))
        if not chunk:
            return None
        buf += chunk
    return buf


def hz_to_mel(frequencies: np.ndarray) -> np.ndarray:
    f_sp = 200.0 / 3
    min_log_hz = 1000.0
    min_log_mel = min_log_hz / f_sp
    logstep = np.log(6.4) / 27.0
    mels = frequencies / f_sp
    log_t = frequencies >= min_log_hz
    if np.any(log_t):
        mels = mels.copy()
        mels[log_t] = min_log_mel + np.log(frequencies[log_t] / min_log_hz) / logstep
    return mels


def mel_to_hz(mels: np.ndarray) -> np.ndarray:
    f_sp = 200.0 / 3
    min_log_hz = 1000.0
    min_log_mel = min_log_hz / f_sp
    logstep = np.log(6.4) / 27.0
    freqs = f_sp * mels
    log_t = mels >= min_log_mel
    freqs = np.where(log_t, min_log_hz * np.exp(logstep * (mels - min_log_mel)), freqs)
    return freqs


def mel_filterbank() -> np.ndarray:
    """Slaney mel matrix, matching NeMo's librosa filterbank. No feature norm."""
    n_freqs = N_FFT // 2 + 1
    fftfreqs = np.linspace(0, SAMPLE_RATE / 2, n_freqs)
    mel_f = mel_to_hz(np.linspace(hz_to_mel(np.array([0.0]))[0], hz_to_mel(np.array([SAMPLE_RATE / 2]))[0], N_MELS + 2))
    fdiff = np.diff(mel_f)
    ramps = mel_f[:, None] - fftfreqs[None, :]
    weights = np.zeros((N_MELS, n_freqs), dtype=np.float64)
    for i in range(N_MELS):
        lower = -ramps[i] / fdiff[i]
        upper = ramps[i + 2] / fdiff[i + 1]
        weights[i] = np.maximum(0, np.minimum(lower, upper))
    enorm = 2.0 / (mel_f[2 : N_MELS + 2] - mel_f[:N_MELS])
    weights *= enorm[:, None]
    return weights.astype(np.float32)


def hann_window() -> np.ndarray:
    # torch.hann_window(WIN, periodic=False), centered in the FFT.
    hann = 0.5 - 0.5 * np.cos(2 * np.pi * np.arange(WIN) / (WIN - 1))
    window = np.zeros(N_FFT, dtype=np.float32)
    left = (N_FFT - WIN) // 2
    window[left : left + WIN] = hann.astype(np.float32)
    return window


FB = mel_filterbank()
WINDOW = hann_window()


def log_mel(samples: np.ndarray) -> np.ndarray:
    """Raw log-mel, shape [128, frames]. The ONNX package is not per-feature normalized."""
    x = np.concatenate([samples[:1], samples[1:] - np.float32(0.97) * samples[:-1]]).astype(np.float32)
    x = np.pad(x, (N_FFT // 2, N_FFT // 2))
    n_frames = 1 + (x.shape[0] - N_FFT) // HOP
    frames = np.lib.stride_tricks.as_strided(
        x,
        shape=(n_frames, N_FFT),
        strides=(x.strides[0] * HOP, x.strides[0]),
    )
    spec = np.fft.rfft(frames * WINDOW, axis=1)
    power = (spec.real**2 + spec.imag**2).astype(np.float32)
    mel = power @ FB.T
    return np.log(mel + LOG_GUARD).astype(np.float32).T


def decode(ids: list[int], vocab: list[str]) -> str:
    parts = [vocab[i] for i in ids if 0 <= i < len(vocab)]
    return " ".join("".join(parts).replace("\u2581", " ").split())


class Stream:
    def __init__(self, model_dir: str, device: str) -> None:
        from pathlib import Path

        root = Path(model_dir)
        providers = ["CPUExecutionProvider"]
        if device == "cuda":
            providers = ["CUDAExecutionProvider", "CPUExecutionProvider"]
        opts = ort.SessionOptions()
        self.encoder = ort.InferenceSession(str(root / "streaming_encoder.fp16.onnx"), opts, providers=providers)
        self.decoder = ort.InferenceSession(str(root / "decoder_joint-model.int8.onnx"), opts, providers=providers)
        self.vocab = (root / "vocab.txt").read_text(encoding="utf-8").splitlines()
        self.reset()

    def reset(self) -> None:
        self.pre_cache = np.zeros((1, N_MELS, 16), np.float32)
        self.cache_lc = np.zeros((17, 1, 70, 512), np.float32)
        self.cache_lt = np.zeros((17, 1, 512, 8), np.float32)
        self.cache_len = np.zeros((1,), np.int32)
        self.h = np.zeros((1, 1, 640), np.float32)
        self.c = np.zeros((1, 1, 640), np.float32)
        self.last = BLANK
        self.hyp: list[int] = []

    def step(self, samples: np.ndarray) -> None:
        mel = log_mel(samples)
        frames = mel.shape[1]
        if frames < 128:
            pad = np.full((N_MELS, 128 - frames), np.log(LOG_GUARD), np.float32)
            mel = np.concatenate([mel, pad], axis=1)
            length = frames
        else:
            mel = mel[:, :128]
            length = 128
        feeds = {
            "audio_signal": mel[None, :, :].astype(np.float32),
            "audio_length": np.asarray([length], np.int32),
            "pre_cache": self.pre_cache,
            "cache_last_channel": self.cache_lc,
            "cache_last_time": self.cache_lt,
            "cache_last_channel_len": self.cache_len,
        }
        encoded, enc_len, self.pre_cache, self.cache_lc, self.cache_lt, self.cache_len = self.encoder.run(
            [
                "encoded_output",
                "encoded_length",
                "new_pre_cache",
                "new_cache_last_channel",
                "new_cache_last_time",
                "new_cache_last_channel_len",
            ],
            feeds,
        )
        steps = int(enc_len[0]) if enc_len is not None else encoded.shape[-1]
        for t in range(max(0, steps)):
            if self._decode_frame(encoded[:, :, t : t + 1]):
                return

    def _decode_frame(self, frame: np.ndarray) -> bool:
        """Greedy RNN-T for one encoder frame. True when the utterance ended."""
        for _ in range(MAX_SYMBOLS):
            logits, h2, c2 = self.decoder.run(
                ["outputs", "output_states_1", "output_states_2"],
                {
                    "encoder_outputs": frame,
                    "targets": np.asarray([[self.last]], np.int32),
                    "input_states_1": self.h,
                    "input_states_2": self.c,
                },
            )
            token = int(np.argmax(logits[0, 0, -1]))
            if token == BLANK:
                return False
            self.last = token
            self.h = h2
            self.c = c2
            if token == EOU:
                emit("eou", decode(self.hyp, self.vocab))
                self.reset()
                return True
            if token == EOB:
                emit("eob", decode(self.hyp, self.vocab))
                continue
            self.hyp.append(token)
            emit("interim", decode(self.hyp, self.vocab))
        return False


def main() -> None:
    model_dir = sys.argv[1]
    device = sys.argv[2] if len(sys.argv) > 2 else "cpu"
    stream = Stream(model_dir, device)
    emit("ready")
    pending = np.zeros((0,), np.float32)
    while True:
        header = read_exact(4)
        if header is None:
            break
        n = struct.unpack(">I", header)[0]
        if n == 0:
            if pending.size:
                padded = np.zeros((CHUNK_SAMPLES,), np.float32)
                take = min(pending.size, CHUNK_SAMPLES)
                padded[:take] = pending[:take]
                stream.step(padded)
                pending = np.zeros((0,), np.float32)
            stream.reset()
            emit("reset")
            continue
        payload = read_exact(n)
        if payload is None:
            break
        samples = np.frombuffer(payload, dtype="<i2").astype(np.float32) / np.float32(32768.0)
        pending = np.concatenate([pending, samples])
        while pending.size >= CHUNK_SAMPLES:
            stream.step(pending[:CHUNK_SAMPLES])
            pending = pending[CHUNK_SAMPLES:]


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        emit("error", str(exc))
        sys.exit(1)
