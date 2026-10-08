Feature: Conversation context controls the canvas
  A context response distinguishes a follow-up from a new conversation before
  old results or tool heads can affect the new answer.

  Background:
    Given a chat UI in a temp runtime dir
    And the chat UI uses the keyword router
    And llama-server replies "Which image do you want?"
    And wallpaper listing returns a ship image
    When I run a turn with text "show me the screensaver images" on the chat UI
    And the UI finishes tool "wallpaper_set" with "wallpaper set to ship at sea"

  Scenario Outline: A new conversation clears old output even without replacement results
    Given the context response is "new_conversation"
    And llama-server replies "Answered the new request."
    When I continue the turn with text "<request>"
    Then the spoken reply should be "Answered the new request."
    And the context decision used the earlier results and "<request>"
    And the new answer started with a blank conversation canvas
    And the model messages excluded "show me the screensaver images"
    And the model messages excluded "Ship At Sea"
    And the new answer uses head "<head>"
    And the listening session identity was retained

    Examples:
      | request                                     | head      |
      | what time is it?                            | reminders |
      | hello there                                 | none      |
      | start over: what makes a good wallpaper?     | wallpaper |

  Scenario: A short follow-up keeps results even when its words name no tool head
    Given the context response is "follow_up"
    And llama-server replies "Setting ship at sea."
    When I continue the turn with text "ship at sea"
    Then the spoken reply should be "Setting ship at sea."
    And the context decision used the earlier results and "ship at sea"
    And the earlier canvas and conversation were retained
    And the follow-up model was offered "wallpaper_set"
    And the listening session identity was retained

  Scenario Outline: An invalid context response reports an error and retains prior results
    Given the context response is "<response>"
    And llama-server replies "This answer must not run."
    When I continue the turn with text "what time is it?"
    Then the spoken reply should contain "could not determine"
    And no action answer was requested
    And the earlier canvas and model history were retained
    And the snapshot phase should be "error"

    Examples:
      | response                      |
      | maybe                         |
      | follow_up or new_conversation |

  Scenario: An empty context response reports an error and retains prior results
    Given the context response is empty
    And llama-server replies "This answer must not run."
    When I continue the turn with text "what time is it?"
    Then the spoken reply should contain "could not determine"
    And no action answer was requested
    And the earlier canvas and model history were retained

  Scenario: A context response cannot execute a tool call
    Given the context response contains a tool call
    And llama-server replies "This answer must not run."
    When I continue the turn with text "ship at sea"
    Then the spoken reply should contain "could not determine"
    And no action answer was requested
    And the tool "wallpaper_list" should have been called once
    And the earlier canvas and model history were retained

  Scenario: A failed context call retains prior results and reports the failure
    Given the context model fails with "llama-server unreachable"
    And llama-server replies "This answer must not run."
    When I continue the turn with text "what time is it?"
    Then the spoken reply should contain "llama-server unreachable"
    And no action answer was requested
    And the earlier canvas and model history were retained

  Scenario: Dismissal during the context decision prevents a late reset or answer
    Given the context response is "new_conversation"
    And the session is dismissed during the context decision
    And llama-server replies "This answer must not run."
    When I continue the turn with text "what time is it?"
    Then no spoken reply is produced
    And no action answer was requested
    And the earlier canvas and model history were retained
    And the snapshot phase should be "idle"
    And the listening session identity was retained

  Scenario: Empty speech does not classify or clear the conversation
    When I continue the turn with text "   "
    Then the spoken reply should be "I did not hear anything."
    And no context decision was requested
    And no action answer was requested
    And the conversation snapshot was unchanged

  Scenario: An explicitly fresh turn bypasses classification and clears old output
    Given llama-server replies "Hello."
    When I run a turn with text "hello there" on the chat UI
    Then the spoken reply should be "Hello."
    And no context decision was requested
    And the new answer started with a blank conversation canvas
    And the model messages excluded "show me the screensaver images"

  Scenario: Partial speech retains the results without a context decision
    When the UI listens for a follow-up
    And recognition updates the words to "what time"
    Then no context decision was requested
    And the native result title is "Images"
