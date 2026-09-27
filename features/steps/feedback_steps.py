from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from behave import then, when

from oma_voice.feedback import osd_show


@when("I show the listening OSD")
def step_show(context):
    run = MagicMock()
    run.returncode = 0
    which = patch("oma_voice.feedback.shutil.which", return_value="/usr/bin/omarchy")
    run_p = patch("oma_voice.feedback.subprocess.run", return_value=run)
    context.run_mock = run_p.start()
    which.start()
    context.add_cleanup(which.stop)
    context.add_cleanup(run_p.stop)
    osd_show("Listening", duration=0)


@then("the OSD command should be omarchy shell osd show")
def step_cmd(context):
    argv = context.run_mock.call_args[0][0]
    assert argv[:5] == ["omarchy", "shell", "-q", "osd", "show"], argv
    context.osd_payload = json.loads(argv[5])


@then('the OSD message should be "{text}"')
def step_msg(context, text):
    assert context.osd_payload["message"] == text


@then('the OSD icon should be "{icon}"')
def step_icon(context, icon):
    assert context.osd_payload["icon"] == icon


@then("the OSD duration should be {n:d}")
def step_dur(context, n):
    assert context.osd_payload["duration"] == n
