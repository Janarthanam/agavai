"""Keep the llama-server user services in step with the brain roles in config.toml.

Speech, Needle and Kokoro workers start with each listening session and need no
service. Only llama-server roles run under systemd: agavai-llm.service runs the
first llama role, and agavai-llm@large.service runs the larger one when both roles
use llama. scripts/agavai-llm records the settings it launched with, so a sync can
tell when a running server must restart.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

from agavai.config import Config, config_path, dump_llm_env, load_config, xdg_config

PRIMARY = "agavai-llm.service"
SECONDARY = "agavai-llm@large.service"
WATCHER = "agavai-config.path"
# The user services start without these terminal-only overrides.
TERMINAL_OVERRIDES = ("AGAVAI_MODEL", "AGAVAI_LLAMA_SERVER")


class ServiceError(RuntimeError):
    pass


def service_config_path() -> Path:
    return xdg_config() / "agavai" / "config.toml"


def service_config() -> Config:
    """The configuration the user services read, as they read it."""
    path = service_config_path()
    if config_path().resolve() != path.resolve():
        raise ServiceError(f"services read {path}; unset AGAVAI_CONFIG to manage them")
    saved = {name: os.environ.pop(name) for name in TERMINAL_OVERRIDES if name in os.environ}
    try:
        return load_config(path)
    finally:
        os.environ.update(saved)


def unit_roles(cfg: Config) -> dict[str, str | None]:
    """Each managed unit and the launcher role it runs, or None when no role needs it."""
    both = cfg.llama_for_role("small") is not None and cfg.llama_for_role("large") is not None
    return {
        PRIMARY: "service" if cfg.llama_for_role("service") is not None else None,
        SECONDARY: "large" if both else None,
    }


def role_label(cfg: Config, role: str) -> str:
    if role == "service" and cfg.llama_for_role("small") is not None:
        return "brain.small"
    return "brain.large"


def launch_record(cfg: Config, role: str) -> Path:
    """Written by scripts/agavai-llm just before it starts llama-server."""
    return cfg.runtime_dir / f"llm-{role}.env"


def _unit_file(unit: str) -> Path:
    name = unit.split("@", 1)[0] + "@.service" if "@" in unit else unit
    return xdg_config() / "systemd" / "user" / name


def _systemctl(*args: str) -> str:
    proc = subprocess.run(["systemctl", "--user", *args], capture_output=True, text=True)
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout).strip()
        raise ServiceError(f"systemctl --user {' '.join(args)} failed: {detail}")
    return proc.stdout.strip()


def _state(verb: str, unit: str) -> str:
    # is-active and is-enabled exit non-zero for the negative answers.
    proc = subprocess.run(["systemctl", "--user", verb, unit], capture_output=True, text=True)
    return proc.stdout.strip()


def _launched_settings(cfg: Config, role: str) -> str | None:
    record = launch_record(cfg, role)
    return record.read_text().strip() if record.is_file() else None


def _problems(cfg: Config, units: dict[str, str | None]) -> list[str]:
    problems = []
    for unit, role in units.items():
        if role is None:
            continue
        model = cfg.llama_for_role(role)
        label = role_label(cfg, role)
        if not _unit_file(unit).is_file():
            problems.append(f"{unit} is not installed; run scripts/install.sh")
        if not model.llama_bin.is_file() or not os.access(model.llama_bin, os.X_OK):
            problems.append(f"{label} needs an executable llama_bin: {model.llama_bin}")
        if not model.model_path.is_file():
            problems.append(f"{label} model is missing: {model.model_path}. "
                            f"Download it with: agavai download {model.model_id}")
    return problems


def sync(cfg: Config) -> list[str]:
    """Start, restart or stop each managed unit to match cfg. Returns one line per unit."""
    units = unit_roles(cfg)
    problems = _problems(cfg, units)
    if problems:
        raise ServiceError("; ".join(problems))
    lines = []
    for unit, role in units.items():
        active = _state("is-active", unit) == "active"
        enabled = _state("is-enabled", unit) == "enabled"
        if role is None:
            if active or enabled:
                _systemctl("disable", "--now", unit)
                lines.append(f"{unit}: stopped; no brain role needs it")
            else:
                lines.append(f"{unit}: not needed")
            continue
        label, model_id = role_label(cfg, role), cfg.llama_for_role(role).model_id
        if not active:
            _systemctl("enable", "--now", unit)
            lines.append(f"{unit}: started for {label} ({model_id})")
            continue
        if not enabled:
            _systemctl("enable", unit)
        if _launched_settings(cfg, role) != dump_llm_env(cfg, role).strip():
            _systemctl("restart", unit)
            lines.append(f"{unit}: restarted for {label} ({model_id}); its settings changed")
        else:
            lines.append(f"{unit}: running {label} ({model_id}), settings unchanged")
    return lines


def apply_config_change() -> list[str]:
    """Sync after a CLI command changed config.toml. Problems are reported, not raised:
    the configuration change itself already succeeded."""
    try:
        return sync(service_config())
    except (ServiceError, ValueError) as exc:
        return [f"services not updated: {exc}"]


def status_lines(cfg: Config) -> list[str]:
    """What sync would manage, without changing anything."""
    lines = []
    for unit, role in unit_roles(cfg).items():
        active = _state("is-active", unit) == "active"
        state = "active" if active else "inactive"
        if role is None:
            lines.append(f"{unit}: not needed ({state})")
            continue
        model = cfg.llama_for_role(role)
        need = f"needed for {role_label(cfg, role)} ({model.model_id} on {model.host}:{model.port})"
        if active and _launched_settings(cfg, role) != dump_llm_env(cfg, role).strip():
            state += ", settings changed since launch: run agavai services sync"
        lines.append(f"{unit}: {need}, {state}")
    watching = _state("is-active", WATCHER) == "active"
    lines.append(f"{WATCHER}: " + ("applies config.toml changes automatically" if watching
                                  else "inactive; run agavai services sync after editing config.toml"))
    return lines
