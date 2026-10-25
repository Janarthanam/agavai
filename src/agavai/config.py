from __future__ import annotations

import os
import re
import shlex
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any


def _expand(path: str) -> Path:
    return Path(os.path.expanduser(path)).resolve()


def xdg_config() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))


def xdg_data() -> Path:
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))


def xdg_runtime() -> Path:
    return Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}"))


DEFAULT_MODEL_ID = "qwen3-4b-instruct"
DEFAULT_LLAMA_BIN = Path.home() / (
    ".lmstudio/extensions/backends/"
    "llama.cpp-linux-x86_64-vulkan-avx2-2.31.2/llama-server"
)


@dataclass(frozen=True)
class ModelSpec:
    """One on-device GGUF the assistant can load."""

    id: str
    path: Path
    description: str = ""
    download_url: str | None = None
    expected_bytes: int | None = None
    ctx_size: int | None = None
    n_gpu_layers: int | None = None
    builtin: bool = False

    def present(self) -> bool:
        return self.path.is_file()


def _default_model_path(filename: str) -> Path:
    return xdg_data() / "agavai" / "models" / filename


BUILTIN_MODELS: dict[str, ModelSpec] = {
    "qwen3-4b-instruct": ModelSpec(
        id="qwen3-4b-instruct",
        path=_default_model_path("Qwen3-4B-Instruct-2507-Q4_K_M.gguf"),
        description=(
            "Qwen3-4B Instruct 2507 Q4_K_M (~2.5 GB). Non-thinking, tool-capable. "
            "Default for the voice loop on 8 GB VRAM / 62 GB RAM."
        ),
        download_url=(
            "https://huggingface.co/unsloth/Qwen3-4B-Instruct-2507-GGUF/"
            "resolve/main/Qwen3-4B-Instruct-2507-Q4_K_M.gguf"
        ),
        expected_bytes=2497281120,
        ctx_size=8192,
        n_gpu_layers=0,
        builtin=True,
    ),
}


@dataclass
class LlmConfig:
    backend: str = "llama-server"
    tool_selection: str = "routed"
    venv: Path = field(default_factory=lambda: xdg_data() / "agavai/cactus-venv")
    runtime_library: Path | None = None
    host: str = "127.0.0.1"
    port: int = 18766
    alias: str = "agavai"
    model_id: str = DEFAULT_MODEL_ID
    model_path: Path = field(
        default_factory=lambda: BUILTIN_MODELS[DEFAULT_MODEL_ID].path
    )
    llama_bin: Path = field(default_factory=lambda: DEFAULT_LLAMA_BIN)
    ctx_size: int = 8192
    n_gpu_layers: int = 0
    temperature: float = 0.2
    max_tokens: int = 512
    max_tool_rounds: int = 6
    timeout_secs: int = 120
    # Unset leaves the server's sampling seed and prompt cache alone. The eval
    # pins both so a score repeats exactly.
    seed: int | None = None
    cache_prompt: bool | None = None
    models: dict[str, ModelSpec] = field(default_factory=dict)
    path_overridden: bool = False

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def active_spec(self) -> ModelSpec | None:
        return self.models.get(self.model_id)


@dataclass
class TtsConfig:
    prefer: str = "kokoro"
    voice: str = "af_bella"
    model_path: Path = field(
        default_factory=lambda: xdg_data() / "agavai/tts/kokoro-v1.0.fp16.onnx"
    )
    voices_path: Path = field(
        default_factory=lambda: xdg_data() / "agavai/tts/voices-v1.0.bin"
    )
    venv: Path = field(default_factory=lambda: xdg_data() / "agavai/tts-venv")


@dataclass
class RouterConfig:
    backend: str = "jev"
    fallback: str = "keyword"
    timeout_secs: int = 2
    max_tools: int = 8
    jev_base_url: str = "https://openrouter.ai/api/alpha/decisions"
    jev_model: str = "typesafe/jev-1.13"
    api_key_env: str = "OPENROUTER_API_KEY"
    needle: LlmConfig | None = None


