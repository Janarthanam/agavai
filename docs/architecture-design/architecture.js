"use strict";

const components = {
  capture: {
    name: "Microphone capture", label: "16 kHz mono PCM", kind: "Local audio transport",
    purpose: "Read the default microphone once. Reuse the same samples for the orb's RMS meter; the meter never commits a turn.",
    deployment: "A parec subprocess owned by the listener, opened for each utterance. No recording service or second VAD stream.",
    contract: "Raw signed 16-bit little-endian PCM, 16,000 samples/s. Parent frames bytes for the ASR child; levels reach ChatUi at most 10 Hz.",
    lifecycle: "Capture starts while listening and stops before reasoning/playback. A session-unmuted source is restored when leaving listening.",
    files: ["src/agavai/asr.py", "src/agavai/meter.py", "src/agavai/feedback.py"]
  },
  recognizer: {
    name: "Streaming recognizer", label: "Parakeet: text + EOU", kind: "Model child process",
    purpose: "Keep a growing hypothesis and emit interim, end-of-boundary (EOB) and end-of-utterance (EOU) events.",
    deployment: "One parakeet_worker.py child per listening session, in the configured speech venv; NumPy and ONNX Runtime run there, not in the stdlib parent.",
    contract: "Binary length-framed PCM in; UTF-8 JSON lines out. CPU default; optional CUDA when configured and available. ONNX intra-op threads = 1.",
    lifecycle: "Load once per session. After nonempty EOU, ignore queued PCM until parent flush/reset; emit reset acknowledgement and clear all recognition state.",
    files: ["src/agavai/asr.py", "src/agavai/parakeet_worker.py", "docs/audio.md"]
  },
  session: {
    name: "Session controller", label: "Commit, cancel, resume", kind: "Session owner",
    purpose: "Decide when a request is final, order turn execution and speech, and keep listening until dismissal.",
    deployment: "Detached python -m agavai listen. It owns the ASR child, capture and ChatUi instance. The controller is not a resident systemd service.",
    contract: "Interim/EOB replace the hypothesis. Nonempty EOU or Enter invokes run_turn(text, cfg, ui). Escape drops the hypothesis and cancels the session.",
    lifecycle: "Guard invocation with listener PID/start token and startup lock. Reasoning and speech run serially with capture paused; results and memory stay until a topic reset or exit.",
    files: ["src/agavai/__main__.py", "src/agavai/app.py", "src/agavai/state.py"]
  },
  engine: {
    name: "Turn engine", label: "Context → route → tool loop", kind: "In the session process",
    purpose: "Convert one committed sentence into a verified action/result and short answer. It coordinates Qwen; it does not implement inference.",
    deployment: "run_turn() in orchestrator.py, called in the listener or a separate one-shot agavai ask process.",
    contract: "Health check; strict local context label when history exists; choose heads; chat with selected schemas; execute calls in order; feed results back until final text.",
    lifecycle: "Six model rounds default; one missing-head attachment retry. Keep up to 24 non-system messages. The advertised subset guides Qwen; DISPATCH is the global execution allowlist.",
    files: ["src/agavai/orchestrator.py", "src/agavai/router.py", "src/agavai/heads.py", "src/agavai/llm.py"]
  },
  model: {
    name: "Local Qwen", label: "Proposes calls or an answer", kind: "Resident model service",
    purpose: "Given text, history and tools, return a next function call or final answer. Also classify topic continuity in a separate no-tools request.",
    deployment: "agavai-llm.service → agavai-llm → llama-server, default 127.0.0.1:18766. Qwen3-4B-Instruct Q4_K_M (~2.5 GB), CPU by default; own user-service cgroup.",
    contract: "Non-streaming OpenAI-compatible POST /v1/chat/completions. Health uses /health then /v1/models. Responses contain choices[0].message.content and/or tool_calls.",
    lifecycle: "--parallel 1; 8,192 context tokens; 512 output tokens and 120 s client timeout default. systemd restarts failures after 3 s; model selection changes need a restart.",
    files: ["src/agavai/llm.py", "src/agavai/config.py", "scripts/agavai-llm", "systemd/agavai-llm.service"]
  },
  tools: {
    name: "Tool executor", label: "Allowlisted desktop actions", kind: "In the session process",
    purpose: "Resolve a proposed tool name in DISPATCH, validate its arguments and perform the named action through existing local commands.",
    deployment: "tools.py functions in the caller. They spawn host commands such as omarchy, hyprctl, fd, grim and tesseract using fixed argument lists.",
    contract: "call_tool(name, JSON arguments, cfg) → result string. Unknown names, invalid arguments, exceptions and subprocess timeouts return error strings.",
    lifecycle: "35 global tools, executed sequentially. File search uses configured roots. No generic shell, isolated tool service, transaction or rollback.",
    files: ["src/agavai/tools.py", "src/agavai/heads.py"]
  },
  ui: {
    name: "Native UI & snapshot", label: "Transcript, canvas, controls", kind: "Presentation boundary",
    purpose: "Show partial speech and typed results, preserve local paths for opening, and send explicit stop/cancel/open controls.",
    deployment: "ChatUi writes ui.json in the listener; the keepLoaded janar.agavai Quickshell plugin reads it in the separate Omarchy shell process.",
    contract: "Atomic temporary-file replacement; FileView watches the latest snapshot. It includes session_id, transcript{text,final}, phase, tools, display{id,items}, answer_html and completion.",
    lifecycle: "A new display id expands results; retained snapshots preserve manual minimization. dismissed-session suppresses late writes. Selected item/compact state live in QML, model memory in Python.",
    files: ["src/agavai/ui.py", "src/agavai/canvas.py", "src/agavai/richtext.py", "plugin/Chat.qml", "plugin/ResultBrowser.qml", "plugin/VoiceOrb.qml", "plugin/BarWidget.qml"]
  },
  speech: {
    name: "Speech output", label: "Kokoro → WAV → speakers", kind: "Speech controller + model",
    purpose: "Speak the finished reply after tools complete. Warming is silent; the working acknowledgement is separate from the final answer.",
    deployment: "tts.py in the listener; on-demand Kokoro CPU child in the speech venv; pw-play/paplay subprocess for a full WAV.",
    contract: "Unix-socket JSON line {text,out,voice} → {ok,error?}; audio is written to a local file, not streamed through the socket. Default voice af_bella.",
    lifecycle: "Kokoro warms at listen/think time and accepts serial requests; idle accept timeout 600 s. Speech fallback is eSpeak then notification after preference. Listener Kokoro playback polls cancel at ≤100 ms; synthesis/eSpeak/typed playback can block.",
    files: ["src/agavai/tts.py", "scripts/kokoro_synth.py", "scripts/download-tts.sh"]
  },
  mel: {
    name: "Continuous mel frontend", label: "128 log-mel bands", kind: "ASR child / NumPy",
    purpose: "Convert one continuous PCM signal into model features without treating packet boundaries as signal boundaries.",
    deployment: "MelStream and log_mel inside parakeet_worker.py; no additional process.",
    contract: "int16 / 32768; pre-emphasis 0.97; Hann window 400 samples, FFT 512, hop 160; HTK mel scale with area normalization, 128 bands; log(mel + 2⁻²⁴), no feature normalization.",
    lifecycle: "Keep previous sample and pending FFT overlap. Pad only stream start/explicit final flush. Feed 16 new frames plus nine preceding frames to the encoder.",
    files: ["src/agavai/parakeet_worker.py", "features/asr_worker.feature"]
  },
  encoder: {
    name: "Cache-aware encoder", label: "FastConformer / ONNX", kind: "ASR child / ONNX",
    purpose: "Encode the next 160 ms of features using rolling attention/convolution caches instead of reprocessing the whole sentence.",
    deployment: "Pinned dynamic encoder.onnx loaded in the same ASR worker; CPU or configured CUDA provider.",
    contract: "audio_signal [1,128,25] (nine context + 16 new frames), length and cache_last_channel/time/len → encoded outputs, encoded_lengths and new caches.",
    lifecycle: "Channel cache [17,1,70,512]; time cache [17,1,512,8]. Cache persists between steps and clears on reset. No measured per-step desktop SLA.",
    files: ["src/agavai/parakeet_worker.py", "scripts/download-asr.sh"]
  },
  decoder: {
    name: "Greedy RNN-T decoder", label: "Tokens, EOB, EOU", kind: "ASR child / ONNX",
    purpose: "Generate the text hypothesis and learned end markers from encoder frames and recurrent token state.",
    deployment: "FP32 decoder_joint.onnx + local vocabulary in the ASR worker.",
    contract: "Argmax decode, at most ten symbols per encoder frame. Blank=1026 advances; EOB=1025 emits provisional boundary; nonempty EOU=1024 ends the utterance. h/c states [1,1,640].",
    lifecycle: "Emit interim after normal tokens. Ignore empty EOU. After nonempty EOU wait for reset. Enter can submit the parent hypothesis; no silence-timer fallback.",
    files: ["src/agavai/parakeet_worker.py", "docs/audio.md"]
  },
  host: {
    name: "Host desktop commands", label: "Omarchy, Hyprland, files", kind: "Host dependencies",
    purpose: "Make the actual desktop change or lookup requested by an allowlisted function.",
    deployment: "Existing system CLI programs and local filesystem. The tool executor calls them directly, without an app-owned container.",
    contract: "Fixed argv and bounded subprocess calls. Examples: hyprctl JSON, fd paths, grim PNG stdout → tesseract stdin. Default _run timeout 15 s; tool-specific values differ.",
    lifecycle: "A result returns to the model and canvas; selection/preview alone is not an action. Browser-opening tools can access http(s) independently of local inference.",
    files: ["src/agavai/tools.py", "src/agavai/ui.py"]
  },
  jev: {
    name: "Optional Jev router", label: "One typed head choice", kind: "Remote / optional",
    purpose: "Choose a head from a committed utterance. It receives text, not microphone audio, and never executes a tool.",
    deployment: "Configured external OpenRouter Decisions API. No remote Agavai server is deployed by this application.",
    contract: "HTTPS POST /api/alpha/decisions with Bearer key; model typesafe/jev-1.13, state.utterance and a typed choice question; read answers.head.choice. Default timeout 2 s.",
    lifecycle: "Missing key, request failure or empty result can use keyword fallback; fallback=none returns no tools. backend=keyword avoids this hop; backend=local currently uses keywords too.",
    files: ["src/agavai/router.py", "src/agavai/config.py", "share/config.example.toml"], remote: true
  }
};

