Feature: Isolated finalized controls bypass the model
  A control is the whole committed utterance, never a word in partial or longer
  speech. Confirmation stores one session-bound action with resolved arguments.

  Background:
    Given a chat UI in a temp runtime dir
    And the chat UI uses the keyword router
    And control turn dependencies are recorded
    When the UI starts listening

  Scenario Outline: Yes and Continue execute a prepared action without inference
    Given a browser launch is awaiting confirmation
    And the control model is unavailable
    When I continue the turn with text "<text>"
    Then the spoken reply should be "launched browser"
    And the prepared browser launch executed once
    And no control inference or routing happened
    And there is no pending control action
    And the control history contains the actual tool result
    And the listening session identity was retained
    And the completion is "Done" with "launched browser"

    Examples:
      | text         |
      | Yes!         |
      | YES          |
      | yes...       |
      |  yes         |
      | Continue!    |
      | continue…    |

  Scenario: A consumed confirmation cannot execute twice
    Given a browser launch is awaiting confirmation
    When I continue the turn with text "Yes"
    And I continue the turn with text "Yes"
    Then the spoken reply should be "What would you like me to confirm?"
    And the prepared browser launch executed once
    And no control inference or routing happened

  Scenario: No consumes the proposal without executing it
    Given a browser launch is awaiting confirmation
    When I continue the turn with text "No!"
    Then the spoken reply should be "Cancelled the pending action."
    And no control desktop action happened
    And no control inference or routing happened
    And there is no pending control action
    When I continue the turn with text "Yes"
    Then the spoken reply should be "What would you like me to confirm?"
    And no control desktop action happened

  Scenario Outline: Unbound Yes and No are handled locally
    Given the control model is unavailable
    When I continue the turn with text "<text>"
    Then the spoken reply should be "<reply>"
    And no control inference or routing happened
    And no control desktop action happened

    Examples:
      | text | reply                                    |
      | Yes  | What would you like me to confirm?        |
      | No   | There is no pending action to cancel.     |

  Scenario: Continue without a prepared action goes to Qwen
    When I continue the turn with text "Continue"
    Then the spoken reply should be "Normal answer."
    And the control action model received "Continue"

  Scenario Outline: Controls embedded in speech do not execute or reset
    Given a browser launch is awaiting confirmation
    And prior control results are on the canvas
    When I continue the turn with text "<text>"
    Then the spoken reply should be "Normal answer."
    And the control action model received "<text>"
    And the control context decision happened once
    And no control desktop action happened
    And there is no pending control action
    And the prior control conversation was retained

    Examples:
      | text                                                                   |
      | while you are doing this, yes you have to show me the wall paper         |
      | Yes, show me the wallpaper                                              |
      | Agavai show me the wallpaper                                            |
      | continue explaining                                                    |
      | yesterday                                                              |
      | nobody                                                                 |

  Scenario: Isolated Agavai silently clears conversation within the same session
    Given a browser launch is awaiting confirmation
    And prior control results are on the canvas
    And the control model is unavailable
    When I continue the turn with text "AGAVAI!"
    Then no spoken reply is produced
    And the control conversation is empty
    And there is no pending control action
    And no control inference or routing happened
    And no control desktop action happened
    And the snapshot phase should be "listening"
    And the listening session identity was retained

  Scenario: A fresh turn cannot consume an earlier proposal
    Given a browser launch is awaiting confirmation
    When I run a turn with text "Yes" on the chat UI
    Then the spoken reply should be "What would you like me to confirm?"
    And no control desktop action happened
    And there is no pending control action

  Scenario: Dismissal prevents a pending action from executing
    Given a browser launch is awaiting confirmation
    When the control session is dismissed
    And I continue the turn with text "Yes"
    Then no spoken reply is produced
    And no control desktop action happened
    And no control inference or routing happened
    And there is no pending control action

  Scenario: A new session has no pending action
    Given a browser launch is awaiting confirmation
    When the UI starts listening
    And I continue the turn with text "Yes"
    Then the spoken reply should be "What would you like me to confirm?"
    And no control desktop action happened

  Scenario: A stale session-bound proposal is rejected
    Given a browser launch is awaiting confirmation
    When the control proposal belongs to another session
    And I continue the turn with text "Yes"
    Then the spoken reply should be "What would you like me to confirm?"
    And no control desktop action happened
    And there is no pending control action

  Scenario: An unrelated request invalidates the proposal even if Qwen is down
    Given a browser launch is awaiting confirmation
    And the control model is unavailable
    When I continue the turn with text "what time is it"
    Then there is no pending control action
    When I continue the turn with text "Yes"
    Then the spoken reply should be "What would you like me to confirm?"
    And no control desktop action happened

  Scenario: Tool failure is reported without a success claim or inference
    Given a browser launch is awaiting confirmation
    And the control desktop command fails
    When I continue the turn with text "Yes"
    Then the spoken reply should be "launch failed"
    And the completion is "Not completed" with "launch failed"
    And there is no pending control action
    And no control inference or routing happened

  Scenario: Invalid arguments are rejected before a confirmation is prepared
    Given a control proposal for "launch" with arguments "{"target":"unknown"}"
    When I run a turn with text "open the browser but confirm first" on the chat UI
    Then the spoken reply should contain "Invalid launch argument choice"
    And no control desktop action happened
    And there is no pending control action

  Scenario Outline: Invalid proposals never become executable
    Given a malformed control proposal "<proposal>"
    When I run a turn with text "open the browser but confirm first" on the chat UI
    Then the snapshot phase should be "error"
    And there is no pending control action
    And no control desktop action happened

    Examples:
      | proposal                                                                                         |
      | broken JSON                                                                                      |
      | []                                                                                               |
      | {"name":"shell","arguments":{},"question":"Run it?"}                                          |
      | {"name":"wallpaper_set","arguments":{"name":"ship"},"question":"Apply it?"}                   |
      | {"name":"launch","arguments":[],"question":"Open browser?"}                                    |
      | {"name":"launch","arguments":{"target":"browser"},"question":""}                             |

  Scenario: Confirmation cannot be combined with action execution
    Given a control confirmation and launch are returned together
    When I run a turn with text "open the browser but confirm first" on the chat UI
    Then the snapshot phase should be "error"
    And there is no pending control action
    And no control desktop action happened

  Scenario: A prose question does not create an executable proposal
    Given the control model asks only in prose
    When I run a turn with text "open the browser but confirm first" on the chat UI
    And I continue the turn with text "Yes"
    Then the spoken reply should be "What would you like me to confirm?"
    And no control desktop action happened

  Scenario: Cancellation while preparing confirmation prevents late state
    Given a browser confirmation will be cancelled during inference
    When I run a turn with text "open the browser but confirm first" on the chat UI
    Then no spoken reply is produced
    And there is no pending control action
    And no control desktop action happened

  Scenario: Confirmation respects the schema budget
    When a control request combines two tool heads
    Then the control schemas stay within the configured budget

  Scenario: Empty input leaves the proposal intact
    Given a browser launch is awaiting confirmation
    When I continue the turn with text "   "
    Then a control action remains pending
    And no control inference or routing happened
    And no control desktop action happened

  Scenario: Loading a prior snapshot cannot restore a pending action
    Given a browser launch is awaiting confirmation
    When I open a second chat UI on the same runtime dir
    And I continue the turn with text "Yes"
    Then the spoken reply should be "What would you like me to confirm?"
    And no control desktop action happened

  Scenario: Cancellation immediately before dispatch prevents the action
    Given a browser launch is awaiting confirmation
    And the control session will be dismissed at action start
    When I continue the turn with text "Yes"
    Then no spoken reply is produced
    And no control desktop action happened
    And no control inference or routing happened
    And there is no pending control action

  Scenario: Dismissal during execution suppresses a late reply
    Given a browser launch is awaiting confirmation
    And the control session will be dismissed during execution
    When I continue the turn with text "Yes"
    Then no spoken reply is produced
    And the prepared browser launch executed once
    And no control inference or routing happened
    And there is no pending control action

  Scenario: Confirmation is unavailable when the schema budget has one slot
    Given the control schema budget is one
    And a control proposal for "launch" with arguments "{"target":"browser"}"
    When I run a turn with text "open the browser but confirm first" on the chat UI
    Then the snapshot phase should be "error"
    And there is no pending control action
    And no control desktop action happened

  Scenario: Noninteractive turns cannot prepare an executable confirmation
    Given a control proposal for "launch" with arguments "{"target":"browser"}"
    When a control request is made without a chat UI
    Then the spoken reply should contain "interactive turn"
    And no control desktop action happened

  Scenario Outline: Local results preserve errors and readable speech
    Given a browser launch is awaiting confirmation
    And the confirmed control tool returns "<result>"
    When I continue the turn with text "Yes"
    Then the spoken reply should be "<reply>"
    And no control inference or routing happened
    And there is no pending control action

    Examples:
      | result                                      | reply                                                    |
      | screenshot saved /tmp/ship-at-sea.png        | screenshot saved ship at sea                             |
      | {"error":"failed"}                        | The action returned more detail than I can read aloud. I have kept its result.    |
      | First sentence. Second sentence. Third one. | The action returned more detail than I can read aloud. I have kept its result.    |
      |                                             | The action returned no result.                           |

  Scenario: Partial Yes grows into a longer request without triggering confirmation
    When a real control listen loop receives
      | kind    | text                                                                   |
      | eou     | open the browser but confirm first                                      |
      | interim | yes                                                                    |
      | eob     | yes                                                                    |
      | interim | while you are doing this yes you have to show me the wall paper          |
      | eou     | while you are doing this yes you have to show me the wall paper          |
    Then no control desktop action happened
    And the control action model received "while you are doing this yes you have to show me the wall paper"
    And there is no pending control action

  Scenario: Enter commits the isolated control
    When a real control listen loop receives
      | kind    | text                              |
      | eou     | open the browser but confirm first |
      | interim | yes                               |
      | enter   |                                   |
    Then the prepared browser launch executed once
    And only the proposal needed control inference

  Scenario: EOU commits Yes and returns to listening
    When a real control listen loop receives
      | kind    | text                              |
      | eou     | open the browser but confirm first |
      | interim | yes                               |
      | eou     | yes                               |
    Then the prepared browser launch executed once
    And only the proposal needed control inference
    And the snapshot phase should be "listening"

  Scenario Outline: A partial or EOB control never acts
    When a real control listen loop receives
      | kind    | text                              |
      | eou     | open the browser but confirm first |
      | <kind>  | <text>                            |
    Then no control desktop action happened
    And a control action remains pending
    And only the proposal needed control inference

    Examples:
      | kind    | text   |
      | interim | yes    |
      | eob     | yes    |
      | interim | agavai |
      | eob     | agavai |

  Scenario: Reset immediately listens for the next request without speech or thinking cue
    When a real control listen loop receives
      | kind | text                              |
      | eou  | open the browser but confirm first |
      | eou  | Agavai                            |
      | eou  | what time is it                   |
    Then the control reset reopened a blank conversation
    And only the proposal and next request played replies
    And the control action model received "what time is it"
    And no control desktop action happened