@dataclass
class VadConfig:
    enabled: bool = True
    backend: str = "energy"
    rate: int = 16000
    frame_ms: int = 20
    open_threshold_dbfs: float = -35.0
    close_threshold_dbfs: float = -42.0
    noise_margin_db: float = 12.0
    silence_ms: int = 900
    min_speech_ms: int = 250
    max_record_ms: int = 15000
    start_timeout_ms: int = 5000
    lead_in_ignore_ms: int = 300
    model_path: Path = field(
        default_factory=lambda: xdg_data() / "agavai/vad/silero_vad-v5.1.2.onnx"
    )
    threshold: float = 0.5
    response_timeout_ms: int = 250
    device: str = "cpu"
    venv: Path = field(default_factory=lambda: xdg_data() / "agavai/tts-venv")


@dataclass
class AsrConfig:
    """Streaming recognizer. device is cpu, or gpu when an NVIDIA GPU is present."""

    device: str = "cpu"
    backend: str = "parakeet-onnx"
    endpoint: str = "native"
    mode: str = "streaming"
    model_path: Path = field(default_factory=lambda: xdg_data() / "agavai/models/whistle.cact")
    runtime_library: Path | None = None
    # Whistle only. "auto" lets Whistle guess, and it guesses wrong on short or noisy English.
    language: str = "en"
    chunk_ms: int = 1000
    startup_timeout_secs: float = 120
    finish_timeout_secs: float = 30
    max_utterance_secs: float = 120
    model_dir: Path = field(
        default_factory=lambda: xdg_data() / "agavai/models/parakeet-realtime-eou-120m"
    )
    venv: Path = field(default_factory=lambda: xdg_data() / "agavai/tts-venv")


@dataclass
class FilesConfig:
    roots: list[Path] = field(
        default_factory=lambda: [
            _expand("~/Documents"),
            _expand("~/Downloads"),
            _expand("~/Projects"),
            _expand("~/Work"),
        ]
    )
    max_results: int = 20


PLACEMENTS = ("bottom-right", "bottom-left", "top-right", "top-left")
LOG_LEVELS = ("info", "debug")


@dataclass
class OverlayConfig:
    """Monitor corner that holds the orb; the expanded view grows from it."""

    placement: str = "bottom-right"


@dataclass
class RecordingsConfig:
    """Where recordings are kept; each recording is one folder in it."""

    dir: Path = field(default_factory=lambda: _expand("~/Documents/Agavai/Recordings"))


@dataclass
class LogConfig:
    """debug adds what the user said, replies, and tool arguments and results."""

    level: str = "info"


@dataclass
class Config:
    llm: LlmConfig = field(default_factory=LlmConfig)
    # With no explicit small tier, the existing [llm] remains the local brain.
    small_brain: LlmConfig | None = None
    large_brain: LlmConfig | None = None
    files: FilesConfig = field(default_factory=FilesConfig)
    tts: TtsConfig = field(default_factory=TtsConfig)
    router: RouterConfig = field(default_factory=RouterConfig)
    vad: VadConfig = field(default_factory=VadConfig)
    asr: AsrConfig = field(default_factory=AsrConfig)
    overlay: OverlayConfig = field(default_factory=OverlayConfig)
    recordings: RecordingsConfig = field(default_factory=RecordingsConfig)
    log: LogConfig = field(default_factory=LogConfig)

    def llama_for_role(self, role: str = "service") -> LlmConfig | None:
        small = self.small_brain or self.llm
        if role == "small":
            return small if small.backend == "llama-server" else None
        if role == "large":
            return self.large_brain if self.large_brain and self.large_brain.backend == "llama-server" else None
        return self.llama_for_role("small") or self.llama_for_role("large")

    @property
    def tts_prefer(self) -> str:
        return self.tts.prefer

    runtime_dir: Path = field(default_factory=lambda: xdg_runtime() / "agavai")
    config_dir: Path = field(default_factory=lambda: xdg_config() / "agavai")
    config_path: Path = field(default_factory=lambda: xdg_config() / "agavai" / "config.toml")
    a2a_dir: Path = field(default_factory=lambda: xdg_config() / "agavai/a2a")

    @property
    def state_file(self) -> Path:
        return self.runtime_dir / "state"


def config_path() -> Path:
    env = os.environ.get("AGAVAI_CONFIG")
    if env:
        return _expand(env)
    return xdg_config() / "agavai" / "config.toml"


