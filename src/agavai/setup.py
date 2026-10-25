"""Pick a model for each role, download it, and explain the resulting flow.

`agavai setup` rewrites only the role tables in config.toml ([asr], [router],
[router.needle], [brain.small], [brain.large], and [vad] when Whistle needs one)
and keeps the previous file as a timestamped backup. `agavai download` runs the
existing download scripts. `agavai explain` prints what happens to a request.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import textwrap
import time
from dataclasses import dataclass
from pathlib import Path

from agavai.config import Config, config_path, load_config, xdg_data
from agavai.router import has_jev_key, routes_itself
from agavai.services import PRIMARY, SECONDARY, apply_config_change, role_label, unit_roles
from agavai.tools import DISPATCH

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
SPEECH = ("parakeet", "whistle")
ROUTERS = ("needle", "keyword", "jev", "none")
ROUTER_NAMES = {"needle-cactus": "needle", "keyword": "keyword", "local": "keyword", "jev": "jev", "none": "none"}


class SetupError(RuntimeError):
    pass


def cactus_dir() -> Path:
    # scripts/setup-cactus.sh installs here.
    return Path(os.environ.get("AGAVAI_CACTUS_DIR") or xdg_data() / "agavai" / "cactus")


@dataclass(frozen=True)
class Download:
    id: str
    summary: str
    size: str
    command: tuple[str, ...]  # a script under scripts/ and its arguments; empty when there is no source
    files: tuple[Path, ...]
    requires: tuple[str, ...] = ()

    def installed(self) -> bool:
        return all(path.is_file() for path in self.files)


def downloads(cfg: Config) -> dict[str, Download]:
    cactus = cactus_dir()
    runtime = (cactus / "libneedle.so", cactus / "venv/bin/python")
    parakeet = Path(cfg.asr.model_dir)
    items = [
        Download("whistle", "Whistle speech recognition: 7 languages, CPU", "17 MB + 50 MB Cactus runtime",
                 ("setup-cactus.sh",), (cactus / "whistle.cact", *runtime)),
        Download("needle3", "Needle 3 tool calling: picks a tool and fills its arguments", "35 MB + 50 MB Cactus runtime",
                 ("setup-cactus.sh",), (cactus / "needle3.cact", *runtime)),
        Download("parakeet", "Parakeet-EOU-120M speech recognition: English, hears the sentence end", "481 MB",
                 ("download-asr.sh",), tuple(parakeet / name for name in ("encoder.onnx", "decoder_joint.onnx", "vocab.txt")),
                 requires=("kokoro",)),
        Download("kokoro", "Kokoro-82M voice, and the speech runtime Parakeet also uses", "192 MB + 150 MB runtime",
                 ("download-tts.sh",), (cfg.tts.model_path, cfg.tts.voices_path, cfg.tts.venv / "bin/python")),
    ]
    for mid, spec in sorted(cfg.llm.models.items()):
        size = f"{spec.expected_bytes / 1e9:.1f} GB" if spec.expected_bytes else "size unknown"
        summary = spec.description.split(". ")[0] if spec.description else f"{mid} for llama-server"
        command = ("download-model.sh", mid) if spec.download_url and spec.expected_bytes else ()
        items.append(Download(mid, summary, size, command, (spec.path,)))
    return {item.id: item for item in items}


def run_downloads(cfg: Config, ids: list[str]) -> list[str]:
    """Run each needed script once, in order. Returns the scripts that ran."""
    catalog = downloads(cfg)
    commands: list[tuple[str, ...]] = []
    for mid in ids:
        item = catalog[mid]
        for dependency in item.requires:
            if not catalog[dependency].installed() and catalog[dependency].command not in commands:
                commands.append(catalog[dependency].command)
        if not item.command:
            raise SetupError(f"{mid} has no download source; put the file at {item.files[0]}")
        if item.command not in commands:
            commands.append(item.command)
    for command in commands:
        script, *arguments = command
        if subprocess.run(["bash", str(SCRIPTS / script), *arguments]).returncode != 0:
            raise SetupError(f"{script} failed")
    return [" ".join(command) for command in commands]


@dataclass
class Selection:
    speech: str  # parakeet | whistle
    small: str   # needle | a GGUF id
    large: str   # none | a GGUF id
    router: str  # needle | keyword | jev | none


def current_selection(cfg: Config) -> Selection:
    small = cfg.small_brain or cfg.llm
    large = cfg.large_brain
    return Selection(
        speech="whistle" if cfg.asr.backend == "whistle-cactus" else "parakeet",
        small="needle" if small.backend == "needle-cactus" else small.model_id,
        large="none" if large is None else ("needle" if large.backend == "needle-cactus" else large.model_id),
        router=ROUTER_NAMES[cfg.router.backend],
    )


def default_router(small: str, current: Selection) -> str:
    if small == "needle":
        return "needle"  # Needle routes itself in its own inference.
    if current.small == "needle" and current.router == "needle":
        return "keyword"  # the shared Needle router goes away with the Needle agent
    return current.router


def needed_downloads(cfg: Config, sel: Selection) -> list[str]:
    ids = ["whistle" if sel.speech == "whistle" else "parakeet"]
    ids.append("needle3" if sel.small == "needle" else sel.small)
    if sel.router == "needle" and sel.small != "needle":
        ids.append("needle3")
    if sel.large != "none":
        ids.append("needle3" if sel.large == "needle" else sel.large)
    if cfg.tts.prefer == "kokoro":
        ids.append("kokoro")
    catalog = downloads(cfg)
    missing = []
    for mid in dict.fromkeys(ids):
        item = catalog.get(mid)
        # A model outside the catalog was configured by path; the user manages that file.
        if item is not None and (not item.installed() or any(not catalog[d].installed() for d in item.requires)):
            missing.append(mid)
    return missing


def _toml_value(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, Path):
        home = Path.home()
        value = "~/" + str(value.relative_to(home)) if value.is_relative_to(home) else str(value)
    # TOML basic strings use JSON's escapes.
    return json.dumps(str(value))


def _table(name: str, values: dict) -> str:
    return f"[{name}]\n" + "".join(f"{key} = {_toml_value(value)}\n" for key, value in values.items())


def _needle(cactus: Path) -> dict:
    return {"backend": "needle-cactus", "model": "needle3", "model_path": cactus / "needle3.cact",
            "runtime_library": cactus / "libneedle.so", "venv": cactus / "venv"}


def _brain(choice: str, port: int, alias: str, cactus: Path) -> dict:
    if choice == "needle":
        return {**_needle(cactus), "timeout_secs": 10, "max_tokens": 512, "max_tool_rounds": 6}
    return {"backend": "llama-server", "model": choice, "host": "127.0.0.1", "port": port, "alias": alias,
            "tool_selection": "routed"}


def role_tables(sel: Selection, current: Selection, cfg: Config, existing: set[str]) -> dict[str, str | None]:
    """New text for the tables of each role that changes; None removes a table."""
    cactus = cactus_dir()
    tables: dict[str, str | None] = {}
    if sel.speech != current.speech and sel.speech == "whistle":
        tables["asr"] = _table("asr", {
            "backend": "whistle-cactus", "model_path": cactus / "whistle.cact", "runtime_library": cactus / "libneedle.so",
            "venv": cactus / "venv", "device": "cpu", "endpoint": "vad", "mode": "streaming"})
        if "vad" not in existing:
            tables["vad"] = _table("vad", {"enabled": True, "backend": "energy", "silence_ms": 900,
                                           "min_speech_ms": 250, "max_record_ms": 120000})
    elif sel.speech != current.speech:
        tables["asr"] = _table("asr", {
            "backend": "parakeet-onnx", "model_dir": Path(cfg.asr.model_dir), "venv": cfg.tts.venv,
            "device": "cpu", "endpoint": "native", "mode": "streaming"})
    small_changed = sel.small != current.small
    small_llama = sel.small != "needle"
    if small_changed:
        tables["brain.small"] = _table("brain.small", _brain(sel.small, 18766, "agavai", cactus))
    # Two llama roles need distinct ports, so a new llama small brain moves the larger one.
    if sel.large != current.large or (small_changed and small_llama and sel.large not in {"none", "needle"}):
        port, alias = (18767, "agavai-large") if small_llama else (18766, "agavai")
        tables["brain.large"] = None if sel.large == "none" else _table("brain.large", _brain(sel.large, port, alias, cactus))
    if sel.router != current.router or small_changed:
        backend = {"needle": "needle-cactus"}.get(sel.router, sel.router)
        timeout = 10 if sel.router == "needle" else 2
        tables["router"] = _table("router", {"backend": backend, "fallback": "keyword", "max_tools": 8,
                                             "timeout_secs": timeout})
        # A Needle agent shares the router's model, so only a separate Needle router needs its own table.
        needs_own = sel.router == "needle" and small_llama
        tables["router.needle"] = _table("router.needle", {**_needle(cactus), "max_tokens": 512}) if needs_own else None
    return tables


HEADER = re.compile(r"^\s*\[([^\[\]]+)\]\s*(?:#.*)?$")


def table_names(text: str) -> set[str]:
    return {m.group(1).strip() for line in text.splitlines() if (m := HEADER.match(line))}


def rewrite_tables(text: str, tables: dict[str, str | None]) -> str:
    """Replace or remove whole tables, keeping every other line as it was.

    Comments and blank lines after a replaced table's last key stay, since they
    usually introduce the next table. Tables not yet in the file are appended."""
    blocks: list[tuple[str | None, list[str]]] = [(None, [])]
    for line in text.splitlines(keepends=True):
        match = HEADER.match(line)
        if match:
            blocks.append((match.group(1).strip(), [line]))
        else:
            blocks[-1][1].append(line)
    out, written = [], set()
    for name, lines in blocks:
        if name not in tables:
            out.append("".join(lines))
            continue
        end = len(lines)
        while end > 1 and (not lines[end - 1].strip() or lines[end - 1].lstrip().startswith("#")):
            end -= 1
        if tables[name] is not None and name not in written:
            out.append(tables[name])
            written.add(name)
        out.append("".join(lines[end:]))
    result = "".join(out)
    for name, body in tables.items():
        if body is not None and name not in written:
            result = result.rstrip("\n") + "\n\n" + body
    return result


@dataclass
class Plan:
    path: Path
    current: Selection
    selection: Selection
    text: str  # the config as it will be written; unchanged when the selection is
    cfg: Config  # the validated result
    downloads: list[str]
    changed_tables: list[str]
    removed_tables: list[str]

    @property
    def changes_config(self) -> bool:
        return self.selection != self.current


def make_plan(sel_args: dict, ask=None) -> Plan:
    """Build the plan. ask(role, cfg, default, small=None) chooses unspecified roles; without it they stay."""
    path = config_path()
    base = path.read_text() if path.is_file() else (ROOT / "share/config.example.toml").read_text()
    cfg = load_config(path) if path.is_file() else _load_text(base, path)
    current = current_selection(cfg)
    speech = sel_args.get("speech") or (ask("speech", cfg, current.speech) if ask else current.speech)
    small = sel_args.get("small") or (ask("small", cfg, current.small) if ask else current.small)
    router_default = default_router(small, current)
    router = sel_args.get("router") or (ask("router", cfg, router_default, small=small) if ask else router_default)
    large = sel_args.get("large") or (ask("large", cfg, current.large) if ask else current.large)
    sel = Selection(speech, small, large, router)
    _check_choices(cfg, sel, current)
    if sel == current:
        return Plan(path, current, sel, base, cfg, needed_downloads(cfg, sel), [], [])
    existing = table_names(base)
    tables = role_tables(sel, current, cfg, existing)
    text = rewrite_tables(base, tables)
    try:
        new_cfg = _load_text(text, path)
    except ValueError as exc:
        raise SetupError(f"the new configuration would not load: {exc}") from exc
    changed = [name for name, body in tables.items() if body is not None]
    removed = [name for name, body in tables.items() if body is None and name in existing]
    return Plan(path, current, sel, text, new_cfg, needed_downloads(new_cfg, sel), changed, removed)


def _load_text(text: str, path: Path) -> Config:
    """Load config text as if it were saved at path, without touching path."""
    with tempfile.NamedTemporaryFile("w", suffix=".toml") as trial:
        trial.write(text)
        trial.flush()
        cfg = load_config(Path(trial.name))
    cfg.config_path, cfg.config_dir = path, path.parent
    return cfg


def _check_choices(cfg: Config, sel: Selection, current: Selection) -> None:
    """Check the roles that change; unchanged roles keep whatever the file already says."""
    ggufs = sorted(cfg.llm.models)
    if sel.speech != current.speech and sel.speech not in SPEECH:
        raise SetupError(f"speech must be parakeet or whistle, not {sel.speech!r}")
    if sel.small != current.small and sel.small not in {"needle", *ggufs}:
        raise SetupError(f"small brain must be needle or one of {', '.join(ggufs)}, not {sel.small!r}")
    if sel.large != current.large and sel.large not in {"none", "needle", *ggufs}:
        raise SetupError(f"larger brain must be none or one of {', '.join(ggufs)}, not {sel.large!r}")
    if sel.router != current.router and sel.router not in ROUTERS:
        raise SetupError(f"router must be one of {', '.join(ROUTERS)}, not {sel.router!r}")
    if sel.small != "needle" and sel.small == sel.large:
        raise SetupError("the larger brain must be a different model from the small one")
    new_ggufs = {role for role in (sel.small, sel.large) if role in ggufs} - {current.small, current.large}
    if new_ggufs:
        binary = cfg.llm.llama_bin
        if not binary.is_file() or not os.access(binary, os.X_OK):
            raise SetupError(f"a GGUF brain needs llama-server; set [llm] llama_bin (now {binary})")


def apply_plan(plan: Plan) -> list[str]:
    """Download, then write the config, then sync services. Returns a report."""
    report = []
    if plan.downloads:
        ran = run_downloads(plan.cfg, plan.downloads)
        report.append("Downloaded: " + ", ".join(ran))
    if plan.changes_config:
        if plan.path.is_file():
            backup = plan.path.with_name(f"{plan.path.name}.bak-{time.strftime('%Y%m%d-%H%M%S')}")
            shutil.copy2(plan.path, backup)
            report.append(f"Previous config saved as {backup}")
        plan.path.parent.mkdir(parents=True, exist_ok=True)
        trial = plan.path.with_name(f".{plan.path.name}.setup")
        trial.write_text(plan.text)
        os.replace(trial, plan.path)
        report.append(f"Wrote {plan.path}")
    report += apply_config_change()
    return report


def describe_plan(plan: Plan) -> list[str]:
    lines = ["Plan"]
    catalog = downloads(plan.cfg)
    if plan.downloads:
        lines.append("  Download:  " + ", ".join(f"{mid} ({catalog[mid].size})" for mid in plan.downloads))
    else:
        lines.append("  Download:  nothing; every model is installed")
    if plan.changes_config:
        lines.append(f"  Config:    {plan.path}")
        lines.append("             writes " + ", ".join(f"[{name}]" for name in plan.changed_tables)
                     + ("; removes " + ", ".join(f"[{name}]" for name in plan.removed_tables) if plan.removed_tables else ""))
        lines.append("             keeps every other table, and saves the previous file as a backup")
    else:
        lines.append("  Config:    unchanged")
    lines.append("  Services:  agavai services sync starts or stops llama-server to match")
    return lines


QUESTIONS = {
    "speech": "Speech input: what turns your voice into text",
    "small": "Small brain: the first model to handle each request",
    "router": "Router: which tools the small brain gets to see",
    "large": "Larger brain: takes over when the small brain cannot handle a request",
}


def role_options(role: str, cfg: Config, small: str | None = None) -> list[tuple[str, str]]:
    catalog = downloads(cfg)
    tools = len(DISPATCH)

    def state(mid: str) -> str:
        item = catalog[mid]
        return " [installed]" if item.installed() else f" [download {item.size}]"

    ggufs = sorted(cfg.llm.models)
    if role == "speech":
        return [("parakeet", "Parakeet-EOU-120M, English. Sends when it hears your sentence end." + state("parakeet")),
                ("whistle", "Whistle, 7 languages. Sends after 900 ms of quiet." + state("whistle"))]
    if role == "small":
        return [("needle", "Needle 3 picks a tool and its arguments in one pass. Calls tools only; cannot chat."
                 + state("needle3")),
                *[(mid, f"{catalog[mid].summary} on llama-server: chats, answers and calls tools; slower."
                   + state(mid)) for mid in ggufs]]
    if role == "router":
        own = (f"Needle chooses among all {tools} tools itself, in the same inference." if small == "needle"
               else "Needle 3 picks up to two tool groups for the small brain." + state("needle3"))
        return [("needle", own), ("keyword", "Word matching picks up to two tool groups, offline."),
                ("jev", "Jev on OpenRouter picks the group; sends your request text off this machine "
                        "and needs OPENROUTER_API_KEY."),
                ("none", f"No routing: the small brain sees all {tools} tools.")]
    return [("none", "No fallback; no llama-server runs for this role."),
            *[(mid, f"{catalog[mid].summary} on llama-server, kept running as a service." + state(mid))
              for mid in ggufs]]


def ask_role(role: str, cfg: Config, default: str, small: str | None = None, read=input) -> str:
    options = role_options(role, cfg, small)
    names = [mid for mid, _ in options]
    print(f"\n{QUESTIONS[role]}")
    for mid, text in options:
        print(f"  {mid:20} {text}")
    while True:
        try:
            answer = read(f"Choose [{default}]: ").strip()
        except EOFError:
            return default
        if not answer:
            return default
        if answer in names:
            return answer
        print(f"  Choose one of: {', '.join(names)}")


def run_setup(choices: dict, *, yes: bool, dry_run: bool, interactive: bool, read=input) -> int:
    """With a terminal and no role options, ask about each role; otherwise unnamed roles stay."""
    ask = None
    if interactive and not any(choices.values()):
        def ask(role, cfg, default, small=None):
            return ask_role(role, cfg, default, small, read)
    plan = make_plan(choices, ask)
    print("\n" + "\n".join(describe_plan(plan)) + "\n")
    print("\n".join(walkthrough(plan.cfg)) + "\n")
    if not plan.downloads and not plan.changes_config:
        print("Nothing to change.")
        return 0
    if dry_run:
        print("Dry run: nothing changed.")
        return 0
    if not yes:
        if not interactive:
            print("Run again with --yes to apply, or from a terminal to confirm.")
            return 2
        if read("Apply? [Y/n] ").strip().lower() not in {"", "y", "yes"}:
            print("Nothing changed.")
            return 1
    print("\n".join(apply_plan(plan)))
    print("Run agavai explain to see this walkthrough again.")
    return 0


# ---------- walkthrough ----------

REPLY = {
    "kokoro": "Kokoro speaks the reply from a voice worker kept warm between requests; eSpeak or a notification takes over if it cannot.",
    "espeak": "eSpeak speaks the reply; a notification takes over if it cannot.",
    "notify": "The reply appears as a notification and in the overlay.",
}


def _step(label: str, text: str) -> list[str]:
    return textwrap.wrap(text, width=96, initial_indent=f"{label:<13}", subsequent_indent=" " * 13,
                         break_on_hyphens=False)


def _unit(cfg: Config, tier: str) -> str:
    return SECONDARY if tier == "large" and cfg.llama_for_role("small") is not None else PRIMARY


def _brain_name(tier) -> str:
    return "Needle 3" if tier.backend == "needle-cactus" else tier.model_id


def _router_phrase(cfg: Config) -> str:
    """Who picks the tool groups, as a noun phrase."""
    if cfg.router.backend == "jev":
        if not has_jev_key(cfg):
            return "word matching (Jev is selected, but no OpenRouter key is set)"
        return "Jev on OpenRouter (your request text leaves this machine)"
    if cfg.router.backend == "needle-cactus":
        return "Needle 3 in a brain worker"
    return "word matching"


def _capitalized(text: str) -> str:
    return text[:1].upper() + text[1:]


def _decide(cfg: Config, small) -> str:
    tools = len(DISPATCH)
    all_tools = small.tool_selection == "all" or cfg.router.backend == "none"
    if small.backend == "needle-cactus":
        if routes_itself(small, cfg):
            return (f"Needle 3 runs in a brain worker started with the session. In one inference it is both router and "
                    f"agent: it picks the tool from all {tools} and fills in its arguments.")
        if all_tools:
            return f"Needle 3 runs in a brain worker and picks from all {tools} tools in one inference; no router runs."
        return (f"{_capitalized(_router_phrase(cfg))} picks up to two tool groups, then Needle 3 in a brain worker "
                f"picks the call from those tools. That is two steps before anything runs.")
    unit = _unit(cfg, "small")
    if all_tools:
        return (f"{small.model_id} on llama-server ({unit}) sees all {tools} tools and writes the calls; after they run, "
                f"it writes the reply. A tool request takes two model steps.")
    return (f"{_capitalized(_router_phrase(cfg))} picks up to two tool groups, then {small.model_id} on llama-server "
            f"({unit}) writes the calls; after they run, it writes the reply. A tool request takes two model steps.")


def _fallback(cfg: Config, small, large) -> str:
    if large is None:
        then = "suggests a desktop request" if small.backend == "needle-cactus" else "asks you to rephrase it"
        text = f"No larger brain is configured. If {_brain_name(small)} cannot handle a request, Agavai says so and {then}."
        if not any(unit_roles(cfg).values()):
            text += " No llama-server runs at all."
        return text
    if large.tool_selection == "all" or cfg.router.backend == "none":
        tools = "all tools"
    elif routes_itself(small, cfg):
        tools = ("tool groups from word matching" if cfg.router.fallback == "keyword"
                 else "no tools, though it can still answer questions")
    else:
        tools = "tool groups from " + _router_phrase(cfg)
    where = "a brain worker" if large.backend == "needle-cactus" else f"llama-server ({_unit(cfg, 'large')})"
    return (f"If {_brain_name(small)} finds no tool or fails, {_brain_name(large)} on {where} takes over with the "
            f"same history and {tools}. Only those requests reach it, but its server stays loaded.")


def used_models(cfg: Config) -> list[str]:
    small = cfg.small_brain or cfg.llm
    ids = ["whistle" if cfg.asr.backend == "whistle-cactus" else "parakeet", _model_id(small)]
    if cfg.router.backend == "needle-cactus":
        ids.append("needle3")
    if cfg.large_brain is not None:
        ids.append(_model_id(cfg.large_brain))
    if cfg.tts.prefer == "kokoro":
        ids.append("kokoro")
    return list(dict.fromkeys(ids))


def _model_id(tier) -> str:
    return "needle3" if tier.backend == "needle-cactus" else tier.model_id


def walkthrough(cfg: Config) -> list[str]:
    small, large = cfg.small_brain or cfg.llm, cfg.large_brain
    lines = [f"How Agavai handles a request with {cfg.config_path}", ""]
    if cfg.asr.backend == "whistle-cactus":
        end = (f"{cfg.vad.silence_ms} ms of quiet sends the request, or Enter sooner" if cfg.asr.endpoint == "vad"
               else "pressing Enter sends the request")
        shown = "Words appear while you speak" if cfg.asr.mode == "streaming" else "The words appear when you finish"
        lines += _step("1. Listen", f"Whistle runs in a speech worker started with each listening session. {shown}; "
                                    f"{end}. Escape cancels.")
    else:
        lines += _step("1. Listen", "Parakeet-EOU-120M runs in a speech worker started with each listening session. "
                                    "Words appear while you speak, and the model sends the request when it hears the "
                                    "sentence end. Enter sends sooner; Escape cancels.")
    lines += _step("2. Decide", _decide(cfg, small))
    lines += _step("3. Act", f"The session checks each call against the {len(DISPATCH)}-tool allowlist, asks you first "
                             f"when a tool needs confirmation, and runs it. Models never run commands themselves.")
    lines += _step("4. Fallback", _fallback(cfg, small, large))
    lines += _step("5. Reply", REPLY.get(cfg.tts.prefer, REPLY["kokoro"]))
    lines.append("")
    running = [f"{unit} for {role_label(cfg, role)} ({cfg.llama_for_role(role).model_id})"
               for unit, role in unit_roles(cfg).items() if role]
    lines += _step("Always on", "; ".join(running) if running else "No model service. Between requests only the overlay runs.")
    workers = ["speech worker", *(["brain worker"] if "needle3" in used_models(cfg) else []),
               *(["Kokoro voice"] if cfg.tts.prefer == "kokoro" else [])]
    lines += _step("Per session", ", ".join(workers) + "; they start with listening and stop with it.")
    sends = cfg.router.backend == "jev" and has_jev_key(cfg)
    lines += _step("Network", "Your request text goes to OpenRouter for Jev routing." if sends
                   else "Nothing leaves this machine.")
    catalog = downloads(cfg)
    states = []
    for mid in used_models(cfg):
        item = catalog.get(mid)
        if item is None:
            states.append(f"{mid} (custom path)")
        else:
            states.append(f"{mid} " + ("installed" if item.installed() else f"missing: agavai download {mid}"))
    lines += _step("Models", ", ".join(states))
    return lines


def download_list(cfg: Config) -> list[str]:
    used = set(used_models(cfg))
    lines = []
    for item in downloads(cfg).values():
        state = "installed" if item.installed() else ("no source" if not item.command else "not installed")
        mark = "*" if item.id in used else " "
        lines.append(f"{mark} {item.id:20} {state:14} {item.size:30} {item.summary}")
    lines.append("* used by the current configuration. Download with: agavai download <id> ...")
    return lines
