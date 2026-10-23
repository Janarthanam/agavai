# Select speech and brain engines

Speech recognition and the local brain are configured independently in `~/.config/agavai/config.toml`. Restart the listening session after editing. Defaults remain Parakeet/ONNX and the existing `[llm]` Qwen/llama-server configuration.

## Whistle speech recognition

Run `scripts/setup-cactus.sh` to install pinned CPU models and the Cactus runtime in `~/.local/share/agavai/cactus`. It does not edit config or restart services. Override the destination with `AGAVAI_CACTUS_DIR` if needed. Then replace your `[asr]` table:

```toml
[asr]
backend = "whistle-cactus"
model_path = "~/.local/share/agavai/cactus/whistle.cact"
runtime_library = "~/.local/share/agavai/cactus/libneedle.so"
venv = "~/.local/share/agavai/cactus/venv"
device = "cpu"
endpoint = "manual"
mode = "streaming"
chunk_ms = 1000
finish_timeout_secs = 30
max_utterance_secs = 120
```

Whistle shows words while you speak. **Enter finishes recognition and submits the final text; Escape discards it.** `mode = "batch"` buffers the utterance, shows microphone feedback without partial words, and transcribes on Enter. Streaming committed words never trigger a request. Automatic silence endpointing for Whistle is deferred; `endpoint = "native"` is rejected because its API has no turn-end event.

Parakeet uses `backend = "parakeet-onnx"`, `endpoint = "native"`, `mode = "streaming"`, `model_dir` and `venv` from the [example config](../share/config.example.toml). It retains native EOU submission and Enter. CUDA must actually be installed when selecting GPU; missing support fails explicitly.

## Small brain, then larger brain

With no role tables, `[llm]` is the small local brain. Add a larger role only when you want escalation. To try Needle before Qwen:

```toml
[brain.small]
backend = "needle-cactus"
model = "needle3"
model_path = "~/.local/share/agavai/cactus/needle3.cact"
runtime_library = "~/.local/share/agavai/cactus/libneedle.so"
venv = "~/.local/share/agavai/cactus/venv"
timeout_secs = 10
max_tokens = 512
max_tool_rounds = 6

[brain.large]
backend = "llama-server"
model = "qwen3-4b-instruct"
model_path = "~/.local/share/agavai/models/Qwen3-4B-Instruct-2507-Q4_K_M.gguf"
host = "127.0.0.1"
port = 18766
alias = "agavai"
# llama_bin = "/path/to/llama-server"
```

The normal `agavai-llm` service launches the first configured llama tier: small if it uses llama, otherwise large. Restart that service after changing its model. Needle workers are launched by the session and need no service. A Needle-only configuration works without a running llama server.

For a small Qwen and a larger GGUF, use `backend = "llama-server"` for both roles, distinct host/port pairs and explicit model paths. The service launches the small role; run `scripts/agavai-llm large` separately for the larger role. Each role accepts `llama_bin`, `ctx_size`, `n_gpu_layers`, `temperature`, `max_tokens`, `max_tool_rounds` and `timeout_secs`. `agavai dump-llm --role small|large` shows its launcher settings. The old `agavai model set` command edits only the legacy `[llm]` catalog selection; explicit roles are selected in TOML.

Needle is a specialized tool model. It receives locally selected tool schemas; it executes no tools itself. A valid supported call goes through the existing allowlist and confirmation flow. A simple result is acknowledged directly. No matching call, grounded-argument failure or runtime failure escalates if a larger role exists. Without one, the failure is shown. Needle retains shared session history but does not perform Qwen's conversation-classification call; unrelated requests retain canvas/history until reset with “Agavai.”

Chat models can call `escalate_to_larger_model` when unable to handle a request. Empty output and exhausted tool steps also trigger escalation. The larger model receives the same history and completed tool results. Repeated identical calls after escalation reuse results from that turn instead of executing actions again. An answer or clarification from the small model completes the turn directly; the application does not infer universal correctness from a confidence score.

## Failure bounds and tests

Workers use a bounded response queue and input deadlines. Maximum audio duration, startup and finish deadlines are configurable. Overflow, worker crashes, microphone disconnection and decode timeouts never submit the last partial. Runtime downloads and telemetry are disabled during inference; install artifacts beforehand.

Run the standard BDD suite with optional native checks excluded:

```sh
PYTHONPATH=src .venv/bin/behave --tags=-asr_model --tags=-cactus_model
```

For native Cactus checks, set `AGAVAI_CACTUS_TEST_DIR` to the setup destination and run `features/cactus_worker.feature`. These replay recorded speech and generate schema-only tool calls without changing the desktop. Parakeet native checks retain the `@asr_model` tag.

Audio evaluation uses the same `SpeechBackend` adapters as the worker. Manual mode simulates Enter at clip end and is labeled manual; it cannot establish automatic endpoint quality. Batch mode has no first-word target. Replay timing includes chunk buffering and sequential inference compute, excluding live capture/IPC jitter. Fingerprints record selected model/runtime hashes and endpoint settings. These checks establish integration, not broad recognition quality or a faster-than-Parakeet performance claim.

## Add another backend

Implement `SpeechBackend` in `speech_backends.py` and add its factory to `SPEECH_BACKENDS`, or implement `BrainBackend` in `brain.py` and register it in `BRAIN_BACKENDS`. Reuse the existing worker transport when the runtime needs another Python environment. Keep native dependencies inside the worker. Extend backend-specific configuration/preflight alongside the adapter; shared capture, overlay and tool execution need no engine-specific branch. No dynamic plugin loader is required.

The speech protocol is `uint32 length` followed by a command byte (`S`, `A`, `F`, `C`), uint32 utterance ID and PCM bytes for audio commands. Output is JSONL with utterance ID. The brain worker receives framed JSON and returns normalized messages; llama uses loopback HTTP. See [the design](model-engines.md) for process boundaries.
