# agavai architecture

Runtime behavior of a voice session — invoke, end of utterance, follow-up turns, cancel, and the overlay contract — is specified in [`flow.md`](flow.md). The audio stages are in [`audio.md`](audio.md). This file covers process split, model selection, and the tool allowlist.

Local voice control for Omarchy. Streaming ASR (Parakeet-Realtime-EOU-120M) is the ear. A **configurable on-device GGUF** (default: Qwen3-4B Instruct, ~2.5 GB) is the brain. Allowlisted tools are the hands. Head selection may call OpenRouter (Jev, below); everything else stays on the machine.

Two voice products run on this machine:

| Mode | Binding | Output |
|---|---|---|
| Dictation (Voxtype, not this repo) | F9 (push-to-talk) / Super+Ctrl+X | Types into the focused window |
| Assistant | Super+M (Super+Ctrl+M alias) | Tools, spoken reply, overlay results |

They share the microphone and should not run at the same time. Agavai does not enforce that, and it never starts, stops, or cancels a Voxtype recording.

---

## System diagram

```
                       Super+M
                          │
                          ▼
                    agavai invoke ─────────► overlay (janar.agavai)
                          │                  watches ui.json
                          ▼
           agavai listen (detached, one per session)
                          │
          ┌───────────────┴────────────────┐
          │  parec 16 kHz mono → Parakeet  │
          │  worker (streaming ASR)        │
          └───────────────┬────────────────┘
                          │ end of utterance or Enter
                          ▼
                    orchestrator
                (in the listen process)
                          │
          ┌───────────────┼────────────────┐
          ▼               ▼                ▼
   llama-server     tool dispatch      Kokoro/espeak
   :18766           allowlist          or notification
   [llm] model      omarchy/hyprctl
   from config.toml fd / grim / tesseract
```

Typed path skips the microphone: `agavai ask "open the browser"`.

---

## Processes

Keep **two** `llama-server` processes. They are different models and different jobs.

| Port | Unit / starter | Config | Job |
|---|---|---|---|
| **18765** | Voxtype `sanitize.sh` | Voxtype, not agavai | Dictation cleanup. Qwen2.5-1.5B. Do not reuse. |
| **18766** | `agavai-llm.service` → `agavai-llm` | `~/.config/agavai/config.toml` `[llm]` | Tool loop. Active on-device GGUF. |

`agavai-llm.service` is a user unit under `graphical-session.target`, in its **own cgroup**. A leftover llama-server inside the Voxtype cgroup hangs `systemctl --user restart voxtype`.

The orchestrator is **not** a daemon. It runs inside the listen process, one turn per committed line, until the session is dismissed; `ask` is one process per request. A turn is: committed text → POST `/v1/chat/completions` with `tools` → run tool results → speak.

MCP stdio (`agavai mcp`) exposes the same allowlist for other clients. The voice loop calls tools in-process so the 4B does not need a second MCP stack.

---

## On-device model (configurable)

The brain is **never hardcoded in the systemd unit**. `agavai-llm` asks Python for the resolved GGUF, then execs llama-server:

```
agavai dump-llm   →  MODEL, HOST, PORT, CTX, NGL, BIN, ALIAS, MODEL_ID
agavai-llm        →  llama-server --model $MODEL --jinja --n-gpu-layers $NGL …
```

### Resolution order (last wins)

1. Builtin catalog (`qwen3-4b-instruct` → the 2.5 GB Instruct Q4_K_M under `~/.local/share/agavai/models/`).
2. `[llm.models.<id>]` in config (path, ctx, GPU layers, download URL).
3. `[llm] model = "<id>"` selects from that catalog.
4. `[llm] model_path = "/path/to.gguf"` overrides the id’s path (escape hatch).
5. Environment `AGAVAI_MODEL` overrides the path for one process.
6. `AGAVAI_LLAMA_SERVER` overrides the llama-server binary.
7. `AGAVAI_CONFIG` overrides which TOML file is read.

After changing the active id, **restart** the runner so llama-server reloads weights:

```bash
agavai model list
agavai model set qwen3-4b-instruct
systemctl --user restart agavai-llm
agavai status
```

### Add another local GGUF

Put the file anywhere, then name it in config:

```toml
[llm]
model = "my-3b"

[llm.models.my-3b]
path = "~/.local/share/agavai/models/My-3B-Instruct-Q4_K_M.gguf"
description = "Smaller experimental tool model"
ctx_size = 4096
n_gpu_layers = 0
```

Requirements for a swap-in model:

- GGUF llama.cpp can load with `--jinja` (Qwen2.5/Qwen3 Instruct, Llama 3.x Instruct, Granite, etc.).
- Prefer **Instruct / non-thinking** checkpoints. Thinking models waste the voice budget on `<think>` blocks.
- Stay in **2–4 GB** Q4_K_M for this machine (RX 590 8 GB VRAM). Leave Vulkan for Voxtype Whisper; default `n_gpu_layers = 0` runs the assistant on RAM.
- Must emit OpenAI-style `tool_calls` or Qwen `<tool_call>` JSON. Heavily quantized (Q2 and below) usually breaks tool calling.

The on-device GGUF never changes because of the router (below). A future “think hard” id can point at a larger local GGUF; it is still selected the same way.

Download the default id:

```bash
scripts/download-model.sh
# or a named id from the catalog:
scripts/download-model.sh qwen3-4b-instruct
```

---

## Config file

Path: `~/.config/agavai/config.toml` (example: `share/config.example.toml`).

```toml
[llm]
model = "qwen3-4b-instruct"
host = "127.0.0.1"
port = 18766
# llama_bin = "/path/to/llama-server"
# model_path = "/override.gguf"    # optional; wins over model id
temperature = 0.2
max_tokens = 512
max_tool_rounds = 6
timeout_secs = 120

[llm.models.qwen3-4b-instruct]
path = "~/.local/share/agavai/models/Qwen3-4B-Instruct-2507-Q4_K_M.gguf"
ctx_size = 8192
n_gpu_layers = 0

[files]
roots = ["~/Documents", "~/Downloads", "~/Projects", "~/Work"]
max_results = 20

[tts]
prefer = "kokoro"   # kokoro | espeak | notify

[asr]
device = "cpu"      # gpu is used only when an NVIDIA GPU is present
```

`agavai status` prints the resolved `model_id` and `model_path`.

---

## Tool loop

1. System prompt: local Omarchy assistant, tools only, short spoken answers, no remote agents.
2. User text (transcript or `ask`).
3. **Router**: a small decision model picks tool **heads** for the utterance, and Qwen is given only those heads’ schemas (default Jev; keyword fallback offline). See below.
4. Up to `max_tool_rounds` (default 6):
   - POST llama-server `/v1/chat/completions` with OpenAI `tools` (the selected heads).
   - Parse `tool_calls`, or Qwen `<tool_call>{...}</tool_call>` if the template leaks.
   - Dispatch only names in the allowlist. Unknown names return an error string to the model.
5. Final assistant content → TTS / notification. ` thinking` blocks are stripped if a thinking model slips in.

### Router (head selection)

All ~30 schemas (~1.7k tokens) do not fit a 4B’s useful budget, so a small decision model picks the relevant pack(s) before each turn and Qwen sees only those (6–8 tools). Jev is **not** the voice model.

```
utterance → ToolRouter.select() → pack id(s) → pack schemas → Qwen tool loop
```

| Backend | What it is |
|---|---|
| `jev` (default) | TypeSafe **Jev 1.13** (`typesafe/jev-1.13`) on the OpenRouter **Decisions API**. One typed `choice` question (“which pack?”); `chat` means no tools. ~70–500 ms, no prose. |
| `keyword` | Token-overlap fallback. Used automatically if the key is missing, the request times out, or HTTP fails. |
| `local` | Stub with the same `select()` contract, for a future on-device decision model. |

Jev answers the pack question directly; the pack choice is the signal (`chat` → no tools). Packs stay the unit so a future local model answers the same question. The key lives in `OPENROUTER_API_KEY` (or gitignored `~/.config/agavai/secrets.toml`), never in git.

If Qwen emits a tool from a pack that was not injected, the orchestrator attaches that pack and calls Qwen once more. Tool results are clipped (~500 chars) before re-entering the context.

```toml
[router]
backend = "jev"      # jev | keyword | local
fallback = "keyword" # used when the key is missing or the call fails
timeout_secs = 2
max_tools = 8

[router.jev]
base_url = "https://openrouter.ai/api/alpha/decisions"
model = "typesafe/jev-1.13"
api_key_env = "OPENROUTER_API_KEY"
```