const edges = {
  pcm: {
    from: "capture", to: "recognizer", label: "PCM", protocol: "parec stdout → parent pump → worker stdin (binary pipe)",
    payload: "Unsigned 4-byte BIG-ENDIAN byte length, followed by that many signed little-endian int16 samples. 16 kHz, mono; no WAV header. Zero length asks for flush/reset.",
    effect: "Only transport bytes; no word, turn or tool decision. Worker sends JSONL ready before capture starts.",
    example: "[00 00 0c 80] + 3200 bytes of s16le PCM\n[00 00 00 00] → flush / reset → JSONL reset acknowledgement", files: ["src/agavai/asr.py", "src/agavai/parakeet_worker.py"]
  },
  events: {
    from: "recognizer", to: "session", label: "JSONL", protocol: "ASR child stdout / UTF-8 newline-delimited JSON",
    payload: "{kind,text}: ready, interim, eob, eou, reset, error. Interim/EOB replace the hypothesis. Only nonempty EOU commits a sentence.",
    effect: "Parent pauses the audio pump, sends a zero-length reset frame and waits for reset acknowledgement before running the turn. Queued audio cannot begin a second hypothesis before reset.",
    example: '{"kind":"interim","text":"find the budget"}\n{"kind":"eou","text":"find the budget notes"}', files: ["src/agavai/asr.py", "src/agavai/__main__.py"]
  },
  commit: {
    from: "session", to: "engine", label: "committed text", protocol: "In-process Python function call; return value is the final reply",
    payload: "run_turn(text, cfg, ui, continue_conversation=...). Text is a completed utterance; subsequent turns can use ChatUi's remembered model_messages/model_heads.",
    effect: "No audio or partial text enters reasoning. First turn has blank history; later turns classify topic continuity. The returned reply is spoken by the controller.",
    example: 'run_turn("find the budget notes", cfg, ui)\n→ "I found your notes. They are on the canvas."', files: ["src/agavai/__main__.py", "src/agavai/orchestrator.py"], reply: true
  },
  chat: {
    from: "engine", to: "model", label: "HTTP", protocol: "Default loopback HTTP POST /v1/chat/completions; JSON, stream:false",
    payload: "model alias, messages, temperature, max_tokens, and selected function schemas with tool_choice:auto. Response choices[0].message has content and/or tool_calls with id, name and arguments.",
    effect: "A proposal, not execution. Subsequent requests include assistant tool_calls and role:tool results with matching tool_call_id. Context classification uses the same endpoint, no tools, temperature 0, max_tokens 16.",
    example: '{model:"agavai", messages:[system,user],\n tools:[search_files_schema], stream:false}\n→ tool_calls:[{id:"c1", function:{name:"search_files",\n arguments:"{\\"query\\":\\"budget\\"}"}}]', files: ["src/agavai/llm.py", "src/agavai/orchestrator.py"], reply: true
  },
  action: {
    from: "engine", to: "tools", label: "call / result", protocol: "In-process call_tool(name, arguments, cfg) → string",
    payload: "Allowlisted name and argument object/JSON string. Return raw JSON or plain text; validation, unknown names and timeout/exception failures return error strings.",
    effect: "Calls within one completion execute sequentially. A missing head is attached once and completion retried before execution. Per-turn schemas are not an independent permission layer.",
    example: 'call_tool("search_files", {"query":"budget"}, cfg)\n→ ["/home/user/Documents/budget_notes.md"]', files: ["src/agavai/orchestrator.py", "src/agavai/tools.py"], reply: true
  },
  snapshot: {
    from: "session", to: "ui", label: "ui.json / CLI", protocol: "Python atomic file replace → QML FileView; return controls via CLI + SIGTERM",
    payload: "Snapshot: session_id, phase, transcript{text,final}, level_db, turns, display{id,items}, answer_html, completion. UI controls: agavai stop, cancel, ui-open index --session id.",
    effect: "Stop submits the current hypothesis. Cancel marks dismissed-session and listen.cancel before SIGTERM. Writer suppresses later snapshots for that session id. This is a file protocol, not a websocket.",
    example: 'transcript: {text:"find the budget", final:false}\ndisplay: {id:"presentation-uuid", kind:"files", items:[…]}', files: ["src/agavai/ui.py", "src/agavai/__main__.py", "plugin/Chat.qml"], reply: true
  },
  results: {
    from: "engine", to: "ui", label: "canvas", protocol: "ui.tool_done → canvas.display_for → atomic ui.json",
    payload: "Full raw tool result becomes typed display items with id, kind, title, subtitle, path, uri, openable and preview. Separate model_view projects kind/readable name, clipped to 500 characters.",
    effect: "UI can open/preview the full local item; Qwen and speech avoid paths/extensions. New display identity expands the canvas; retained display preserves minimization.",
    example: 'UI: {kind:"file", path:"/…/budget_notes.md", openable:true}\nModel: {kind:"file", name:"budget notes"}', files: ["src/agavai/ui.py", "src/agavai/canvas.py", "src/agavai/richtext.py"]
  },
  spoken: {
    from: "session", to: "speech", label: "reply", protocol: "In-process _interruptible_speak(reply,cfg), then Unix socket + WAV playback",
    payload: "Finished one/two-sentence answer after tool results. Kokoro request is newline JSON {text,out,voice}; response {ok,error?}; local WAV path goes to pw-play/paplay.",
    effect: "No TTS on partial speech. Warm model and think acknowledgement are separate. Capture reopens after playback, not during it.",
    example: '{"text":"I found your notes.","out":"/tmp/reply.wav",\n "voice":"af_bella"}\n→ {"ok":true}; play /tmp/reply.wav', files: ["src/agavai/__main__.py", "src/agavai/tts.py", "scripts/kokoro_synth.py"]
  },
  features: {
    from: "mel", to: "encoder", label: "features", protocol: "In-memory float32 tensor → ONNX encoder.run",
    payload: "audio_signal [1,128,25]: nine preceding mel frames and 16 new frames, plus length and rolling cache tensors. Raw log-mel; no per-feature normalization.",
    effect: "Encoder step represents 160 ms of new audio. Previous sample and FFT overlap survive transport packet splits.",
    example: "audio_signal: float32 [1,128,25]\nlength: int64 [1]\ncache_last_channel: [17,1,70,512]", files: ["src/agavai/parakeet_worker.py"]
  },
  encoded: {
    from: "encoder", to: "decoder", label: "frames", protocol: "ONNX output arrays → per-frame decoder/joint ONNX calls",
    payload: "Encoder outputs + encoded_lengths, then encoder frame, last token, target length and h/c input states. Decoder returns logits and h/c output states.",
    effect: "Greedy argmax emits at most ten symbols per encoder frame. Blank advances; normal tokens update hypothesis; EOB remains provisional; nonempty EOU ends the turn.",
    example: "decoder(encoder_frame, last_token, h, c)\nargmax → subword / BLANK 1026 / EOB 1025 / EOU 1024", files: ["src/agavai/parakeet_worker.py"]
  },
  samples: {
    from: "capture", to: "mel", label: "samples", protocol: "Unframed s16le bytes → NumPy float32 samples inside worker",
    payload: "np.frombuffer(payload, dtype='<i2').astype(float32) / 32768. Input framing is identical to the PCM contract in the system diagram.",
    effect: "Continue pre-emphasis and overlapping FFT windows; only explicit stream start/end are padded.",
    example: "samples[n] = int16[n] / 32768\nemphasized[n] = samples[n] − 0.97 × samples[n−1]", files: ["src/agavai/parakeet_worker.py"]
  },
  nativeControl: {
    from: "ui", to: "session", label: "CLI / file", protocol: "Plugin runs local agavai CLI; listener publishes atomic ui.json",
    payload: "invoke summons plugin and guards listener startup. stop/cancel target identity-checked listener pid. QML renders the current snapshot through FileView.",
    effect: "Native plugin remains loaded after listener exit. Compact/expanded presentation is UI-owned, not a second assistant process.",
    example: "Click → agavai invoke\nEnter → agavai stop\nEscape → agavai cancel\nui.json → FileView", files: ["plugin/Chat.qml", "plugin/BarWidget.qml", "src/agavai/app.py", "src/agavai/ui.py"], reply: true
  },
  workerPipes: {
    from: "session", to: "recognizer", label: "child pipes", protocol: "Popen speech-venv Python with stdin/stdout/stderr pipes",
    payload: "argv: ASR venv/bin/python, parakeet_worker.py, model_dir, resolved_device. PCM framed binary input; JSONL ready/events/reset output.",
    effect: "Handshake allows 120 s for worker startup. Worker is per session; capture is per utterance. Parent closes/terminates it on session cleanup.",
    example: "main interpreter: stdlib\nchild interpreter: NumPy + ONNX Runtime\nparent ⇄ binary stdin / JSONL stdout", files: ["src/agavai/asr.py", "src/agavai/__main__.py"], reply: true
  },
  serviceHttp: {
    from: "session", to: "model", label: "HTTP :18766", protocol: "Same local HTTP client used by Turn engine",
    payload: "Text messages and selected schemas go to the resident local model. Context-only and action completions use this one service.",
    effect: "llama-server runs in its own systemd user cgroup, --parallel 1. It outlives listener sessions; it is not Voxtype's sanitizer on :18765.",
    example: "agavai-llm.service → llama-server\n127.0.0.1:18766/v1/chat/completions", files: ["src/agavai/llm.py", "scripts/agavai-llm", "systemd/agavai-llm.service"], reply: true
  },
  unix: {
    from: "session", to: "speech", label: "Unix socket", protocol: "AF_UNIX SOCK_STREAM / $XDG_RUNTIME_DIR/agavai/kokoro.sock",
    payload: "Ping {cmd:'ping'} → {ok:true,ready:true}; synthesis {text,out,voice} → {ok:true} or error. WAV data is passed through the filesystem, not the socket.",
    effect: "On-demand detached CPU model process, not systemd. Accepts serial requests and exits after 600 s idle accept timeout. Socket client timeout is 30 s.",
    example: 'socket.send({text:"Done.", out:"/tmp/reply.wav", voice:"af_bella"})\n→ {ok:true}; local WAV is ready', files: ["src/agavai/tts.py", "scripts/kokoro_synth.py"], reply: true
  },
  argv: {
    from: "session", to: "host", label: "subprocess argv", protocol: "Tool dispatcher → local subprocesses, captured stdout/stderr and file reads",
    payload: "Named implementations build fixed argument lists: fd filename search, hyprctl clients/dispatch, Omarchy actions; grim PNG stdout is piped to tesseract stdin for OCR.",
    effect: "Existing desktop program performs the action. Global allowlist has no generic shell. Timeout/error strings return to the model; finished actions are not rolled back on cancel.",
    example: '["fd","-i","--max-results","20","budget",root]\n["hyprctl","clients","-j"]', files: ["src/agavai/tools.py"], reply: true
  },
  https: {
    from: "session", to: "jev", label: "optional HTTPS", protocol: "Router HTTPS POST /api/alpha/decisions with Bearer key",
    payload: "{model:'typesafe/jev-1.13',state:{utterance},questions:{head:{type:'choice',criteria}}}; parse answers.head.choice.",
    effect: "Committed text leaves the machine only when remote routing is used. Keyword mode and fallback execute locally; no audio or tool invocation goes to Jev.",
    example: 'state:{utterance:"find the budget notes"}\n→ answers:{head:{choice:"files"}}', files: ["src/agavai/router.py", "share/config.example.toml"], reply: true, remote: true
  }
};

