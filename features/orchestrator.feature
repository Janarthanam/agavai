Feature: Local tool loop
  The on-device model may call tools, then speak a short reply.

  Scenario: Empty speech is ignored
    When I run a turn with text "   "
    Then the spoken reply should be "I did not hear anything."

  Scenario: Down llama-server is reported instead of inventing actions
    Given llama-server is down
    When I run a turn with text "open the browser"
    Then the spoken reply should contain "not running"

  Scenario: A tool call is executed then the model speaks
    Given llama-server will call "launch" then reply "Opened the browser."
    When I run a turn with text "open the browser"
    Then the spoken reply should be "Opened the browser."
    And the tool "launch" should have been called once

  Scenario: Think tags are stripped from model text
    Then stripping think tags from "hello" yields "hello"
    And stripping think tags from "pre<think>secret</think>post" yields "prepost"