def _load_brain_config(spec: dict[str, Any], section: str, cfg: Config) -> LlmConfig:
    from agavai.brain import BRAIN_BACKENDS

    backend = str(spec.get("backend", "llama-server"))
    if backend not in BRAIN_BACKENDS:
        raise ValueError(f"Unknown brain backend: {backend}")
    model = spec.get("model_path")
    model_id = str(spec.get("model", section.rsplit(".", 1)[-1]))
    catalog_model = cfg.llm.models.get(model_id) if backend == "llama-server" else None
    if not model and catalog_model:
        model = str(catalog_model.path)
    if not model:
        raise ValueError(f"[{section}] needs model_path")
    tier = LlmConfig(backend=backend, model_id=model_id, llama_bin=cfg.llm.llama_bin, models=cfg.llm.models)
    tier.model_path = _expand(str(model))
    if catalog_model:
        if catalog_model.ctx_size is not None:
            tier.ctx_size = catalog_model.ctx_size
        if catalog_model.n_gpu_layers is not None:
            tier.n_gpu_layers = catalog_model.n_gpu_layers
    for key in ("host", "alias", "tool_selection"):
        if key in spec:
            setattr(tier, key, str(spec[key]))
    for key in ("port", "max_tokens", "max_tool_rounds", "timeout_secs", "ctx_size", "n_gpu_layers"):
        if key in spec:
            setattr(tier, key, int(spec[key]))
    if "temperature" in spec:
        tier.temperature = float(spec["temperature"])
    for key in ("venv", "runtime_library", "llama_bin"):
        if key in spec:
            setattr(tier, key, _expand(str(spec[key])))
    if tier.max_tool_rounds < 1 or tier.timeout_secs <= 0 or tier.max_tokens < 1:
        raise ValueError(f"Invalid limits in [{section}]")
    return tier


