from __future__ import annotations

import os
import subprocess
from pathlib import Path

from behave import then, when

ROOT = Path(__file__).resolve().parents[2]
DESKTOP = ROOT / "share" / "agavai.desktop"


@then("the desktop file should exist")
def step_exists(context):
    assert DESKTOP.is_file(), DESKTOP


@then('the desktop file should contain "{text}"')
def step_contains(context, text):
    body = DESKTOP.read_text()
    assert text in body, body


@when('I run "{command}"')
def step_run(context, command):
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "src") + ((":" + env["PYTHONPATH"]) if env.get("PYTHONPATH") else "")
    proc = subprocess.run(
        command.split(),
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        env=env,
    )
    context.cmd_out = (proc.stdout or "") + (proc.stderr or "")
    context.cmd_code = proc.returncode


@then('the command output should contain "{text}"')
def step_out(context, text):
    assert text in context.cmd_out, context.cmd_out
