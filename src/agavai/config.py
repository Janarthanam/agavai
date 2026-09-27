from __future__ import annotations

import os
import re
import shlex
from dataclasses import dataclass, field
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


@dataclass
class Config:
    llm: LlmConfig = field(default_factory=LlmConfig)
    files: FilesConfig = field(default_factory=FilesConfig)
    tts: TtsConfig = field(default_factory=TtsConfig)

    @property
    def tts_prefer(self) -> str:
        return self.tts.prefer
    runtime_dir: Path = field(default_factory=lambda: xdg_runtime() / "agavai")
    config_dir: Path = field(default_factory=lambda: xdg_config() / "agavai")
    config_path: Path = field(default_factory=lambda: xdg_config() / "agavai" / "config.toml")
    a2a_dir: Path = field(default_factory=lambda: xdg_config() / "agavai/a2a")

    @property
    def prompt_file(self) -> Path:
        return self.runtime_dir / "prompt.txt"

    @property
    def state_file(self) -> Path:
        return self.runtime_dir / "state"


def config_path() -> Path:
    env = os.environ.get("AGAVAI_CONFIG")
    if env:
        return _expand(env)
    return xdg_config() / "agavai" / "config.toml"


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


def dump_llm_env(cfg: Config | None = None) -> str:
    """Shell assignments for agavai-llm. Values are shlex-quoted."""
    cfg = cfg or load_config()
    pairs = {
        "BIN": str(cfg.llm.llama_bin),
        "MODEL": str(cfg.llm.model_path),
        "HOST": cfg.llm.host,
        "PORT": str(cfg.llm.port),
        "CTX": str(cfg.llm.ctx_size),
        "NGL": str(cfg.llm.n_gpu_layers),
        "ALIAS": cfg.llm.alias,
        "MODEL_ID": cfg.llm.model_id,
    }
    return "".join(f"{k}={shlex.quote(v)}\n" for k, v in pairs.items())
