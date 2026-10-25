"""Parakeet-Realtime-EOU-120M adapter implementation (NumPy + ONNX Runtime).

In continuous mode (recordings), an end of utterance does not end the
stream. The next utterance is decoded from the same audio, so nothing
between utterances is dropped. Each eou also carries start_ms, the time of
its first word, and end_ms, both from the start of the stream. A flush
emits an unfinished last utterance as a final eou.

The cache-aware encoder steps 16 new mel frames (160 ms) with nine frames
of pre-encode context. PCM and mel overlap survive transport boundaries.
The shared asr_worker.py owns transport and utterance lifecycle.
"""

from __future__ import annotations

import json
import sys

import numpy as np
import onnxruntime as ort

ort.set_default_logger_severity(3)

SAMPLE_RATE = 16000
N_FFT = 512
WIN = 400
HOP = 160
N_MELS = 128
CHUNK_FRAMES = 16
PRE_ENCODE_FRAMES = 9
BLANK = 1026
EOU = 1024
EOB = 1025
MAX_SYMBOLS = 10
LOG_GUARD = np.float32(2**-24)


def emit(kind: str, text: str = "", **timing: int) -> None:
    sys.stdout.write(json.dumps({"kind": kind, "text": text, **timing}, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def hz_to_mel(frequencies: np.ndarray) -> np.ndarray:
    return 2595.0 * np.log10(1.0 + frequencies / 700.0)


def mel_to_hz(mels: np.ndarray) -> np.ndarray:
    return 700.0 * (10.0 ** (mels / 2595.0) - 1.0)


def mel_filterbank() -> np.ndarray:
    """HTK mel scale with area normalization, matching the EOU reference frontend."""
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


def log_mel(frames: np.ndarray) -> np.ndarray:
    """Raw log-mel from complete FFT windows; no per-feature normalization."""
    spec = np.fft.rfft(frames * WINDOW, axis=1)
    power = (spec.real**2 + spec.imag**2).astype(np.float32)
    mel = power @ FB.T
    return np.log(mel + LOG_GUARD).astype(np.float32).T


class MelStream:
    def __init__(self) -> None:
        self.pending = np.zeros(N_FFT // 2, np.float32)
        self.previous: np.float32 | None = None
        self.samples = 0
        self.frames = 0

    def feed(self, samples: np.ndarray, *, final: bool = False) -> np.ndarray:
        if samples.size:
            emphasized = samples.copy()
            emphasized[1:] -= np.float32(0.97) * samples[:-1]
            if self.previous is not None:
                emphasized[0] -= np.float32(0.97) * self.previous
            self.previous = samples[-1]
            self.samples += samples.size
            self.pending = np.concatenate([self.pending, emphasized])
        if final:
            self.pending = np.concatenate([self.pending, np.zeros(N_FFT // 2, np.float32)])
        count = max(0, 1 + (self.pending.size - N_FFT) // HOP)
        if final:
            count = min(count, self.samples // HOP - self.frames)
        if not count:
            return np.empty((N_MELS, 0), np.float32)
        windows = np.lib.stride_tricks.sliding_window_view(self.pending, N_FFT)[::HOP][:count]
        mel = log_mel(windows)
        self.pending = self.pending[count * HOP:]
        self.frames += count
        return mel


def decode(ids: list[int], vocab: list[str]) -> str:
    parts = [vocab[i] for i in ids if 0 <= i < len(vocab)]
    return " ".join("".join(parts).replace("\u2581", " ").split())


class Stream:
    def __init__(self, model_dir: str, device: str, *, continuous: bool = False, on_event=None) -> None:
        from pathlib import Path

        self.on_event = on_event or emit
        root = Path(model_dir)
        providers = ["CPUExecutionProvider"]
        if device == "cuda":
            if "CUDAExecutionProvider" not in ort.get_available_providers():
                raise RuntimeError("ONNX CUDA provider is unavailable. Install it or select CPU explicitly.")
            providers = ["CUDAExecutionProvider", "CPUExecutionProvider"]
        opts = ort.SessionOptions()
        # Tiny streaming steps fall behind real time with a pool spanning every core.
        opts.intra_op_num_threads = 1
        self.encoder = ort.InferenceSession(str(root / "encoder.onnx"), opts, providers=providers)
        self.decoder = ort.InferenceSession(str(root / "decoder_joint.onnx"), opts, providers=providers)
        self.vocab = (root / "vocab.txt").read_text(encoding="utf-8").splitlines()
        self.continuous = continuous
        self.reset()

    def reset(self) -> None:
        self.frontend = MelStream()
        self.pending_mel = np.empty((N_MELS, 0), np.float32)
        self.pre_cache = np.zeros((N_MELS, PRE_ENCODE_FRAMES), np.float32)
        self.ended = False
        self.cache_lc = np.zeros((17, 1, 70, 512), np.float32)
        self.cache_lt = np.zeros((17, 1, 512, 8), np.float32)
        self.cache_len = np.zeros((1,), np.int64)
        self.h = np.zeros((1, 1, 640), np.float32)
        self.c = np.zeros((1, 1, 640), np.float32)
        self.last = BLANK
        self.hyp: list[int] = []
        self.encoded_ms = 0
        self.frame_ms = 0
        self.first_ms: int | None = None

    def feed(self, samples: np.ndarray, *, final: bool = False) -> None:
        if self.ended:
            return
        mel = self.frontend.feed(samples, final=final)
        self.pending_mel = np.concatenate([self.pending_mel, mel], axis=1)
        while self.pending_mel.shape[1] >= CHUNK_FRAMES:
            chunk = self.pending_mel[:, :CHUNK_FRAMES]
            self.pending_mel = self.pending_mel[:, CHUNK_FRAMES:]
            if self._encode(chunk):
                self.ended = True
                return
        if final and self.pending_mel.shape[1]:
            # Only an explicit flush pads the final short chunk, never a live boundary.
            chunk = np.pad(
                self.pending_mel,
                ((0, 0), (0, CHUNK_FRAMES - self.pending_mel.shape[1])),
                constant_values=np.log(LOG_GUARD),
            )
            self.ended = self._encode(chunk)
            self.pending_mel = np.empty((N_MELS, 0), np.float32)

    def _encode(self, mel: np.ndarray) -> bool:
        features = np.concatenate([self.pre_cache, mel], axis=1)
        self.pre_cache = features[:, -PRE_ENCODE_FRAMES:]
        feeds = {
            "audio_signal": features[None, :, :],
            "length": np.asarray([features.shape[1]], np.int64),
            "cache_last_channel": self.cache_lc,
            "cache_last_time": self.cache_lt,
            "cache_last_channel_len": self.cache_len,
        }
        encoded, enc_len, self.cache_lc, self.cache_lt, self.cache_len = self.encoder.run(
            [
                "outputs",
                "encoded_lengths",
                "new_cache_last_channel",
                "new_cache_last_time",
                "new_cache_last_channel_len",
            ],
            feeds,
        )
        steps = int(enc_len[0])
        chunk_ms = mel.shape[1] * HOP * 1000 // SAMPLE_RATE
        for t in range(steps):
            self.frame_ms = self.encoded_ms + t * chunk_ms // max(steps, 1)
            if self._decode_frame(encoded[:, :, t : t + 1]):
                return True
        self.encoded_ms += chunk_ms
        return False

    def _decode_frame(self, frame: np.ndarray) -> bool:
        """Greedy RNN-T for one encoder frame. True when the utterance ended."""
        for _ in range(MAX_SYMBOLS):
            logits, h2, c2 = self.decoder.run(
                ["outputs", "output_states_1", "output_states_2"],
                {
                    "encoder_outputs": frame,
                    "targets": np.asarray([[self.last]], np.int32),
                    "target_length": np.asarray([1], np.int32),
                    "input_states_1": self.h,
                    "input_states_2": self.c,
                },
            )
            token = int(np.argmax(logits[0, 0, -1]))
            if token == BLANK:
                return False
            if token == EOU:
                text = decode(self.hyp, self.vocab)
                # Silence must not close capture and discard the beginning of speech.
                if not text:
                    return False
                if self.continuous:
                    self.finish_utterance()
                    return False
                self.on_event("eou", text)
                return True
            self.last = token
            self.h = h2
            self.c = c2
            if token == EOB:
                self.on_event("eob", decode(self.hyp, self.vocab))
                continue
            if not self.hyp:
                self.first_ms = self.frame_ms
            self.hyp.append(token)
            self.on_event("interim", decode(self.hyp, self.vocab))
        return False

    def finish_utterance(self) -> None:
        """Emit the current utterance with its timing and decode the next one from a fresh predictor."""
        text = decode(self.hyp, self.vocab)
        if text:
            self.on_event("eou", text, start_ms=self.first_ms or 0, end_ms=self.frame_ms)
        self.hyp = []
        self.first_ms = None
        self.last = BLANK
        self.h = np.zeros((1, 1, 640), np.float32)
        self.c = np.zeros((1, 1, 640), np.float32)
