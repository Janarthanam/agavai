Feature: Invoke one voice widget and speak without a second shortcut
  The app launcher, bar and Super+M invoke automatic listening in one surface.

  Scenario: Invocation opens the shared widget and starts automatic listening
    Given a chat UI in a temp runtime dir
    When I invoke Agavai while it is "idle"
    Then the shared overlay is summoned once
    And one automatic listening session is requested

  Scenario Outline: Reinvocation raises the same widget without interrupting work
    Given a chat UI in a temp runtime dir
    When I invoke Agavai while it is "<phase>"
    Then the shared overlay is summoned once
    And no new listening session is requested

    Examples:
      | phase        |
      | listening    |
      | transcribing |
      | thinking     |
      | speaking     |

  Scenario: An unavailable widget does not start invisible microphone capture
    Given a chat UI in a temp runtime dir
    When I invoke Agavai without an available shell
    Then no new listening session is requested
    And invocation reports failure

  Scenario: One successful shell invocation is sufficient
    When the Omarchy shell accepts the overlay invocation
    Then the shell invocation launches exactly once

  Scenario: Automatic invocation chooses a pause-detecting listener even in manual config
    Given a chat UI in a temp runtime dir
    When I launch an automatic session with manual capture configured
    Then the detached command uses automatic listening

  Scenario: End of utterance completes the command without another key press
    Given a chat UI in a temp runtime dir
    When an automatic session hears speech and an end of utterance
    Then the voice request is submitted once

  Scenario: Missing microphone input ends with a visible error
    Given a chat UI in a temp runtime dir
    When an automatic session has no microphone
    Then the voice request is not submitted
    And the snapshot phase should be "error"

  Scenario: Silence keeps the session listening and does not send noise to the model
    Given a chat UI in a temp runtime dir
    When an automatic session hears only silence
    Then the voice request is not submitted
    And the snapshot phase should be "listening"

  Scenario: A choice prompt returns to listening and keeps the images
    Given a chat UI in a temp runtime dir
    When an automatic session is asked to choose a screensaver image and then hears silence
    Then the voice request is submitted once
    And the follow-up listen started
    And the follow-up kept the shown images

  Scenario: The next utterance is marked as a continuation of the conversation
    Given a chat UI in a temp runtime dir
    When an automatic session hears a screensaver choice and then an answer
    Then the voice turns continued as
      | continued |
      | false     |
      | true      |

  Scenario: A stalled source ends automatically
    When the microphone stream stalls
    Then the source ends rather than waiting for another shortcut
