from pathlib import Path
import os
import shutil
import subprocess
import tempfile
import pty

from behave import when, then


def run_setup(context, args, failure=""):
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        scripts = root / "scripts"
        scripts.mkdir()
        shutil.copyfile("scripts/setup.sh", scripts / "setup.sh")
        log = root / "calls"
        for name in ("configure", "download-model", "download-asr", "download-tts", "install"):
            label = 'configure${1:+ $1}' if name == "configure" else name
            (scripts / f"{name}.sh").write_text(
                f'echo "{label}" >> "$SETUP_TEST_LOG"\nexit {int(name == failure)}\n'
            )
        bin_dir = root / "bin"
        bin_dir.mkdir()
        for name in ("python3", "omarchy", "systemctl", "curl", "uv"):
            path = bin_dir / name
            path.write_text("#!/bin/sh\nexit 0\n")
            path.chmod(0o755)
        env = dict(os.environ, PATH=f"{bin_dir}:{os.environ['PATH']}", SETUP_TEST_LOG=str(log))
        context.setup_result = subprocess.run(
            ["bash", str(scripts / "setup.sh"), *args], input="",
            capture_output=True, text=True, env=env,
        )
        context.setup_operations = log.read_text().splitlines() if log.exists() else []


@when('I run setup selecting "{choice}"')
def setup_choice(context, choice):
    run_setup(context, ["--models", choice])


@when("I run setup with no selection")
def setup_no_choice(context):
    run_setup(context, [])


@when("configuration fails during setup")
def setup_failed_config(context):
    run_setup(context, ["--models", "all"], "configure")


@when("a model download fails during setup")
def setup_failed_download(context):
    run_setup(context, ["--models", "all"], "download-model")


@when("I run setup accepting existing configuration")
def setup_existing(context):
    run_setup(context, ["--models", "none", "--configured"])


@then('setup operations are "{operations}"')
def setup_operations(context, operations):
    assert context.setup_operations == operations.split(","), context.setup_operations


@then("setup operations are empty")
def setup_no_operations(context):
    assert context.setup_operations == [], context.setup_operations


@then("setup returns {code:d}")
def setup_status(context, code):
    assert context.setup_result.returncode == code, context.setup_result.stderr


def run_install(context, state, start_fails=False, editor_status=None):
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        home = root / "home"
        home.mkdir()
        app = root / "app"
        for folder in ("scripts", "share", "plugin", "systemd", "src"):
            shutil.copytree(folder, app / folder, ignore=shutil.ignore_patterns("__pycache__"))
        config = home / ".config/agavai/config.toml"
        config.parent.mkdir(parents=True)
        binary = root / "llama-server"
        binary.write_text("#!/bin/sh\nexit 0\n")
        binary.chmod(0o755)
        model = root / "model.gguf"
        model.touch()
        if state != "missing":
            config.write_text(f'[llm]\nllama_bin = "{binary}"\nmodel_path = "{model}"\n')
        if state == "malformed":
            config.write_text("[llm\n")
        elif state == "missing binary":
            binary.unlink()
        elif state == "missing model":
            model.unlink()
        log = root / "services"
        bin_dir = root / "bin"
        bin_dir.mkdir()
        for name in ("systemctl", "omarchy", "omarchy-shell", "gtk-update-icon-cache", "update-desktop-database"):
            command = bin_dir / name
            text = '#!/bin/sh\n'
            if name == "systemctl":
                text += 'echo "$*" >> "$SETUP_TEST_LOG"\n'
                if start_fails:
                    text += 'if [ "$*" = "--user enable --now agavai-llm.service" ]; then exit 1; fi\n'
            command.write_text(text + "exit 0\n")
            command.chmod(0o755)
        env = dict(os.environ, HOME=str(home), XDG_CONFIG_HOME=str(home / ".config"),
                   XDG_DATA_HOME=str(home / ".local/share"), SETUP_TEST_LOG=str(log),
                   PATH=f"{bin_dir}:{os.environ['PATH']}")
        args = ["bash", str(app / "scripts/install.sh")]
        if editor_status is None:
            context.setup_result = subprocess.run(
                [*args, "--configured"], input="", capture_output=True, text=True, env=env,
            )
        else:
            saved = root / "edited.toml"
            saved.write_text(f'[llm]\nllama_bin = "{binary}"\nmodel_path = "{model}"\n[tts]\nvoice = "af_heart"\n')
            editor = bin_dir / "test-editor"
            editor.write_text(f'#!/bin/sh\ncp "$SETUP_TEST_CONFIG" "$1"\nexit {editor_status}\n')
            editor.chmod(0o755)
            env.update(VISUAL=str(editor), SETUP_TEST_CONFIG=str(saved))
            master, terminal = pty.openpty()
            try:
                context.setup_result = subprocess.run(
                    args, stdin=terminal, capture_output=True, text=True, env=env, timeout=10,
                )
            finally:
                os.close(master)
                os.close(terminal)
            context.edited_config = config.read_text()
        context.service_commands = log.read_text().splitlines() if log.exists() else []
        context.service_exists = (home / ".config/systemd/user/agavai-llm.service").is_file()


@when('I install with "{state}" configuration')
def install_config(context, state):
    run_install(context, state)


@when("service start fails during installation")
def install_start_fails(context):
    run_install(context, "ready", start_fails=True)


@when("I configure through the installation editor")
def install_editor(context):
    run_install(context, "missing", editor_status=0)


@when("the installation editor fails")
def install_editor_fails(context):
    run_install(context, "missing", editor_status=1)


@then("the edited configuration is saved")
def edited_config(context):
    assert 'voice = "af_heart"' in context.edited_config


@then("no service commands have run")
def no_service_commands(context):
    assert not context.service_commands, context.service_commands
    assert not context.service_exists


@then("the service is installed and started by sync")
def service_started(context):
    assert context.service_exists
    changes = [c for c in context.service_commands if not c.startswith(("--user is-active", "--user is-enabled"))]
    assert changes[-3:] == [
        "--user daemon-reload", "--user enable --now agavai-config.path", "--user enable --now agavai-llm.service"
    ], context.service_commands
