Automated tests live in `features/` and run with Behave only. See `AGENTS.md`.

```bash
PYTHONPATH=src behave
```

The frontend checks use NumPy and ONNX Runtime in the configured ASR venv.
Scenarios tagged `@asr_model` additionally replay a checked-in speech fixture
through the actual worker and require `scripts/download-asr.sh` first. Set
`AGAVAI_ASR_TEST_MODEL_DIR` to test assets in another directory. Cactus scenarios
tagged `@cactus_model` require `scripts/setup-cactus.sh` and
`AGAVAI_CACTUS_TEST_DIR` pointing at its destination. The Silero scenario tagged
`@vad_model` requires `scripts/download-vad.sh`; set `AGAVAI_VAD_TEST_MODEL` to
use a model file elsewhere. To omit native model replays, run
`PYTHONPATH=src behave --tags=-asr_model --tags=-cactus_model --tags=-vad_model`.

Microphone feedback scenarios replay isolated PCM into the parent capture
path without opening a live microphone. Orb animation checks use Qt's
`qmltestrunner` with an offscreen software renderer; on Omarchy it lives at
`/usr/lib/qt6/bin/qmltestrunner`.

`report/` holds the latest published eval report, not a test. `report.html`
opens in a browser and carries the data in `report.json`; both are copied from
a run under `evals/results/`. See [`docs/eval.md`](../docs/eval.md).
