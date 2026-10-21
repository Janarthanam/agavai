import json
from unittest.mock import patch

from behave import given, when, then
from agavai.ui import cancel_ui, open_result
from agavai.orchestrator import run_turn


def snapshot(context):
    return json.loads((context.runtime_dir / "ui.json").read_text())


@when('tool "{tool}" returns this full result')
def full_tool(context, tool):
    context.ui.tool_done(tool, context.text)


@when('recognition updates the words to "{text}"')
def partial(context, text):
    context.ui.partial(text)


@then("the native snapshot has no results or prior turns")
def fresh(context):
    data = snapshot(context)
    assert not data["turns"] and "display" not in data, data


@then('the native transcript is "{text}" and is {status}')
def transcript(context, text, status):
    assert snapshot(context)["transcript"] == {"text": text, "final": status == "final"}


@then('the native result kinds are "{kinds}"')
def kinds(context, kinds):
    assert ",".join(item["kind"] for item in snapshot(context)["display"]["items"]) == kinds


@then('the native result kinds are ""')
def no_kinds(context):
    assert snapshot(context)["display"]["items"] == []


@then('the native result title is "{title}"')
def title(context, title):
    assert snapshot(context)["display"]["title"] == title


@then('the native result {index:d} URI contains "{text}"')
def uri(context, index, text):
    assert text in snapshot(context)["display"]["items"][index]["uri"]


@then('the native result {index:d} subtitle is "{text}"')
def subtitle(context, index, text):
    assert snapshot(context)["display"]["items"][index]["subtitle"] == text


@then('the native answer contains "{text}"')
def answer(context, text):
    assert text in snapshot(context)["answer_html"]


@then('the native rich result {mode} "{text}"')
def rich(context, mode, text):
    assert (text in snapshot(context)["display"]["html"]) == (mode == "contains")


@when("a mocked model searches for 30 matching files")
def long_results(context):
    reply = [
        {"tool_calls": [{"id": "search", "function": {"name": "search_files", "arguments": '{"query":"notes"}'}}]},
        {"content": "Found your notes."},
    ]
    result = json.dumps([f"/tmp/notes-for-a-very-long-design-session-{i}.md" for i in range(30)])
    def chat(cfg, messages, tools=None):
        if len(reply) == 1:
            context.model_result = messages[-1]["content"]
        return reply.pop(0)
    with patch("agavai.orchestrator.health", return_value=True), patch("agavai.orchestrator.select_head_ids", return_value=["files"]), patch("agavai.orchestrator.chat", side_effect=chat), patch("agavai.orchestrator.call_tool", return_value=result):
        run_turn("find notes", context.cfg, context.ui)


@then("the native browser has {count:d} items")
def item_count(context, count):
    assert len(snapshot(context)["display"]["items"]) == count


@then("the model received a bounded tool result")
def bounded(context):
    assert len(context.model_result) <= 500 and context.model_result.endswith("…")


@given("a native document result exists")
def document(context):
    context.document = context.runtime_dir / "selected note.md"
    context.document.write_text("# Notes\n\n**Important**", encoding="utf-8")
    context.ui.user("find notes")
    context.ui.tool_done("search_files", json.dumps([str(context.document)]))


@when("I open native result {index:d} in the {session} session")
def open_item(context, index, session):
    token = str(snapshot(context).get("session_id", "")) if session == "current" else "old-session"
    with patch("agavai.ui.subprocess.Popen") as opener:
        context.opened = open_result(context.cfg, index, token)
        context.open_calls = opener.call_args_list


@given("a native folder result exists")
def folder(context):
    context.document = context.runtime_dir / "Notes"
    context.document.mkdir()
    context.ui.user("find notes")
    context.ui.tool_done("search_files", json.dumps([str(context.document)]))


@then("the native opener launches the selected document")
def opened(context):
    assert context.opened and len(context.open_calls) == 1
    assert context.open_calls[0].args[0] == ["xdg-open", str(context.document)]


@then("the native opener launches nothing")
def unopened(context):
    assert not context.opened and not context.open_calls


@when("the native session is cancelled")
def cancelled(context):
    cancel_ui(context.cfg)


@then('the native snapshot label is "{label}"')
def snapshot_label(context, label):
    assert snapshot(context)["phase_label"] == label


@then("the native session is marked cancelled")
def is_cancelled(context):
    assert context.ui.cancelled()


@then("the native session is not marked cancelled")
def not_cancelled(context):
    assert not context.ui.cancelled()


@when("the mic input level is {db:g} dB")
def mic_level(context, db):
    context.ui.level(db)


@then("the native microphone level is absent")
def quiet(context):
    assert snapshot(context)["level_db"] is None


@given('a chat UI in a temp runtime dir with overlay placement "{placement}"')
def placed_ui(context, placement):
    context.execute_steps("Given a chat UI in a temp runtime dir")
    context.cfg.overlay.placement = placement


@then('the native snapshot places the overlay at "{placement}"')
def placed(context, placement):
    assert snapshot(context).get("placement") == placement, snapshot(context)