const diagrams = {
  system: {
    height: 615,
    nodes: [["capture",32,60],["recognizer",288,60],["session",544,60],["speech",800,60],["ui",288,290],["engine",544,290],["model",800,290],["tools",544,490]],
    edges: [
      ["pcm",[[240,106],[288,106]],[264,81]],
      ["events",[[496,106],[544,106]],[520,81]],
      ["spoken",[[752,106],[800,106]],[776,81]],
      ["commit",[[648,152],[648,290]],[648,218]],
      ["chat",[[752,336],[800,336]],[776,311]],
      ["action",[[648,382],[648,490]],[648,435]],
      ["snapshot",[[600,152],[600,210],[392,210],[392,290]],[456,210]],
      ["results",[[568,290],[568,267],[416,267],[416,290]],[520,267]]
    ],
    notes: [[32,300,"Recognition is live.\nActions wait for commitment."],[800,505,"Qwen proposes.\nThe executor acts.\nSpeech follows the result."]]
  },
  audio: {
    height: 230,
    nodes: [["capture",32,72,"PCM input","Worker input"],["mel",288,72],["encoder",544,72],["decoder",800,72]],
    edges: [["samples",[[240,118],[288,118]],[264,190]],["features",[[496,118],[544,118]],[520,190]],["encoded",[[752,118],[800,118]],[776,190]]],
    groups: [["Continuous signal and model state; reset only at the utterance boundary",16,16,1008,198]]
  },
  deployment: {
    height: 730,
    nodes: [["ui",32,90,"Native plugin","Quickshell process"],["session",352,90,"Listener process","System Python / session"],["model",704,90,"Qwen / llama-server","systemd user service"],["host",32,320],["recognizer",352,320,"ASR worker","Speech-venv child"],["speech",704,320,"Kokoro server","Speech-venv / warm child"],["jev",816,596]],
    edges: [
      ["nativeControl",[[240,136],[352,136]],[296,110]],
      ["serviceHttp",[[560,136],[704,136]],[632,110]],
      ["workerPipes",[[456,182],[456,320]],[456,252]],
      ["argv",[[384,182],[384,246],[136,246],[136,320]],[244,246]],
      ["unix",[[560,160],[608,160],[608,300],[808,300],[808,320]],[670,300]],
      ["https",[[560,150],[640,150],[640,560],[920,560],[920,596]],[640,480]]
    ],
    groups: [["User's computer · no application containers",16,24,1008,500],["External service",800,548,224,158,"remote"]],
    notes: [[40,450,"Plugin + Qwen outlive a session.\nListener + ASR end on dismissal.\nKokoro can remain warm."]]
  }
};