def load_config(path: Path | None = None) -> Config:
    """Stdlib-only loader. Unknown keys ignored. Missing file → defaults."""
    cfg = Config()
    cfg.config_path = path or config_path()
    cfg.config_dir = cfg.config_path.parent
    data: dict[str, Any] = {}
    if cfg.config_path.is_file():
        try:
            import tomllib
        except ImportError:
            tomllib = None  # type: ignore[assignment]
        if tomllib is not None:
            data = tomllib.loads(cfg.config_path.read_text())

    llm = data.get("llm") or {}
    if "host" in llm:
        cfg.llm.host = str(llm["host"])
    if "port" in llm:
        cfg.llm.port = int(llm["port"])
    if "alias" in llm:
        cfg.llm.alias = str(llm["alias"])
    if "tool_selection" in llm:
        cfg.llm.tool_selection = str(llm["tool_selection"])
    if "ctx_size" in llm:
        cfg.llm.ctx_size = int(llm["ctx_size"])
    if "n_gpu_layers" in llm:
        cfg.llm.n_gpu_layers = int(llm["n_gpu_layers"])
    if "temperature" in llm:
        cfg.llm.temperature = float(llm["temperature"])
    if "max_tokens" in llm:
        cfg.llm.max_tokens = int(llm["max_tokens"])
    if "max_tool_rounds" in llm:
        cfg.llm.max_tool_rounds = int(llm["max_tool_rounds"])
    if "timeout_secs" in llm:
        cfg.llm.timeout_secs = int(llm["timeout_secs"])
    if "llama_bin" in llm:
        cfg.llm.llama_bin = _expand(str(llm["llama_bin"]))
    env_bin = os.environ.get("AGAVAI_LLAMA_SERVER")
    if env_bin:
        cfg.llm.llama_bin = Path(env_bin)

    user_models = llm.get("models") or {}
    catalog: dict[str, ModelSpec] = dict(BUILTIN_MODELS)
    if isinstance(user_models, dict):
        for mid, spec in user_models.items():
            if not isinstance(spec, dict):
                continue
            base = catalog.get(str(mid))
            path_s = spec.get("path")
            path = _expand(str(path_s)) if path_s else (base.path if base else _default_model_path(str(mid) + ".gguf"))
            catalog[str(mid)] = ModelSpec(
                id=str(mid),
                path=path,
                description=str(spec.get("description") or (base.description if base else "")),
                download_url=(
                    str(spec["download_url"])
                    if spec.get("download_url")
                    else (base.download_url if base else None)
                ),
                expected_bytes=(
                    int(spec["expected_bytes"])
                    if spec.get("expected_bytes") is not None
                    else (base.expected_bytes if base else None)
                ),
                ctx_size=int(spec["ctx_size"]) if spec.get("ctx_size") is not None else (base.ctx_size if base else None),
                n_gpu_layers=(
                    int(spec["n_gpu_layers"])
                    if spec.get("n_gpu_layers") is not None
                    else (base.n_gpu_layers if base else None)
                ),
                builtin=base.builtin if base else False,
            )
    cfg.llm.models = catalog

    model_id = str(llm.get("model") or DEFAULT_MODEL_ID)
    cfg.llm.model_id = model_id
    spec = catalog.get(model_id)
    if spec:
        cfg.llm.model_path = spec.path
        if spec.ctx_size is not None:
            cfg.llm.ctx_size = spec.ctx_size
        if spec.n_gpu_layers is not None:
            cfg.llm.n_gpu_layers = spec.n_gpu_layers

    if "model_path" in llm:
        cfg.llm.model_path = _expand(str(llm["model_path"]))
        cfg.llm.path_overridden = True
    env_model = os.environ.get("AGAVAI_MODEL")
    if env_model:
        cfg.llm.model_path = _expand(env_model)
        cfg.llm.path_overridden = True

    files = data.get("files") or {}
    if "roots" in files:
        cfg.files.roots = [_expand(str(p)) for p in files["roots"]]
    if "max_results" in files:
        cfg.files.max_results = int(files["max_results"])
    tts = data.get("tts") or {}
    if "prefer" in tts or "engine" in tts:
        cfg.tts.prefer = str(tts.get("prefer") or tts.get("engine") or cfg.tts.prefer)
    if "voice" in tts:
        cfg.tts.voice = str(tts["voice"])
    if "model_path" in tts:
        cfg.tts.model_path = _expand(str(tts["model_path"]))
    if "voices_path" in tts:
        cfg.tts.voices_path = _expand(str(tts["voices_path"]))
    if "venv" in tts:
        cfg.tts.venv = _expand(str(tts["venv"]))
    a2a = data.get("a2a") or {}
    if "card_dir" in a2a:
        cfg.a2a_dir = _expand(str(a2a["card_dir"]))
    router = data.get("router") or {}
    if "backend" in router:
        cfg.router.backend = str(router["backend"])
    if "fallback" in router:
        cfg.router.fallback = str(router["fallback"])
    if "timeout_secs" in router:
        cfg.router.timeout_secs = int(router["timeout_secs"])
    if "max_tools" in router:
        cfg.router.max_tools = int(router["max_tools"])
    jev = router.get("jev") or {}
    if "base_url" in jev:
        cfg.router.jev_base_url = str(jev["base_url"])
    if "model" in jev:
        cfg.router.jev_model = str(jev["model"])
    if "api_key_env" in jev:
        cfg.router.api_key_env = str(jev["api_key_env"])
    vad = data.get("vad") or {}
    if "enabled" in vad:
        cfg.vad.enabled = bool(vad["enabled"])
    if "backend" in vad:
        cfg.vad.backend = str(vad["backend"])
    if "rate" in vad:
        cfg.vad.rate = int(vad["rate"])
    if "frame_ms" in vad:
        cfg.vad.frame_ms = int(vad["frame_ms"])
    if "open_threshold_dbfs" in vad:
        cfg.vad.open_threshold_dbfs = float(vad["open_threshold_dbfs"])
    if "close_threshold_dbfs" in vad:
        cfg.vad.close_threshold_dbfs = float(vad["close_threshold_dbfs"])
    if "noise_margin_db" in vad:
        cfg.vad.noise_margin_db = float(vad["noise_margin_db"])
    if "silence_ms" in vad:
        cfg.vad.silence_ms = int(vad["silence_ms"])
    if "min_speech_ms" in vad:
        cfg.vad.min_speech_ms = int(vad["min_speech_ms"])
    if "max_record_ms" in vad:
        cfg.vad.max_record_ms = int(vad["max_record_ms"])
    if "start_timeout_ms" in vad:
        cfg.vad.start_timeout_ms = int(vad["start_timeout_ms"])
    if "lead_in_ignore_ms" in vad:
        cfg.vad.lead_in_ignore_ms = int(vad["lead_in_ignore_ms"])
    if "model_path" in vad:
        cfg.vad.model_path = _expand(str(vad["model_path"]))
    if "threshold" in vad:
        cfg.vad.threshold = float(vad["threshold"])
    if "response_timeout_ms" in vad:
        cfg.vad.response_timeout_ms = int(vad["response_timeout_ms"])
    if "device" in vad:
        cfg.vad.device = str(vad["device"])
    if "venv" in vad:
        cfg.vad.venv = _expand(str(vad["venv"]))
    asr = data.get("asr") or {}
    if "device" in asr:
        cfg.asr.device = str(asr["device"])
    if "model_dir" in asr:
        cfg.asr.model_dir = _expand(str(asr["model_dir"]))
    if "venv" in asr:
        cfg.asr.venv = _expand(str(asr["venv"]))
    for key in ("backend", "endpoint", "mode", "language"):
        if key in asr:
            setattr(cfg.asr, key, str(asr[key]))
    for key in ("model_path", "runtime_library"):
        if key in asr:
            setattr(cfg.asr, key, _expand(str(asr[key])))
    if "chunk_ms" in asr:
        cfg.asr.chunk_ms = int(asr["chunk_ms"])
    for key in ("startup_timeout_secs", "finish_timeout_secs", "max_utterance_secs"):
        if key in asr:
            setattr(cfg.asr, key, float(asr[key]))
    from agavai.speech_backends import SPEECH_BACKENDS

    brain = data.get("brain") or {}
    if "cloud" in brain:
        raise ValueError("Cloud models are not supported yet; use brain.large for local fallback")
    for role, attr in (("small", "small_brain"), ("large", "large_brain")):
        if role in brain:
            setattr(cfg, attr, _load_brain_config(brain[role], f"brain.{role}", cfg))
    for tier in (cfg.llm, cfg.small_brain, cfg.large_brain):
        if tier and tier.tool_selection not in {"all", "routed"}:
            raise ValueError("Brain tool_selection must be all/routed")
    if cfg.router.backend not in {"jev", "keyword", "local", "none", "needle-cactus"}:
        raise ValueError(f"Unknown router backend: {cfg.router.backend}")
    if cfg.router.fallback not in {"keyword", "none"} or cfg.router.max_tools < 1 or cfg.router.timeout_secs <= 0:
        raise ValueError("Invalid router fallback, schema budget or timeout")
    if cfg.router.backend == "needle-cactus":
        small = cfg.small_brain or cfg.llm
        if "needle" not in router and small.backend == "needle-cactus":
            # Needle for both roles: the agent's own model routes, in the agent's call.
            cfg.router.needle = replace(small, timeout_secs=cfg.router.timeout_secs)
        elif "needle" not in router:
            raise ValueError("Needle routing needs [router.needle], or a Needle [brain.small] to share")
        else:
            cfg.router.needle = _load_brain_config(
                {**router["needle"], "backend": "needle-cactus", "timeout_secs": cfg.router.timeout_secs},
                "router.needle", cfg,
            )
    if cfg.asr.backend not in SPEECH_BACKENDS:
        raise ValueError(f"Unknown ASR backend: {cfg.asr.backend}")
    if cfg.asr.endpoint not in {"native", "manual", "vad"} or cfg.asr.mode not in {"streaming", "batch"}:
        raise ValueError("ASR endpoint must be native/manual/vad and mode must be streaming/batch")
    SPEECH_BACKENDS[cfg.asr.backend].validate_selection(cfg.asr)
    if cfg.asr.endpoint == "vad":
        from agavai.meter import check_streaming_vad
        check_streaming_vad(cfg.vad)
    if cfg.large_brain and (cfg.small_brain or cfg.llm).backend == cfg.large_brain.backend == "llama-server" and (cfg.small_brain or cfg.llm).base_url == cfg.large_brain.base_url:
        raise ValueError("Small and large llama-server models need distinct host/port endpoints")
    if not 20 <= cfg.asr.chunk_ms <= 5000 or min(cfg.asr.startup_timeout_secs, cfg.asr.finish_timeout_secs, cfg.asr.max_utterance_secs) <= 0:
        raise ValueError("Invalid ASR chunk size or deadline")
    overlay = data.get("overlay") or {}
    if "placement" in overlay:
        placement = str(overlay["placement"])
        if placement not in PLACEMENTS:
            raise ValueError(f"unknown [overlay] placement {placement!r}. known: {', '.join(PLACEMENTS)}")
        cfg.overlay.placement = placement
    recordings = data.get("recordings") or {}
    if "dir" in recordings:
        cfg.recordings.dir = _expand(str(recordings["dir"]))

    log = data.get("log") or {}
    if "level" in log:
        level = str(log["level"])
        if level not in LOG_LEVELS:
            raise ValueError(f"unknown [log] level {level!r}. known: {', '.join(LOG_LEVELS)}")
        cfg.log.level = level
    return cfg


