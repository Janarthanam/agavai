from pathlib import Path
from types import SimpleNamespace
import os
import pty
import shlex
import shutil
import subprocess
import sys
import tempfile

from behave import given, when, then

from agavai.config import load_config
from agavai.router import routes_itself

ROOT = Path(__file__).resolve().parents[2]

# Each fake download script records its call and creates the files the real one installs.
FAKE_DOWNLOADS = {
    "setup-cactus.sh": ["agavai/cactus/whistle.cact", "agavai/cactus/needle3.cact",
                        "agavai/cactus/libneedle.so", "agavai/cactus/venv/bin/python"],
    "download-model.sh": ["agavai/models/Qwen3-4B-Instruct-2507-Q4_K_M.gguf"],
    "download-asr.sh": ["agavai/models/parakeet-realtime-eou-120m/encoder.onnx",
                        "agavai/models/parakeet-realtime-eou-120m/decoder_joint.onnx",
                        "agavai/models/parakeet-realtime-eou-120m/vocab.txt"],
    "download-tts.sh": ["agavai/tts/kokoro-v1.0.fp16.onnx", "agavai/tts/voices-v1.0.bin",
                        "agavai/tts-venv/bin/python"],
}

QWEN_PARAKEET = '''[llm]
model = "qwen3-4b-instruct"
llama_bin = "{binary}"

# Where file search looks.
[files]
roots = ["~/Notes"]
max_results = 7

[router]
backend = "jev"

[router.jev]
model = "typesafe/jev-1.13"

[asr]
backend = "parakeet-onnx"
endpoint = "native"

[tts]
prefer = "kokoro"
voice = "af_heart"
'''

NEEDLE_ONLY = '''[llm]
llama_bin = "{binary}"

[asr]
backend = "whistle-cactus"
endpoint = "vad"

[vad]
enabled = true
backend = "energy"

[router]
backend = "needle-cactus"

[brain.small]
backend = "needle-cactus"
model_path = "~/.local/share/agavai/cactus/needle3.cact"
runtime_library = "~/.local/share/agavai/cactus/libneedle.so"
venv = "~/.local/share/agavai/cactus/venv"

[tts]
voice = "af_heart"
'''


def _app(context, config_text, installed):
    tmp = tempfile.TemporaryDirectory()
    context.add_cleanup(tmp.cleanup)
    root = Path(tmp.name)
    app, home = root / "app", root / "home"
    for folder in ("src", "scripts", "share", "systemd"):
        shutil.copytree(ROOT / folder, app / folder, ignore=shutil.ignore_patterns("__pycache__"))
    data = home / ".local/share"
    for script, files in FAKE_DOWNLOADS.items():
        targets = " ".join(shlex.quote(f"$XDG_DATA_HOME/{f}") for f in files)
        (app / "scripts" / script).write_text(
            "#!/usr/bin/env bash\n"
            f'echo "{script}${{1:+ $1}}" >> "$SETUP_TEST_LOG"\n'
            f'if [ "${{SETUP_TEST_FAIL:-}}" = "{script}" ]; then exit 1; fi\n'
            f"for f in {targets.replace(chr(39), chr(34))}; do mkdir -p \"$(dirname \"$f\")\"; touch \"$f\"; done\n")
    for script in installed:
        for name in FAKE_DOWNLOADS[script]:
            (data / name).parent.mkdir(parents=True, exist_ok=True)
            (data / name).touch()
    binary = root / "llama-server"
    binary.write_text("#!/bin/sh\nexit 0\n")
    binary.chmod(0o755)
    config = home / ".config/agavai/config.toml"
    config.parent.mkdir(parents=True)
    (root / "big.gguf").touch()
    config.write_text(config_text.format(binary=binary, big=root / "big.gguf"))
    shutil.copytree(app / "systemd", home / ".config/systemd/user")
    (root / "bin").mkdir()
    shutil.copy2(ROOT / "features/support/fake-systemctl", root / "bin/systemctl")
    state = root / "state"
    state.mkdir()
    env = {k: v for k, v in os.environ.items() if k not in {"AGAVAI_CONFIG", "AGAVAI_MODEL", "AGAVAI_LLAMA_SERVER",
                                                           "AGAVAI_CACTUS_DIR"}}
    env.update(PATH=f"{root / 'bin'}:{os.environ['PATH']}", PYTHONPATH=str(app / "src"), HOME=str(home),
               XDG_CONFIG_HOME=str(home / ".config"), XDG_DATA_HOME=str(data), XDG_RUNTIME_DIR=str(root / "run"),
               SETUP_TEST_LOG=str(root / "downloads"), SERVICES_TEST_LOG=str(root / "systemctl.log"),
               SERVICES_TEST_CHANGES=str(root / "systemctl.changes"), SERVICES_TEST_STATE=str(state))
    context.cli = SimpleNamespace(root=root, app=app, config=config, original=config.read_text(), env=env, state=state)


@given("a Qwen and Parakeet setup with agavai-llm running")
def qwen_parakeet(context):
    _app(context, QWEN_PARAKEET, ["download-model.sh", "download-asr.sh", "download-tts.sh"])
    for suffix in ("active", "enabled"):
        (context.cli.state / f"agavai-llm.service.{suffix}").touch()


