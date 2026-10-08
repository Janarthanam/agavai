Feature: The orb reveals microphone listening
  Microphone levels come from the same capture as recognition, even before
  words arrive. They never submit a turn or restore the old silence gate.

  Scenario: Input moves the orb before the recognizer returns words
    Given a chat UI in a temp runtime dir
    When streaming capture receives silence and speech without recognition output
    Then the orb receives silent and audible microphone levels at most 10 times per second
    And recognition and metering use one unchanged audio stream
    And the voice request is not submitted

  Scenario: Cancellation stops microphone feedback
    Given a chat UI in a temp runtime dir
    When I cancel streaming capture after microphone levels arrive
    Then the native microphone level is absent
    And the snapshot phase should be "idle"
    And the voice request is not submitted

  Scenario: An unavailable capture does not animate microphone input
    Given a chat UI in a temp runtime dir
    When streaming capture ends before any microphone audio arrives
    Then no microphone levels are published
    And the native microphone level is absent
    And the snapshot phase should be "error"
    And the voice request is not submitted

  Scenario: The listening ring moves during silence and settles after listening
    When I check the native orb animation without desktop capture
    Then the native orb animation check passes