const scenarios = {
  search: [
    {title:"Listen", heading:"Capture and revise a partial", state:"Listening", nodes:["capture","recognizer","session","ui"], input:"“find the budget …” is still being spoken.", output:"PCM → recognizer; interim text replaces transcript with final:false. No model call yet.", reason:"A revised hypothesis must not trigger a stale or duplicate action."},
    {title:"Commit", heading:"Accept exactly one finished utterance", state:"Listening → Reasoning", nodes:["recognizer","session","engine"], input:"Nonempty EOU: “find the budget notes”, or Enter on the current hypothesis.", output:"Worker reset acknowledged; capture stops. run_turn receives one final sentence.", reason:"The controller owns commitment; packet length, RMS level and short pauses do not."},
    {title:"Route", heading:"Give Qwen the files schema", state:"Reasoning", nodes:["engine","model"], input:"First turn: no previous messages; health check succeeds.", output:"Jev or keyword selects files. Qwen receives system + user text + search_files schema.", reason:"Heads reduce schema context. The remote choice is optional; tool inference stays local."},
    {title:"Execute", heading:"Run the proposed search locally", state:"Reasoning → Executing tools", nodes:["engine","model","tools"], input:'Qwen proposes search_files({query:"budget"}).', output:"call_tool dispatches to fd under configured roots; returns an illustrative path list.", reason:"Only the named executor performs the search. Qwen's proposal itself has no effect."},
    {title:"Feed back", heading:"Publish results, then let Qwen finish", state:"Executing tools → Reasoning", nodes:["engine","ui","model"], input:"Full file-path list from the tool.", output:"Canvas retains paths/previews; a short kind/name tool message goes to Qwen with matching tool_call_id.", reason:"One result serves two consumers: actionable screen data and compact readable model context."},
    {title:"Reply", heading:"Speak and reopen listening", state:"Reasoning → Speaking → Listening", nodes:["engine","session","speech","ui"], input:"Qwen returns a final short answer without tool calls.", output:"Remember conversation; synthesize/play WAV; clear live partial, keep canvas and start next capture.", reason:"The user can make a follow-up without losing the search results. Context ends on reset/dismissal."}
  ],
  followup: [
    {title:"Gallery", heading:"Show images and ask for a choice", state:"Executing tools → Speaking", nodes:["engine","tools","ui","speech"], input:"“show me wallpaper images”.", output:"wallpaper_list produces gallery rows; full paths stay in display, readable names enter history.", reason:"Displaying options is distinct from setting wallpaper; preview alone has no side effect."},
    {title:"Follow-up", heading:"Keep context for “ship at sea”", state:"Reasoning", nodes:["session","engine","model"], input:"New committed choice plus the previous gallery/question/tool results.", output:"Local context-only completion returns follow_up; retain messages, heads and canvas.", reason:"The choice only makes sense against earlier results. Matching a head or turn number is not the relevance rule."},
    {title:"Set image", heading:"Resolve and execute the named choice", state:"Executing tools", nodes:["engine","model","tools","ui"], input:'Qwen calls wallpaper_set({name:"ship at sea"}).', output:"Resolve supported local image; execute Omarchy bg set; publish Done/Not completed from tool result.", reason:"A truthful confirmation depends on the action's result, not on model intent."},
    {title:"New topic", heading:"Clear wallpaper context for a clock request", state:"Reasoning", nodes:["session","engine","model","ui"], input:"“what time is it?” with the old conversation still in memory.", output:"Local classifier returns new_conversation; clear turns, display, answer, completion and inherited messages/heads. Keep session_id.", reason:"A conversation can change without closing the listening session or breaking cancellation identity."},
    {title:"Answer", heading:"Route the new task independently", state:"Reasoning → Speaking → Listening", nodes:["engine","tools","speech","session"], input:"Clock request with clean conversation state.", output:"Select current heads, run the normal tool loop and speak the new answer.", reason:"Prior wallpaper tools/results must not contaminate an unrelated task."}
  ],
  cancel: [
    {title:"Speaking", heading:"The controller owns Kokoro playback", state:"Speaking", nodes:["session","speech"], input:"Final synthesized WAV playing via pw-play/paplay.", output:"Listener polls its owned playback process group at ≤100 ms slices.", reason:"Capture is paused: interruption comes from an explicit control, not spoken barge-in."},
    {title:"Dismiss", heading:"Publish cancellation before signalling", state:"Speaking → Cancel requested", nodes:["ui","session"], input:"Escape in expanded view, compact right-click, or bar cancel.", output:"Hide UI; write dismissed-session=id and listen.cancel, then SIGTERM the identity-checked listener.", reason:"The marker distinguishes cancel from Enter/stop and lets late writers see dismissal first."},
    {title:"Cleanup", heading:"Stop playback and reject stale results", state:"Cancel requested → Closed", nodes:["session","speech","recognizer","ui"], input:"Listener observes cancel; any later snapshot has the dismissed id.", output:"Terminate owned playback, remove WAV, close capture/ASR, remove listener pid; skip cancelled-session writes.", reason:"Cancellation is not rollback. Blocking HTTP/tool/synthesis or eSpeak work can delay cleanup; completed actions remain."}
  ]
};

