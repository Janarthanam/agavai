Feature: Voice and result browsing interaction design
  The prototype defines the session behavior before native UI integration.

  Scenario: The shortcut starts a fresh listening surface
    Given the voice design interaction model
    When the design receives these events
      """
      [{"type":"start"}]
      """
    Then the design phase is "listening"
    And the design surface is open

  Scenario: Live transcription revises one utterance
    Given the voice design interaction model
    When the design receives these events
      """
      [{"type":"start"},{"type":"partial","text":"find my node"},{"type":"partial","text":"find my notes"}]
      """
    Then the design transcript is "find my notes"

  Scenario: Input strength drives the microphone without exceeding its range
    Given the voice design interaction model
    When the design receives these events
      """
      [{"type":"start"},{"type":"level","db":10}]
      """
    Then the design microphone level is 1

  Scenario: A quiet microphone has no artificial activity
    Given the voice design interaction model
    When the design receives these events
      """
      [{"type":"start"},{"type":"level","db":-100}]
      """
    Then the design microphone level is 0

  Scenario: Results expand the listening session into a browser
    Given the voice design interaction model
    When the design receives these events
      """
      [{"type":"start"},{"type":"partial","text":"find notes"},{"type":"submit"},{"type":"results","items":[{"kind":"file","title":"Notes.md"},{"kind":"image","title":"Mountain.png"}]},{"type":"select","index":1}]
      """
    Then the design phase is "results"
    And the design selected item is 1
    And the design transcript is "find notes"

  Scenario: Browsing stops at the final result
    Given the voice design interaction model
    When the design receives these events
      """
      [{"type":"start"},{"type":"submit"},{"type":"results","items":[{"kind":"file","title":"Notes.md"}]},{"type":"select","index":20}]
      """
    Then the design selected item is 0

  Scenario: Dismissal ignores pending tool results
    Given the voice design interaction model
    When the design receives these events
      """
      [{"type":"start"},{"type":"submit"},{"type":"dismiss"},{"type":"results","items":[{"kind":"file","title":"Late.md"}]}]
      """
    Then the design phase is "idle"
    And the design surface is closed

  Scenario: A new request clears the previous preview and words
    Given the voice design interaction model
    When the design receives these events
      """
      [{"type":"start"},{"type":"partial","text":"old request"},{"type":"submit"},{"type":"results","items":[{"kind":"file","title":"Old.md"}]},{"type":"start"}]
      """
    Then the design transcript is ""
    And the design has 0 results

  Scenario: A microphone error remains visible with no activity
    Given the voice design interaction model
    When the design receives these events
      """
      [{"type":"start"},{"type":"level","db":-15},{"type":"error","message":"Microphone unavailable"}]
      """
    Then the design phase is "error"
    And the design surface is open
    And the design microphone level is 0
