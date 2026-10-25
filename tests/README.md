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

The opt-in `@brain_comparison` BDD experiment runs real Qwen and Needle through
the coordinator against the same simulated desktop cases. It compares Qwen with
keyword-routed or all tools, keyword-routed Needle with Qwen/all fallback, and
Needle/all with the same fallback. It records model quality as data; a passing scenario establishes
valid recorded runs and no outbound connections, not perfect model accuracy.
Without `AGAVAI_BRAIN_COMPARISON_OUT` these scenarios skip. With the installed
local Qwen server running, use:

```bash
PYTHONPATH=src AGAVAI_CONFIG="$PWD/share/config.example.toml" \
  AGAVAI_CACTUS_TEST_DIR="$PWD/.venv/cactus" \
  AGAVAI_BRAIN_COMPARISON_OUT="$PWD/evals/results/brain-comparison" \
  .venv/bin/behave features/brain_comparison.feature --no-capture
```

Use a fresh output directory within the repository to preserve prior runs. Each
profile writes a JSONL trace and a JSON summary with model/runtime fingerprints,
outcome counts, median turn duration and Qwen usage. Temperature is zero, seed is
42 and prompt caching is enabled for Qwen, as in normal use. This is an
exploratory comparison, not a repeatable scored eval: cache reuse can change
outputs, and each profile runs once in the listed order. Timings exclude speech
recognition and playback; Needle process/model warm-up remains part of its first turn.


Harness E2E scenarios in features/harness.feature use a local scripted HTTP service,
real recording files, context and tool dispatch, with scripted OS/ASR boundaries.
They cover source grounding and limits, revisions, corrections, input hold, task
changes, compaction, unknown effects, cancellation and recording during inference.
These establish harness contracts; model quality remains separate evaluation evidence.