const tooltip = document.getElementById("tooltip");
let stepIndex = 0;
let scenarioId = "search";

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
}

function sourceLinks(files) {
  return files.map(file => `<a href="../../${escapeHtml(file)}">${escapeHtml(file)}</a>`).join("");
}

function nodeDetails(item) {
  return `<dl><dt>Responsibility</dt><dd>${escapeHtml(item.purpose)}</dd><dt>Deployment</dt><dd>${escapeHtml(item.deployment)}</dd><dt>Interface</dt><dd>${escapeHtml(item.contract)}</dd><dt>Lifecycle / bounds</dt><dd>${escapeHtml(item.lifecycle)}</dd></dl>`;
}

function edgeDetails(item) {
  return `<dl><dt>Protocol</dt><dd>${escapeHtml(item.protocol)}</dd><dt>Data</dt><dd>${escapeHtml(item.payload)}</dd><dt>Control / effect</dt><dd>${escapeHtml(item.effect)}</dd></dl><pre>${escapeHtml(item.example)}</pre>`;
}

function hideTooltip() {
  tooltip.hidden = true;
  document.querySelectorAll('[aria-describedby="tooltip"]').forEach(el => el.removeAttribute("aria-describedby"));
}

function placeTooltip(event, element) {
  const box = element.getBoundingClientRect();
  const x = event.clientX ?? box.left;
  const y = event.clientY ?? box.bottom;
  tooltip.style.left = `${Math.max(12, Math.min(x + 16, innerWidth - tooltip.offsetWidth - 12))}px`;
  tooltip.style.top = `${Math.max(12, Math.min(y + 16, innerHeight - tooltip.offsetHeight - 12))}px`;
}

