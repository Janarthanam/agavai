# Streaming ASR on the assistant listen path

Replace the silence timer and the Voxtype file on the assistant with Parakeet-Realtime-EOU-120M. Partials update the overlay. End of utterance or Enter commits. End of boundary and Escape do not.

## Surface

- [~] P0 voice Stream the recognizer into the listen loop and commit on end of utterance

### Log

- 2026-10-01 18:10 +0530 — Cursor session streaming-asr — in progress. The listen loop now feeds one capture into a venv Parakeet worker. Interim and end-of-boundary update the snapshot and do not call the model. End of utterance and Enter commit the hypothesis. Escape drops it. Device defaults to CPU and uses an NVIDIA GPU only when `[asr] device` is `gpu` and one is present. Weights: `scripts/download-asr.sh`. Not committed.
- Files: `src/agavai/asr.py`, `src/agavai/parakeet_worker.py`, `src/agavai/__main__.py`, `src/agavai/config.py`, `scripts/download-asr.sh`, `features/asr.feature`, `features/invocation.feature`, `features/steps/invocation_steps.py`, `features/config.feature`, `share/config.example.toml`, `plugin/Chat.qml`, `docs/flow.md`, `docs/audio.md`.
- 2026-10-01 18:25 +0530 — Cursor session streaming-asr — validation. `PYTHONPATH=src .venv/bin/behave features/asr.feature features/invocation.feature features/config.feature features/vad.feature features/tts.feature` passed (`XDG_RUNTIME_DIR` set for TTS). One silence chunk and one tone chunk through the downloaded ONNX both returned an empty end of utterance and did not crash. An empty end of utterance stays on the mic and does not speak. Weights installed by `scripts/download-asr.sh`. Not committed.
