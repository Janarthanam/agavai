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
endpoint = "vad"
mode = "streaming"
chunk_ms = 1000
finish_timeout_secs = 30
max_utterance_secs = 120
```

Whistle shows words while you speak. With `endpoint = "vad"`, the existing energy classifier observes the same 20 ms PCM frames as recognition. After at least 250 ms of speech, 900 ms of quiet requests final decoding and submits once. Configure it explicitly:

```toml
[vad]
enabled = true
backend = "energy"
silence_ms = 900
min_speech_ms = 250
max_record_ms = 120000
```

Shorter pauses keep the request open. Silence alone never submits; brief noise is discarded. Energy detection cannot understand whether a sentence is complete: a pause longer than the window can cut a sentence, and background sound can delay submission. Tune `silence_ms` and the open/close thresholds for the microphone. The streaming VAD policy currently accepts only the energy classifier; it rejects unsupported backends rather than silently substituting one. Parakeet retains native endpointing.

**Enter also finishes recognition and submits the final text; Escape discards it.** Select `endpoint = "manual"` to require Enter; the overlay then says so. `mode = "batch"` buffers the utterance, shows microphone feedback without partial words, and transcribes when Enter or the selected VAD policy ends input. Streaming committed words never trigger a request. `endpoint = "native"` is rejected for Whistle because its API has no turn-end event. VAD is an application policy, not a Whistle capability.

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

Needle is a specialized tool model. It receives locally selected tool schemas; it executes no tools itself. A valid supported call goes through the existing allowlist and confirmation flow. A simple result is acknowledged directly. No matching call, grounded-argument failure or runtime failure escalates if a larger role exists. Without one, the assistant explains that it could not handle the request and suggests a desktop request. Internal no-match diagnostics are logged with the backend and offered tool names; they are not spoken. Needle retains shared session history but does not perform Qwen's conversation-classification call; unrelated requests retain canvas/history until reset with “Agavai.”

Chat models can call `escalate_to_larger_model` when unable to handle a request. This control tool is never offered to Needle; Needle's no-match response triggers escalation in the coordinator. Empty output and exhausted tool steps also trigger escalation. The larger model receives the same history and completed tool results. It can answer general knowledge and conversational questions directly without tools; desktop actions still require an available tool and a successful result. Repeated identical calls after escalation reuse results from that turn instead of executing actions again. An answer or clarification from the small model completes the turn directly; the application does not infer universal correctness from a confidence score.

## Failure bounds and tests

Workers use a bounded response queue and input deadlines. Maximum audio duration, startup and finish deadlines are configurable. Overflow, worker crashes, microphone disconnection and decode timeouts never submit the last partial. Runtime downloads and telemetry are disabled during inference; install artifacts beforehand.

Run the standard BDD suite with optional native checks excluded:

```sh
PYTHONPATH=src .venv/bin/behave --tags=-asr_model --tags=-cactus_model
```

For native Cactus checks, set `AGAVAI_CACTUS_TEST_DIR` to the setup destination and run `features/cactus_worker.feature`. These replay recorded speech and generate schema-only tool calls without changing the desktop. Parakeet native checks retain the `@asr_model` tag.

Audio evaluation uses the same `SpeechBackend` adapters as the worker. VAD replay uses the same frame classifier and endpoint policy as live capture, and fingerprints its settings. Manual mode simulates Enter at clip end and is labeled manual; it cannot establish automatic endpoint quality. Batch mode has no first-word target. Replay timing includes chunk buffering and sequential inference compute, excluding live capture/IPC jitter. Fingerprints record selected model/runtime hashes and endpoint settings. These checks establish integration, not broad recognition quality or a faster-than-Parakeet performance claim.

## Add another backend

Implement `SpeechBackend` in `speech_backends.py` and add its factory to `SPEECH_BACKENDS`, or implement `BrainBackend` in `brain.py` and register it in `BRAIN_BACKENDS`. Reuse the existing worker transport when the runtime needs another Python environment. Keep native dependencies inside the worker. Extend backend-specific configuration/preflight alongside the adapter; shared capture, overlay and tool execution need no engine-specific branch. No dynamic plugin loader is required.

The speech protocol is `uint32 length` followed by a command byte (`S`, `A`, `F`, `C`), uint32 utterance ID and PCM bytes for audio commands. Output is JSONL with utterance ID. The brain worker receives framed JSON and returns normalized messages; llama uses loopback HTTP. See [the design](model-engines.md) for process boundaries.