function inspect(figure, type, id, trigger) {
  hideTooltip();
  const item = type === "node" ? components[id] : edges[id];
  const title = type === "node" ? item.name : `${components[item.from].name} → ${components[item.to].name}`;
  const contract = figure.querySelector(".contract");
  figure.querySelectorAll("[aria-pressed]").forEach(el => el.setAttribute("aria-pressed", String(el === trigger)));
  contract.hidden = false;
  contract.innerHTML = `<button type="button" class="close-contract" aria-label="Close selected contract">×</button><h3>${escapeHtml(title)}</h3>${type === "node" ? nodeDetails(item) : edgeDetails(item)}<p class="sources">${sourceLinks(item.files)}</p>`;
  contract.querySelector("button").addEventListener("click", () => {
    contract.hidden = true;
    figure.querySelectorAll('[aria-pressed="true"]').forEach(el => el.setAttribute("aria-pressed", "false"));
    trigger.focus();
    hideTooltip();
  });
  document.getElementById("selection-status").textContent = `Selected ${title}. The contract is open beneath this diagram.`;
}

function bindInspection(element, figure, type, id, keyboardTrigger = element) {
  const item = type === "node" ? components[id] : edges[id];
  const show = event => {
    if (event.pointerType === "touch") return;
    const title = type === "node" ? item.name : `${components[item.from].name} → ${components[item.to].name}`;
    const body = type === "node"
      ? `<p><b>Does:</b> ${escapeHtml(item.purpose)}</p><p><b>Deployed:</b> ${escapeHtml(item.deployment)}</p>`
      : `<p><b>Protocol:</b> ${escapeHtml(item.protocol)}</p><p><b>Flows:</b> ${escapeHtml(item.payload)}</p>`;
    tooltip.innerHTML = `<strong>${escapeHtml(title)}</strong>${body}<p>Click for the full contract and code.</p>`;
    tooltip.hidden = false;
    keyboardTrigger.setAttribute("aria-describedby", "tooltip");
    placeTooltip(event, element);
  };
  element.addEventListener("pointerenter", show);
  element.addEventListener("pointermove", event => { if (!tooltip.hidden) placeTooltip(event, element); });
  element.addEventListener("pointerleave", hideTooltip);
  element.addEventListener("focus", show);
  element.addEventListener("blur", hideTooltip);
  element.addEventListener("click", () => inspect(figure, type, id, keyboardTrigger));
}

