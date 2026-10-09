"""Exercise the prototype's actual JavaScript reducer through Behave."""
import json
import subprocess
from pathlib import Path

from behave import given, when, then


@given("the voice design interaction model")
def design_model(context):
    context.design_model = Path(__file__).resolve().parents[2] / "docs/ui-prototype/model.js"


@when("the design receives these events")
def design_events(context):
    script = """
const model = require(process.argv[1]);
let input = '';
process.stdin.on('data', chunk => input += chunk);
process.stdin.on('end', () => {
  const state = JSON.parse(input).reduce(model.update, model.initial());
  process.stdout.write(JSON.stringify(state));
});
"""
    result = subprocess.run(
        ["node", "-e", script, str(context.design_model)],
        input=context.text, text=True, capture_output=True, check=True,
    )
    context.design = json.loads(result.stdout)


@then('the design phase is "{phase}"')
def design_phase(context, phase):
    assert context.design["phase"] == phase, context.design


@then('the design transcript is "{text}"')
def design_transcript(context, text):
    assert context.design["transcript"] == text, context.design


@then('the design transcript is ""')
def design_empty_transcript(context):
    assert context.design["transcript"] == "", context.design


@then("the design surface is {visibility}")
def design_visible(context, visibility):
    assert context.design["open"] is (visibility == "open"), context.design


@then("the design microphone level is {level:g}")
def design_level(context, level):
    assert context.design["level"] == level, context.design


@then("the design selected item is {index:d}")
def design_selection(context, index):
    assert context.design["selected"] == index, context.design


@then("the design has {count:d} results")
def design_result_count(context, count):
    assert len(context.design["items"]) == count, context.design
