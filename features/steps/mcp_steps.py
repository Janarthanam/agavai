from __future__ import annotations

from unittest.mock import MagicMock, patch

from behave import then, when

from agavai.mcp_server import handle


@when("I send MCP initialize")
def step_init(context):
    context.mcp_init = handle(
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
    )


@then('the MCP server name should be "{name}"')
def step_name(context, name):
    assert context.mcp_init["result"]["serverInfo"]["name"] == name


@when("I send MCP tools/list")
def step_list(context):
    listed = handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    context.mcp_tools = {t["name"] for t in listed["result"]["tools"]}


@then('MCP should list the tool "{name}"')
def step_has(context, name):
    assert name in context.mcp_tools, context.mcp_tools


@then('MCP should not list the tool "{name}"')
def step_has_not(context, name):
    assert name not in context.mcp_tools, context.mcp_tools


@when('I call MCP tool "{name}"')
def step_call(context, name):
    context.mcp_call = handle(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": name, "arguments": {}},
        }
    )


@when("an MCP client asks to start a recording")
def step_mcp_record(context):
    # A regression must fail here, not start a real recording on this machine.
    fake = MagicMock(return_value="started")
    with patch.dict("agavai.tools.DISPATCH", {"start_recording": fake}):
        context.mcp_call = handle({"jsonrpc": "2.0", "id": 4, "method": "tools/call",
                                   "params": {"name": "start_recording", "arguments": {}}})
    context.mcp_recording = fake


@then("no recording was started over MCP")
def step_mcp_not_recording(context):
    assert not context.mcp_recording.called


@then('the MCP text result should contain "{text}"')
def step_text(context, text):
    body = context.mcp_call["result"]["content"][0]["text"]
    assert text in body, body