function renderDiagram(element) {
  const id = element.dataset.diagram;
  const diagram = diagrams[id];
  const figure = element.closest("figure");
  element.style.height = `${diagram.height}px`;
  const ns = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(ns, "svg");
  svg.setAttribute("viewBox", `0 0 1040 ${diagram.height}`);
  svg.setAttribute("aria-hidden", "true");
  svg.innerHTML = `<defs><marker id="arrow-${id}" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="6" markerHeight="6" orient="auto-start-reverse"><path d="M1 1L7 4L1 7" fill="none" stroke="context-stroke"/></marker></defs>`;
  element.append(svg);
  for (const [name,x,y,width,height,kind] of diagram.groups || []) {
    const group = document.createElement("div");
    group.className = `group ${kind || ""}`;
    group.style.cssText = `left:${x}px;top:${y}px;width:${width}px;height:${height}px`;
    group.innerHTML = `<span>${escapeHtml(name)}</span>`;
    element.append(group);
  }
  for (const [nodeId,x,y,title,kind] of diagram.nodes) {
    const item = components[nodeId];
    const node = document.createElement("button");
    node.type = "button";
    node.className = `node ${item.remote ? "remote" : ""}`;
    node.dataset.node = nodeId;
    node.setAttribute("aria-pressed", "false");
    node.style.cssText = `left:${x}px;top:${y}px`;
    node.innerHTML = `<small class="kind">${escapeHtml(kind || item.kind)}</small><strong>${escapeHtml(title || item.name)}</strong><small>${escapeHtml(item.label)}</small>`;
    element.append(node);
    bindInspection(node, figure, "node", nodeId);
  }
  for (const [edgeId,points,label] of diagram.edges) {
    const item = edges[edgeId];
    const path = document.createElementNS(ns, "path");
    path.setAttribute("d", points.map(([x,y],i) => `${i ? "L" : "M"}${x} ${y}`).join(" "));
    path.setAttribute("class", `wire ${item.remote ? "remote" : ""}`);
    path.setAttribute("marker-end", `url(#arrow-${id})`);
    if (item.reply) path.setAttribute("marker-start", `url(#arrow-${id})`);
    svg.append(path);
    const button = document.createElement("button");
    button.type = "button";
    button.className = "edge";
    button.dataset.edge = edgeId;
    button.setAttribute("aria-pressed", "false");
    button.setAttribute("aria-label", `${components[item.from].name} to ${components[item.to].name}: ${item.protocol}`);
    button.style.cssText = `left:${label[0]}px;top:${label[1]}px`;
    button.textContent = item.label;
    element.append(button);
    bindInspection(button, figure, "edge", edgeId);
    const hit = document.createElementNS(ns, "path");
    hit.setAttribute("d", path.getAttribute("d"));
    hit.setAttribute("class", "wire-hit");
    svg.append(hit);
    bindInspection(hit, figure, "edge", edgeId, button);
  }
  for (const [x,y,note] of diagram.notes || []) {
    const p = document.createElement("p");
    p.className = "diagram-note";
    p.style.cssText = `left:${x}px;top:${y}px`;
    p.innerHTML = escapeHtml(note).replace(/\n/g, "<br>");
    element.append(p);
  }
}

