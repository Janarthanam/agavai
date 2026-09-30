# agavai architecture

Local voice control for Omarchy. Voxtype is the microphone. A **configurable on-device GGUF** (default: Qwen3-4B Instruct, ~2.5 GB) is the brain. Allowlisted tools are the hands. Nothing in v1 leaves the machine.

Two voice products share one Voxtype daemon:

| Mode | Binding | Output |
|---|---|---|
| Dictation | F9 (push-to-talk) / Super+Ctrl+X | Types into the focused window |
| Assistant | Super+Ctrl+M (toggle) | Tools + spoken/notification reply |

They must not run at the same time. They share the mic and the Voxtype state machine.

---

## System diagram

```
                    Super+Ctrl+M
                          │
                          ▼
                   agavai toggle
                          │
          ┌───────────────┴────────────────┐
          │  voxtype record start --file=  │
          │  $XDG_RUNTIME_DIR/agavai/   │
          │  prompt.txt                    │
          └───────────────┬────────────────┘
                          │ WAV (local Whisper)
                          ▼
                    Voxtype daemon
                    (systemd --user voxtype)
                          │
                          ▼
                    transcript file
                          │
                          ▼
                    orchestrator
                    (agavai, one shot)
                          │
          ┌───────────────┼────────────────┐
          ▼               ▼                ▼
   llama-server     tool dispatch      Piper/espeak
   :18766           allowlist          or notification
   [llm] model      omarchy/hyprctl
   from config.toml fd / grim / tesseract
```

Typed path skips Voxtype: `agavai ask "open the browser"`.

---

## Processes

Keep **two** `llama-server` processes. They are different models and different jobs.

| Port | Unit / starter | Config | Job |
|---|---|---|---|
| **18765** | Voxtype `sanitize.sh` | Voxtype, not agavai | Dictation cleanup. Qwen2.5-1.5B. Do not reuse. |
| **18766** | `agavai-llm.service` → `agavai-llm` | `~/.config/agavai/config.toml` `[llm]` | Tool loop. Active on-device GGUF. |

`agavai-llm.service` is a user unit under `graphical-session.target`, in its **own cgroup**. A leftover llama-server inside the Voxtype cgroup hangs `systemctl --user restart voxtype`.

The orchestrator is **not** a daemon. Each Super+Ctrl+M stop (or `ask`) is one process: read transcript → POST `/v1/chat/completions` with `tools` → run tool results → speak.

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
~/Projects/agavai/scripts/download-model.sh
# or a named id from the catalog:
~/Projects/agavai/scripts/download-model.sh qwen3-4b-instruct
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
prefer = "espeak"   # piper | espeak | notify
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

**In:** Super+Ctrl+M (toggle). First press unmutes the default mic if it was muted (same idea as F9 `ptt.sh`) and opens the **bottom voice overlay** (`janar.agavai`), then starts a blocking VAD session: a parallel `parec` capture meters the mic (live `level_db`/`vad_state` in `ui.json`) and after **900 ms of silence** (`[vad] silence_ms`) the turn runs automatically — no second press. Second press force-stops and runs the turn now; during `transcribing`/`thinking` a press within 2 s of the phase change is a no-op (grace window). Meter failure falls back to the old manual mode (`vad_state: "manual"`); `[vad] enabled = false` restores push-to-toggle. Opt-in `backend = "silero"` replaces the energy gate with the pinned Silero VAD v5.1.2 model (`scripts/download-vad.sh`; missing model/runtime → energy).

**Chat overlay:** a keep-loaded Omarchy overlay. Listening is a borderless orb at the bottom center of the active monitor; results grow upward on that same surface. The orchestrator writes `$XDG_RUNTIME_DIR/agavai/ui.json` on every step (listening, user transcript, each tool start/result, assistant text). QML `FileView` watches that file, so you can see the two (or more) tool calls as they happen — name, args, truncated result — then Agavai’s spoken reply. The overlay stays until dismissed or replaced.

**Desktop app:** `agavai app` / launcher entry **Agavai**. GTK4 + libadwaita window that reads the same `ui.json`, with Listen, Send, Cancel, and a typed Ask box. Prefer this if the overlay does not appear. `~/.local/share/applications/agavai.desktop`.

Voxtype’s waveform OSD stays off so it does not stack with the chat HUD.

**Out:** Instant Siri-style earcon on listen, then a second cue while the LLM thinks. A background Kokoro process is started at listen/ask so the model is already loaded when the reply is ready. Final speech is Kokoro-82M on CPU (`kokoro-onnx` + onnxruntime CPU EP). eSpeak-ng is G2P and a robotic fallback. Whisper is never used for speech.

---

## Security

- llama-server binds `127.0.0.1`.
- No `--tools all` on llama-server (that would give the inference process a shell).
- No `bypassPermissions` coding agent in v1.
- File search is rooted. URLs must be `http(s)`. Launch targets are an enum.
- Omarchy plugins are unsandboxed if you add a QML overlay later; v1’s orchestrator is a CLI.

---

## Source map

| Path | Role |
|---|---|
| `src/agavai/config.py` | TOML + builtin catalog + model id |
| `src/agavai/orchestrator.py` | Tool loop |
| `src/agavai/llm.py` | llama-server HTTP client |
| `src/agavai/tools.py` | Allowlist |
| `src/agavai/voxtype.py` | `--file` record/stop |
| `src/agavai/mcp_server.py` | MCP stdio |
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

Voice: Super+Ctrl+M, speak, pause — Agavai sends after 900 ms of silence.

Fresh machine:

```bash
~/Projects/agavai/scripts/download-model.sh
~/Projects/agavai/scripts/install.sh
systemctl --user enable --now agavai-llm
```