def set_model_id(model_id: str, path: Path | None = None) -> Config:
    """Write `model = \"id\"` under [llm] and drop a competing model_path line."""
    cfg = load_config(path)
    if model_id not in cfg.llm.models:
        known = ", ".join(sorted(cfg.llm.models))
        raise ValueError(f"unknown model {model_id!r}. known: {known}")
    cfg_path = path or cfg.config_path
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    text = cfg_path.read_text() if cfg_path.is_file() else ""
    text = _upsert_llm_key(text, "model", model_id)
    text = _remove_llm_key(text, "model_path")
    cfg_path.write_text(text)
    return load_config(cfg_path)


def _upsert_llm_key(text: str, key: str, value: str) -> str:
    quoted = value.replace("\\", "\\\\").replace('"', '\\"')
    line = f'{key} = "{quoted}"'
    if re.search(r"^\[llm\]\s*$", text, re.M):
        pattern = rf"(?m)^[ \t]*{re.escape(key)}[ \t]*=[ \t]*.*$"
        if re.search(pattern, text):
            # Only replace the first occurrence (the [llm] table, not [llm.models.*]).
            llm_span = _llm_table_span(text)
            head, body, tail = text[: llm_span[0]], text[llm_span[0] : llm_span[1]], text[llm_span[1] :]
            body = re.sub(pattern, line, body, count=1)
            return head + body + tail
        start, end = _llm_table_span(text)
        insert_at = start + len(text[start:].split("\n", 1)[0]) + 1
        return text[:insert_at] + line + "\n" + text[insert_at:]
    if text and not text.endswith("\n"):
        text += "\n"
    return text + f"\n[llm]\n{line}\n"


