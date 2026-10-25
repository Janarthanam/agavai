"""Checks run in the ASR venv so the Behave runner stays stdlib-only."""

import json
from pathlib import Path
import struct
import subprocess
import sys
import wave

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from agavai.parakeet_worker import FB, HOP, LOG_GUARD, MelStream, N_FFT, WINDOW, hz_to_mel, mel_to_hz


def check_frontend(lengths, packet_sizes):
    np.testing.assert_allclose(hz_to_mel(np.array([0.0, 1000.0])), [0.0, 999.985537], atol=1e-6)
    np.testing.assert_allclose(mel_to_hz(np.array([0.0, 1000.0])), [0.0, 1000.021816], atol=1e-6)
    for length in lengths:
        samples = np.random.default_rng(length).uniform(-0.4, 0.4, length).astype(np.float32)
        emphasized = samples.copy()
        emphasized[1:] -= np.float32(0.97) * samples[:-1]
        padded = np.pad(emphasized, (N_FFT // 2, N_FFT // 2))
        count = length // HOP
        windows = np.array([padded[i * HOP:i * HOP + N_FFT] for i in range(count)])
        if count:
            spec = np.fft.rfft(windows * WINDOW, axis=1)
            power = (spec.real**2 + spec.imag**2).astype(np.float32)
            expected = np.log(power @ FB.T + LOG_GUARD).astype(np.float32).T
        else:
            expected = np.empty((128, 0), np.float32)
        for packet in packet_sizes:
            frontend = MelStream()
            chunks = [frontend.feed(samples[i:i + packet]) for i in range(0, length, packet)]
            chunks.append(frontend.feed(np.empty(0, np.float32), final=True))
            actual = np.concatenate(chunks, axis=1)
            assert actual.shape == expected.shape, (length, packet, actual.shape, expected.shape)
            np.testing.assert_allclose(actual, expected, rtol=0, atol=2e-5)


def frame(command, uid, data=b""):
    payload = struct.pack(">cI", command, uid) + data
    return struct.pack(">I", len(payload)) + payload


def check_speech(model_dir, *, reset, silence):
    fixture = ROOT / "features" / "fixtures" / "asr-sentence.wav"
    with wave.open(str(fixture)) as wav:
        assert (wav.getframerate(), wav.getnchannels(), wav.getsampwidth()) == (16000, 1, 2)
        pcm = wav.readframes(wav.getnframes()) + bytes(2 * 16000 * 2)
    if silence:
        pcm = bytes(16000 * 2) + pcm
    expected = "please find the meeting notes from yesterday and open the document in my downloads folder"
    sizes = (3200,) if reset or silence else (160, 3200, 10174)
    for size in sizes:
        from agavai.asr import worker_settings
        from agavai.config import AsrConfig
        settings = worker_settings(AsrConfig(model_dir=Path(model_dir)))
        turns = []
        for uid in range(1, 3 if reset else 2):
            frames = b"".join(frame(b"A", uid, pcm[i:i + size]) for i in range(0, len(pcm), size))
            turns.append(frame(b"S", uid) + frames + frame(b"F", uid))
        result = subprocess.run(
            [sys.executable, str(ROOT / "src" / "agavai" / "asr_worker.py"), json.dumps(settings)],
            input=b"".join(turns), capture_output=True, timeout=45,
        )
        assert result.returncode == 0, result.stderr.decode() + result.stdout.decode()
        events = [json.loads(line) for line in result.stdout.splitlines()]
        utterances = [event["text"] for event in events if event["kind"] == "final"]
        assert utterances == [expected] * (2 if reset else 1), (size, utterances)
        assert sum(event["kind"] == "endpoint" for event in events) == (2 if reset else 1), events



def check_continuous(model_dir):
    """A recording keeps decoding after an end of utterance and times each one."""
    fixture = ROOT / "features" / "fixtures" / "asr-sentence.wav"
    with wave.open(str(fixture)) as wav:
        pcm = wav.readframes(wav.getnframes())
    sentence_ms = len(pcm) * 1000 // (2 * 16000)
    expected = "please find the meeting notes from yesterday and open the document in my downloads folder"
    for gap_ms, utterances in ((2000, [expected, expected]), (0, [f"{expected} {expected}"])):
        gap = bytes(2 * 16 * gap_ms)
        audio = pcm + gap + pcm + gap
        from agavai.asr import worker_settings
        from agavai.config import AsrConfig
        settings = worker_settings(AsrConfig(model_dir=Path(model_dir)))
        settings["continuous"] = True
        frames = b"".join(frame(b"A", 1, audio[i:i + 3200]) for i in range(0, len(audio), 3200))
        result = subprocess.run(
            [sys.executable, str(ROOT / "src" / "agavai" / "asr_worker.py"), json.dumps(settings)],
            input=frame(b"S", 1) + frames + frame(b"F", 1), capture_output=True, timeout=90,
        )
        assert result.returncode == 0, result.stderr.decode()
        events = [json.loads(line) for line in result.stdout.splitlines()]
        eous = [event for event in events if event["kind"] == "eou"]
        assert [event["text"] for event in eous] == utterances, (gap_ms, eous)
        assert [event["kind"] for event in events].count("final") == 1, events
        assert 0 <= eous[0]["start_ms"] < 1000, eous[0]
        if gap_ms:
            second = sentence_ms + gap_ms
            assert eous[0]["end_ms"] < eous[1]["start_ms"], eous
            assert second - 500 < eous[1]["start_ms"] < second + 1000, (second, eous[1])


def check_recording_capture():
    import tempfile
    from unittest.mock import patch

    from agavai.asr import open_stream
    from agavai.config import Config
    from agavai.meter import ParecSource
    from agavai.recording import Recorder

    fixture = ROOT / "features" / "fixtures" / "asr-sentence.wav"
    with wave.open(str(fixture)) as wav:
        sentence = wav.readframes(wav.getnframes())
    pcm = (sentence + bytes(64000)) * 2
    expected = "please find the meeting notes from yesterday and open the document in my downloads folder"
    with tempfile.TemporaryDirectory(prefix="agavai-recording-replay-") as directory:
        root = Path(directory)
        audio = root / "microphone.pcm"
        audio.write_bytes(pcm)
        cfg = Config()
        cfg.asr.backend = "whistle-cactus"
        cfg.asr.endpoint = "vad"
        cfg.asr.venv = root / "assistant-runtime-is-not-used-for-recording"
        cfg.recordings.dir = root / "Recordings"
        recorder = Recorder(cfg)
        # A real pipe, capture pump, model worker and encoder; only the microphone is replaced.
        with patch.object(ParecSource, "ARGV", ["cat", str(audio)]):
            stream = open_stream(cfg, continuous=True)
            try:
                for message in stream.record(recorder.audio, should_stop=lambda: False):
                    if message["kind"] == "asr_lost":
                        raise AssertionError("The recording lost its recognizer")
                    if message["kind"] == "eou":
                        recorder.add_line(message["text"], message["start_ms"], message["end_ms"])
            finally:
                stream.close()
        folder = recorder.finish()
        meta = json.loads((folder / "recording.json").read_text())
        assert cfg.asr.backend == "whistle-cactus" and cfg.asr.endpoint == "vad"
        assert meta["duration_ms"] == len(pcm) * 1000 // 32000, meta
        assert [line["live"] for line in meta["segments"]] == [expected, expected], meta
        assert meta["audio"] == "audio.opus" and (folder / "audio.opus").is_file(), meta
        assert not (folder / "audio.wav").exists()


if __name__ == "__main__":
    mode, model_dir = sys.argv[1:]
    if mode == "frontend":
        check_frontend([20320 * 3 + 37], [1, 79, 320, 20320])
    elif mode == "tails":
        check_frontend([0, 1, 159, 160, 255, 256, 257, 319, 320, 511, 512, 2561], [1, 83, 3200])
    elif mode == "continuous":
        check_continuous(model_dir)
    elif mode == "recording":
        check_recording_capture()
    else:
        check_speech(model_dir, reset=mode == "reset", silence=mode == "silence")