Allowlist (no generic shell):

| Tool | Backend |
|---|---|
| `list_windows` / `focus_window` / `to_workspace` / `workspace_step` / `close_window` / `toggle_fullscreen` | `hyprctl` |
| `launch` / `open_app` | Omarchy launchers and `gtk-launch` on desktop files |
| `list_themes` / `set_theme` | `omarchy theme` |
| `toggle_nightlight` / `stay_awake` / `dnd` | `omarchy toggle` |
| `set_volume` / `mute_microphone` | `omarchy audio` |
| `set_brightness` | `omarchy brightness display` |
| `battery_status` / `network_status` / `bluetooth` | Omarchy status CLIs |
| `lock_screen` | `omarchy-system-lock` |
| `screenshot` | `omarchy capture screenshot` (fullscreen/windows only) |
| `reminder` / `list_reminders` / `clear_reminders` | `omarchy reminder` |
| `send_notification` / `clock_now` | notification send / local time |
| `search_files` | `fd` under `[files] roots` |
| `play_url` | https only, `omarchy-launch-webapp` / browser |
| `screen_context` | focused window + `grim` + `tesseract` |
| `list_agents` | systemd units, plugin list, A2A cards — **does not call Grok** |

Pixel click / YOLO is out of v1. Screen understanding is structured (`hyprctl`) then OCR.

---

## Voice I/O

**In:** streaming ASR, specified in [audio.md](audio.md). One `parec` capture feeds the Parakeet worker; end of utterance or Enter commits the line. The same samples drive the orb's level meter, which never decides a turn.

**Overlay:** the Omarchy shell plugin `janar.agavai` (`plugin/`). It starts as an orb in the corner set by `[overlay] placement` (default bottom right) and expands in place for transcripts and results; the orb does not move. The listen process writes `$XDG_RUNTIME_DIR/agavai/ui.json` on every step (listening, partial and committed transcript, each tool start/result, assistant text), and QML `FileView` watches it. The launcher entry **Agavai** (`agavai app`) summons the same overlay; there is no second window. Layout and interaction are in [ui-design.md](ui-design.md).

Voxtype’s waveform OSD stays off so it does not stack with the overlay.

**Out:** Instant Siri-style earcon on listen, then a second cue while the LLM thinks. A background Kokoro process is started at listen/ask so the model is already loaded when the reply is ready. Final speech is Kokoro-82M on CPU (`kokoro-onnx` + onnxruntime CPU EP). eSpeak-ng is G2P and a robotic fallback. Whisper is never used for speech.

---

## Security

- llama-server binds `127.0.0.1`.
- No `--tools all` on llama-server (that would give the inference process a shell).
- No `bypassPermissions` coding agent in v1.
- File search is rooted. URLs must be `http(s)`. Launch targets are an enum.
- The QML overlay runs as an unsandboxed Omarchy plugin. The orchestrator is a CLI process.

---

## Source map

| Path | Role |
|---|---|
| `src/agavai/__main__.py` | CLI and listen session |
| `src/agavai/config.py` | TOML + builtin catalog + model id |
| `src/agavai/asr.py` | Microphone capture and streaming ASR client |
| `src/agavai/parakeet_worker.py` | Recognizer, run in the ASR venv |
| `src/agavai/orchestrator.py` | Tool loop |
| `src/agavai/llm.py` | llama-server HTTP client |
| `src/agavai/tools.py` | Allowlist |
| `src/agavai/ui.py` | `ui.json` snapshot |
| `src/agavai/mcp_server.py` | MCP stdio |
| `plugin/` | Overlay QML |
| `scripts/agavai-llm` | Exec llama-server from resolved config |
| `systemd/agavai-llm.service` | User unit |
| `share/mcp.json` | Optional MCP client snippet |

---

## Deploy (this machine)

Already installed. After a reboot, `voxtype` and `agavai-llm` should follow the graphical session.

```bash
systemctl --user status voxtype agavai-llm
agavai status
agavai ask "what is the current theme?"
```

Voice: Super+M, speak — Agavai sends when the recognizer emits end of utterance. Enter sends the current line.

Fresh machine:

```bash
scripts/download-model.sh
scripts/install.sh
systemctl --user enable --now agavai-llm
```
