import json

from behave import when, then

from agavai.canvas import model_view, read_aloud, spoken_name


@when('I prepare a spoken label for a "{kind}" titled "{title}" at "{path}"')
def label(context, kind, title, path):
    context.result_label = spoken_name({"kind": kind, "title": title, "path": path})


@then('the result label is "{label}"')
def spoken_label(context, label):
    assert context.result_label == label, context.result_label


@when("file results contain technical names and the reply echoes filenames and paths")
def filenames(context):
    paths = [context.runtime_dir / name for name in ("Meeting_Notes-2026.md", "notes.md", "Budget Notes.pdf")]
    payload = json.dumps([str(path) for path in paths])
    context.ui.tool_done("search_files", payload)
    context.canvas = context.ui.data["display"]
    context.model_items = json.loads(model_view("search_files", payload))["items"]
    context.result_speech = read_aloud(
        f'Here are Meeting_Notes-2026.md, {paths[1]}, and "{paths[2]}". Keep notes.md.bak and anotes.md unchanged.',
        context.canvas,
    )


@then("speech uses readable labels while the canvas keeps exact names")
def readable(context):
    assert context.result_speech == 'Here are Meeting Notes 2026, notes, and "Budget Notes". Keep notes.md.bak and anotes.md unchanged.', context.result_speech
    assert [item["name"] for item in context.model_items] == ["Meeting Notes 2026", "notes", "Budget Notes"]
    assert [item["title"] for item in context.canvas["items"]] == ["Meeting_Notes-2026.md", "notes.md", "Budget Notes.pdf"]
    assert all(item["path"].startswith(str(context.runtime_dir)) for item in context.canvas["items"])


@when('I prepare speech for "{reply}" without a canvas')
def no_canvas(context, reply):
    context.result_speech = read_aloud(reply, None)


@when('I prepare speech for "{reply}" from these results')
def from_results(context, reply):
    context.result_speech = read_aloud(reply, {"items": [dict(row.items()) for row in context.table]})


@then('the result speech is "{speech}"')
def speech(context, speech):
    assert context.result_speech == speech, context.result_speech


@when("a file listing is published, retained during listening, and published again")
def repeated_tool(context):
    payload = '["/tmp/Meeting_Notes-2026.md"]'
    context.ui.listening()
    context.ui.tool_done("search_files", payload)
    context.first_canvas = context.ui.data["display"]
    context.ui.continue_listening()
    context.ui.partial("show those again")
    context.ui.level(-20, "off", "off")
    context.retained_id = context.ui.data["display"]["id"]
    context.ui.tool_done("search_files", payload)
    context.second_canvas = context.ui.data["display"]


@then("listening updates keep the canvas identity")
def retained(context):
    assert context.retained_id == context.first_canvas["id"]


@then("repeated results get a new canvas identity with the same content")
def distinct(context):
    first = dict(context.first_canvas)
    second = dict(context.second_canvas)
    assert first.pop("id") != second.pop("id")
    assert first == second


@when("the same explicit canvas is published twice and then cleared")
def explicit(context):
    block = {"kind": "answer", "title": "Example", "html": "<p>Hello</p>"}
    context.ui.display(block)
    context.first_canvas = context.ui.data["display"]
    context.ui.display(block)
    context.second_canvas = context.ui.data["display"]
    assert "id" not in block
    context.ui.display(None)


@then("the cleared canvas is absent")
def cleared(context):
    assert "display" not in context.ui.data
