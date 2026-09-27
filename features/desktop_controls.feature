Feature: Extra desktop controls
  Agavai can change volume, brightness, lock, and similar Omarchy actions
  without a generic shell.

  Scenario: Volume rejects unknown actions
    When I set volume action "explode"
    Then the tool result should contain "raise, lower, or mute"

  Scenario: Volume mute maps to mute-toggle
    Given omarchy commands succeed
    When I set volume action "mute"
    Then the last omarchy argv should include "mute-toggle"

  Scenario: Brightness set requires a percent
    When I set brightness action "set"
    Then the tool result should contain "percent must be 1-100"

  Scenario: Bluetooth rejects unknown actions
    When I set bluetooth action "pair"
    Then the tool result should contain "on, off, toggle, or status"

  Scenario: Screenshot rejects pointer-driven region mode
    When I take a screenshot with mode "region"
    Then the tool result should contain "fullscreen or windows"

  Scenario: Notification needs a headline
    When I send a notification with no headline
    Then the tool result should contain "need a headline"

  Scenario: open_app rejects paths
    When I open app "../bin/bash"
    Then the tool result should contain "simple app name"

  Scenario: workspace_step rejects nonsense
    When I step workspace "up"
    Then the tool result should contain "next or prev"

  Scenario: clock_now returns a timestamp
    When I call the tool "clock_now" with empty arguments
    Then the tool result should contain "-"

  Scenario: MCP lists the new controls
    When I send MCP tools/list
    Then MCP should list the tool "set_volume"
    And MCP should list the tool "lock_screen"
    And MCP should list the tool "open_app"
    And MCP should list the tool "screenshot"