@given("a Qwen and Parakeet setup with a second GGUF")
def qwen_parakeet_big(context):
    _app(context, QWEN_PARAKEET + '\n[llm.models.big]\npath = "{big}"\ndescription = "Bigger local model"\n',
         ["download-model.sh", "download-asr.sh", "download-tts.sh"])
    for suffix in ("active", "enabled"):
        (context.cli.state / f"agavai-llm.service.{suffix}").touch()


@given("a Needle-only setup without Qwen downloaded")
def needle_only(context):
    _app(context, NEEDLE_ONLY, ["setup-cactus.sh", "download-tts.sh"])


@given("a Needle setup whose larger brain is a custom GGUF path")
def needle_custom_large(context):
    custom = '\n[brain.large]\nbackend = "llama-server"\nmodel = "custom"\nmodel_path = "{big}"\n'
    _app(context, NEEDLE_ONLY + custom, ["setup-cactus.sh", "download-tts.sh"])


@given("the Cactus download fails")
def cactus_fails(context):
    context.cli.env["SETUP_TEST_FAIL"] = "setup-cactus.sh"


def _agavai(context, args, stdin=None):
    context.cli.result = subprocess.run(
        [sys.executable, "-m", "agavai", *args], stdin=stdin, input=None if stdin else "",
        capture_output=True, text=True, env=context.cli.env, cwd=context.cli.root, timeout=60,
    )


@when('I run agavai setup with "{options}"')
def run_setup(context, options):
    _agavai(context, ["setup", *options.split()])


@when('I run agavai "{command}"')
def run_command(context, command):
    _agavai(context, command.split())


@when('I answer the setup questions with "{answers}"')
def answer_setup(context, answers):
    master, terminal = pty.openpty()
    try:
        os.write(master, ("\n".join(answers.split(",")) + "\n").encode())
        _agavai(context, ["setup"], stdin=terminal)
    finally:
        os.close(master)
        os.close(terminal)


@when('I explain the "{profile}" profile')
def explain_profile(context, profile):
    context.cli.env["AGAVAI_CONFIG"] = str(context.cli.app / "share" / profile)
    _agavai(context, ["explain"])


def _downloads(context):
    log = context.cli.root / "downloads"
    return log.read_text().splitlines() if log.exists() else []


def _service_changes(context):
    log = context.cli.root / "systemctl.changes"
    return log.read_text().splitlines() if log.exists() else []


@then('the downloads were "{scripts}"')
def downloads_were(context, scripts):
    assert _downloads(context) == scripts.split(";"), (_downloads(context), context.cli.result.stderr)


@then("no downloads ran")
def no_downloads(context):
    assert _downloads(context) == [], _downloads(context)


@then("the config selects Whistle and a Needle small brain that routes itself, with no larger brain")
def needle_selected(context):
    cfg = load_config(context.cli.config)
    assert cfg.asr.backend == "whistle-cactus" and cfg.asr.endpoint == "vad"
    assert cfg.small_brain.backend == "needle-cactus" and cfg.large_brain is None
    assert cfg.router.backend == "needle-cactus" and routes_itself(cfg.small_brain, cfg)
    text = context.cli.config.read_text()
    assert "[router.needle]" not in text and "[brain.large]" not in text


@then('the config has a "{model}" larger brain on port {port:d}')
def larger_selected(context, model, port):
    cfg = load_config(context.cli.config)
    assert cfg.large_brain.backend == "llama-server" and cfg.large_brain.model_id == model
    assert cfg.large_brain.port == port


@then('the config routes with "{router}" for a "{model}" small brain')
def small_llama_selected(context, router, model):
    cfg = load_config(context.cli.config)
    assert cfg.router.backend == router and cfg.large_brain is None
    assert cfg.small_brain.backend == "llama-server" and cfg.small_brain.model_id == model
    assert "[router.needle]" not in context.cli.config.read_text()


@then("the other config tables are unchanged")
def other_tables(context):
    text = context.cli.config.read_text()
    for kept in ('[llm]\nmodel = "qwen3-4b-instruct"', '# Where file search looks.\n[files]\nroots = ["~/Notes"]\nmax_results = 7',
                 '[router.jev]\nmodel = "typesafe/jev-1.13"', '[tts]\nprefer = "kokoro"\nvoice = "af_heart"'):
        assert kept in text, text


@then("the previous config is kept as a backup")
def backup_kept(context):
    backups = list(context.cli.config.parent.glob("config.toml.bak-*"))
    assert len(backups) == 1 and backups[0].read_text() == context.cli.original


@then("the config is unchanged")
def config_unchanged(context):
    assert context.cli.config.read_text() == context.cli.original
    assert not list(context.cli.config.parent.glob("config.toml.bak-*"))


@then('the setup service changes are "{changes}"')
def setup_service_changes(context, changes):
    assert _service_changes(context) == changes.split(";"), (_service_changes(context), context.cli.result.stdout)


@then("no setup service changes were made")
def no_setup_service_changes(context):
    assert _service_changes(context) == [], _service_changes(context)


@then('setup prints "{text}"')
def setup_prints(context, text):
    output = context.cli.result.stdout + context.cli.result.stderr
    assert text in " ".join(output.split()), output


@then("the setup command returns {code:d}")
def setup_returns(context, code):
    assert context.cli.result.returncode == code, context.cli.result.stdout + context.cli.result.stderr