def _remove_llm_key(text: str, key: str) -> str:
    start, end = _llm_table_span(text)
    if start == end == 0 and "[llm]" not in text:
        return text
    head, body, tail = text[:start], text[start:end], text[end:]
    body = re.sub(rf"(?m)^[ \t]*{re.escape(key)}[ \t]*=[ \t]*.*\n?", "", body)
    return head + body + tail


def _llm_table_span(text: str) -> tuple[int, int]:
    match = re.search(r"(?m)^\[llm\][ \t]*\n", text)
    if not match:
        return (0, 0)
    start = match.start()
    nxt = re.search(r"(?m)^\[", text[match.end() :])
    end = match.end() + nxt.start() if nxt else len(text)
    return (start, end)


def dump_llm_env(cfg: Config | None = None, role: str = "service") -> str:
    """Shell assignments for agavai-llm. Values are shlex-quoted."""
    cfg = cfg or load_config()
    model = cfg.llama_for_role(role)
    if model is None:
        return "ENGINE=none\n"
    pairs = {
        "ENGINE": "llama-server",
        "BIN": str(model.llama_bin),
        "MODEL": str(model.model_path),
        "HOST": model.host,
        "PORT": str(model.port),
        "CTX": str(model.ctx_size),
        "NGL": str(model.n_gpu_layers),
        "ALIAS": model.alias,
        "MODEL_ID": model.model_id,
    }
    return "".join(f"{k}={shlex.quote(v)}\n" for k, v in pairs.items())
