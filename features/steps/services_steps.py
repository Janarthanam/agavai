from pathlib import Path
from types import SimpleNamespace
import os
import shutil
import subprocess
import sys
import tempfile

from behave import given, when, then

from agavai.config import dump_llm_env, load_config

ROOT = Path(__file__).resolve().parents[2]

# Unit state lives in files: <unit>.active and <unit>.enabled.
FAKE_SYSTEMCTL = """#!/bin/sh
echo "$*" >> "$SERVICES_TEST_LOG"
shift
verb="$1"; shift
state="$SERVICES_TEST_STATE"
case "$verb" in
  is-active) if [ -e "$state/$1.active" ]; then echo active; exit 0; fi; echo inactive; exit 3 ;;
  is-enabled) if [ -e "$state/$1.enabled" ]; then echo enabled; exit 0; fi; echo disabled; exit 1 ;;
  enable) if [ "$1" = --now ]; then shift; touch "$state/$1.active"; fi; touch "$state/$1.enabled" ;;
  disable) if [ "$1" = --now ]; then shift; rm -f "$state/$1.active"; fi; rm -f "$state/$1.enabled" ;;
  restart) touch "$state/$1.active" ;;
esac
exit 0
"""

NEEDLE_SMALL = '''[brain.small]
backend = "needle-cactus"
model_path = "/cactus/needle3.cact"
'''
SMALL_QWEN = '''[brain.small]
backend = "llama-server"
model = "qwen3-4b-instruct"
model_path = "{qwen}"
llama_bin = "{binary}"
port = 18766
'''
LARGE_QWEN = '''[brain.large]
backend = "llama-server"
model = "qwen3-4b-instruct"
model_path = "{qwen}"
llama_bin = "{binary}"
port = 18766
'''
LARGE_BIG = '''[brain.large]
backend = "llama-server"
model = "big"
model_path = "{big}"
llama_bin = "{binary}"
port = 18767
'''
PROFILES = {
    "needle only": NEEDLE_SMALL,
    "needle with qwen fallback": NEEDLE_SMALL + LARGE_QWEN,
    "two llama roles": SMALL_QWEN + LARGE_BIG,
    "invalid": '[brain.small]\nbackend = "guess"\nmodel_path = "/m"\n',
    "missing fallback model": NEEDLE_SMALL + LARGE_QWEN.replace("{qwen}", "{missing}"),
    "uninstalled unit": NEEDLE_SMALL + LARGE_QWEN,
    "another config file": NEEDLE_SMALL + LARGE_QWEN,
}


@given('the services config "{profile}"')
def services_config(context, profile):
    tmp = tempfile.TemporaryDirectory()
    context.add_cleanup(tmp.cleanup)
    root = Path(tmp.name)
    svc = SimpleNamespace(root=root, profile=profile, config=root / "config/agavai/config.toml",
                          runtime=root / "run", state=root / "state", log=root / "systemctl.log")
    for folder in (svc.config.parent, svc.runtime, svc.state, root / "bin", root / "data"):
        folder.mkdir(parents=True)
    binary = root / "llama-server"
    binary.write_text("#!/bin/sh\nexit 0\n")
    binary.chmod(0o755)
    (root / "qwen.gguf").touch()
    (root / "big.gguf").touch()
    svc.config.write_text(PROFILES[profile].format(
        qwen=root / "qwen.gguf", big=root / "big.gguf", binary=binary, missing=root / "missing.gguf"))
    if profile != "uninstalled unit":
        shutil.copytree(ROOT / "systemd", root / "config/systemd/user")
    fake = root / "bin/systemctl"
    fake.write_text(FAKE_SYSTEMCTL)
    fake.chmod(0o755)
    env = {k: v for k, v in os.environ.items() if k not in {"AGAVAI_CONFIG", "AGAVAI_MODEL", "AGAVAI_LLAMA_SERVER"}}
    env.update(PATH=f"{root / 'bin'}:{os.environ['PATH']}", PYTHONPATH=str(ROOT / "src"), HOME=str(root),
               XDG_CONFIG_HOME=str(root / "config"), XDG_RUNTIME_DIR=str(svc.runtime), XDG_DATA_HOME=str(root / "data"),
               SERVICES_TEST_LOG=str(svc.log), SERVICES_TEST_STATE=str(svc.state))
    if profile == "another config file":
        other = root / "other.toml"
        other.write_text(svc.config.read_text())
        env["AGAVAI_CONFIG"] = str(other)
    svc.env = env
    context.svc = svc


def _running(context, unit):
    (context.svc.state / f"{unit}.active").touch()
    (context.svc.state / f"{unit}.enabled").touch()


@given('"{unit}" is running')
def unit_running(context, unit):
    _running(context, unit)


@given('"{unit}" is running with an older model')
def unit_running_older(context, unit):
    _running(context, unit)
    record = context.svc.runtime / "agavai/llm-service.env"
    record.parent.mkdir(parents=True, exist_ok=True)
    record.write_text("ENGINE=llama-server\nMODEL=/old/model.gguf\n")


@given('"{unit}" is running with the configured settings')
def unit_running_current(context, unit):
    _running(context, unit)
    record = context.svc.runtime / "agavai/llm-service.env"
    record.parent.mkdir(parents=True, exist_ok=True)
    record.write_text(dump_llm_env(load_config(context.svc.config), "service"))


@given('"{unit}" was started by the launcher')
def unit_started_by_launcher(context, unit):
    started = subprocess.run(["bash", str(ROOT / "scripts/agavai-llm")], capture_output=True, text=True,
                             env=context.svc.env, timeout=30)
    assert started.returncode == 0, started.stderr
    assert (context.svc.runtime / "agavai/llm-service.env").is_file()
    _running(context, unit)


def _run(context, action):
    context.svc.result = subprocess.run(
        [sys.executable, "-m", "agavai", "services", action],
        capture_output=True, text=True, env=context.svc.env, cwd=context.svc.root, timeout=30,
    )


@when("I sync the services")
def sync_services(context):
    _run(context, "sync")


@when("I show the services")
def show_services(context):
    _run(context, "status")


def _changes(context):
    calls = context.svc.log.read_text().splitlines() if context.svc.log.exists() else []
    calls = [c.removeprefix("--user ") for c in calls]
    return [c for c in calls if not c.startswith(("is-active", "is-enabled"))]


@then('the service changes are "{changes}"')
def service_changes(context, changes):
    assert _changes(context) == changes.split(";"), (_changes(context), context.svc.result.stderr)


@then("no service changes were made")
def no_service_changes(context):
    assert _changes(context) == [], _changes(context)


@then('sync reports "{text}"')
def sync_reports(context, text):
    output = context.svc.result.stdout + context.svc.result.stderr
    assert text in output, output


@then("sync returns {code:d}")
def sync_returns(context, code):
    assert context.svc.result.returncode == code, context.svc.result.stdout + context.svc.result.stderr


@then('the config watcher runs "{command}" when config.toml changes')
def config_watcher(context, command):
    watcher = (ROOT / "systemd/agavai-config.path").read_text()
    assert "PathChanged=%h/.config/agavai/config.toml" in watcher
    assert "Unit=agavai-sync.service" in watcher and "WantedBy=default.target" in watcher
    runner = (ROOT / "systemd/agavai-sync.service").read_text()
    assert "Type=oneshot" in runner and f"ExecStart=%h/.local/bin/{command}" in runner


@then("the larger llama role has its own service instance")
def larger_instance(context):
    template = (ROOT / "systemd/agavai-llm@.service").read_text()
    assert "ExecStart=%h/.local/bin/agavai-llm %i" in template
