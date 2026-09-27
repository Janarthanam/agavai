Feature: Top chat overlay snapshot
  The HUD must show the user line and each tool call so we can see what oma-voice is doing.

  Scenario: A turn records the user, two tool calls, and the reply
    Given a chat UI in a temp runtime dir
    When the UI starts listening
    And the user says "what is the current theme?"
    And the UI starts tool "list_themes" with "{}"
    And the UI finishes tool "list_themes" with "{\"current\":\"Matte Black\"}"
    And the UI starts tool "list_windows" with "{}"
    And the UI finishes tool "list_windows" with "[]"
    And the assistant says "Matte Black, and no extra windows."
    And the UI goes idle
    Then the snapshot phase should be "idle"
    And the last user line should be "what is the current theme?"
    And the last turn should have 2 tools
    And tool 1 should be "list_themes" with status "ok"
    And tool 2 should be "list_windows" with status "ok"
    And the last assistant line should contain "Matte Black"

  Scenario: A new process reloads prior turns from ui.json
    Given a chat UI in a temp runtime dir
    When the user says "hello"
    And I open a second chat UI on the same runtime dir
    Then the last user line should be "hello"
