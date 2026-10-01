Feature: Streaming recognition commits on end of utterance
  Interim text is shown and is not a turn. End of utterance or Enter runs the
  request. End of boundary and Escape do not.

  Scenario: An interim hypothesis is shown and is not sent
    Given a chat UI in a temp runtime dir
    When an automatic session hears only an interim hypothesis
    Then the voice request is not submitted
    And the native transcript is "find the notes" and is partial
    And the snapshot phase should be "listening"

  Scenario: End of boundary updates the line and does not send
    Given a chat UI in a temp runtime dir
    When an automatic session hears an end of boundary
    Then the voice request is not submitted
    And the native transcript is "find the notes" and is partial
    And the snapshot phase should be "listening"

  Scenario: An empty end of utterance stays listening
    Given a chat UI in a temp runtime dir
    When an automatic session hears an empty end of utterance
    Then the voice request is not submitted
    And the snapshot phase should be "listening"

  Scenario: Enter commits the current hypothesis
    Given a chat UI in a temp runtime dir
    When an automatic session hears an interim and Enter
    Then the voice request is submitted once
    And the submitted line is "find the notes"

  Scenario: Escape drops the hypothesis and does not send
    Given a chat UI in a temp runtime dir
    When an automatic session hears an interim and Escape
    Then the voice request is not submitted
    And the snapshot phase should be "idle"