function renderStep() {
  const steps = scenarios[scenarioId];
  const step = steps[stepIndex];
  document.getElementById("step-count").textContent = `Step ${stepIndex + 1} of ${steps.length}`;
  document.getElementById("previous").disabled = stepIndex === 0;
  document.getElementById("next").disabled = stepIndex === steps.length - 1;
  document.getElementById("step-list").innerHTML = steps.map((s,i) => `<li><button type="button" data-step="${i}" ${i === stepIndex ? 'aria-current="step"' : ""}>${i + 1}. ${escapeHtml(s.title)}</button></li>`).join("");
  document.querySelectorAll("[data-step]").forEach(button => button.addEventListener("click", () => { stepIndex = Number(button.dataset.step); renderStep(); }));
  document.getElementById("step-detail").innerHTML = `<p class="transition">${escapeHtml(step.state)}</p><h4>${escapeHtml(step.heading)}</h4><dl class="step-data"><div><dt>Input</dt><dd>${escapeHtml(step.input)}</dd></div><div><dt>Output</dt><dd>${escapeHtml(step.output)}</dd></div></dl><p>${escapeHtml(step.reason)}</p>`;
  document.querySelectorAll('[data-diagram="system"] .node').forEach(node => node.classList.toggle("trace", step.nodes.includes(node.dataset.node)));
}

function initialize() {
  document.querySelectorAll("[data-diagram]").forEach(renderDiagram);
  document.getElementById("scenario").addEventListener("change", event => { scenarioId = event.target.value; stepIndex = 0; renderStep(); });
  document.getElementById("previous").addEventListener("click", () => { if (stepIndex > 0) { stepIndex--; renderStep(); } });
  document.getElementById("next").addEventListener("click", () => { if (stepIndex < scenarios[scenarioId].length - 1) { stepIndex++; renderStep(); } });
  document.addEventListener("keydown", event => { if (event.key === "Escape") hideTooltip(); });
  window.addEventListener("scroll", hideTooltip, true);
  window.addEventListener("resize", hideTooltip);
  renderStep();
}

initialize();
