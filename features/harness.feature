Feature: Agavai owns voice tasks, context and execution
  Models propose; the in-process harness owns sources, task state and execution.

  Background:
    Given a chat UI in a temp runtime dir
    And an isolated harness with a local scripted language service

  Scenario: Recording summaries read corrected sources
    Given a saved harness recording with "We use cube flow for training."
    And line 1 is corrected to "We use Kubeflow for training."
    When the harness receives "summarize the last recording"
    Then the language service received "Kubeflow"
    And no harness desktop action was dispatched
    And the harness answer has a current recording revision

  Scenario: Word edits preserve heard words and invalidate derived output
    Given a saved harness recording with "We use cube flow for training."
    When the harness receives "summarize the last recording"
    And the harness receives "replace cube flow with Kubeflow"
    Then saved heard words contain "cube flow"
    And effective saved words contain "Kubeflow"
    And the harness answer is marked stale

  Scenario: Ambiguous edits require a line
    Given a saved harness recording with repeated "cube flow"
    When the harness receives "replace cube flow with Kubeflow in the transcript"
    Then the harness response contains "not unique"
    And effective saved words contain "cube flow"
    And no harness desktop action was dispatched

  Scenario: Multiple recordings need an explicit choice
    Given two saved harness recordings
    When the harness receives "summarize the recording"
    Then the harness response contains "Which recording"
    And the harness language service received no request

  Scenario: Long recordings are read in bounded parts
    Given a saved harness recording spanning several source parts
    When the harness receives "summarize the last recording"
    Then every source part reached the language service
    And the harness answer has a current recording revision

  Scenario: Sources exceeding the round budget are not silently truncated
    Given a saved harness recording exceeding the source budget
    When the harness receives "summarize the last recording"
    Then the harness response contains "source budget"
    And the harness language service received no request

  Scenario: Error text is data rather than tool failure
    Given the action service proposes reading the screen
    And the harness screen data contains an error message
    When the harness receives "read the screen"
    Then one screen read was recorded as successful
    And the language service received "error"
    And the harness response excludes "See the details on screen"

  Scenario: Self-correction precedes one side effect
    Given the language service resolves a ten minute reminder
    When the harness receives "remind me in five no ten minutes to call the bank"
    Then only a ten minute reminder was dispatched
    And the raw committed request contains "five no ten"

  Scenario: Ambiguous self-correction takes no action
    Given the language service cannot resolve the correction
    When the harness receives "Yes actually no"
    Then the harness response contains "complete corrected request"
    And no harness desktop action was dispatched

  Scenario: Input hold preserves the draft
    When the harness receives "wait"
    And the harness receives "open the browser"
    Then the harness language service received no request
    And no harness desktop action was dispatched
    And the harness holds "open the browser"
    When the harness receives "resume"
    Then the resumed harness retains "open the browser"

  Scenario: Compaction keeps original outcomes and complete exchanges
    Given a long harness conversation with completed screen reads
    When the harness receives "continue"
    Then the model received complete exchanges within its byte budget
    And original harness exchanges and outcomes are retained

  Scenario: Task classification also applies to Needle
    Given a completed harness screen task and an unrelated request
    When the harness receives "open the browser"
    Then the new action prompt excludes the screen task
    And the previous task is archived

  Scenario: Late inference cannot act after cancellation
    Given a language request waiting to propose a browser launch
    When the harness request is cancelled during inference
    Then no harness desktop action was dispatched
    And late inference cannot change the native snapshot
    And another request cannot queue behind the abandoned inference

  Scenario: Recording controls work during model inference
    Given a language request waiting to propose a browser launch
    When a recording shortcut arrives during model inference
    Then recording starts before that language request finishes
    And no harness desktop action was dispatched
    And the saved recording is bound to the harness

  Scenario: Unknown side effects are retained and never automatically repeated
    Given the action service proposes the same browser launch twice
    And the harness desktop command times out
    When the harness receives "open the browser"
    Then exactly one unknown launch outcome is retained
    And the native task status is "unknown"

  Scenario: Reasoning output cannot widen its route into desktop actions
    Given the language service proposes a screen read for a reasoning request
    When the harness receives "explain gravity"
    Then no harness desktop action was dispatched
    And the harness response contains "unavailable in this turn"

  Scenario: A concurrent transcript edit rejects a stale derived answer
    Given a saved harness recording with "We use cube flow for training."
    When the recording changes while the language model reads it
    Then the harness response contains "transcript changed"
    And the native task status is "needs_input"

  Scenario: A newer recording cannot replace an in-flight source
    Given a saved harness recording with "We use Kubeflow for training."
    When a newer recording arrives while the language model reads the last one
    Then the answer still identifies the original recording

  Scenario: A concurrent correction cannot overwrite newer words
    Given a saved harness recording with "We use cube flow for training."
    When another editor changes the line before the voice correction is saved
    Then the harness response contains "transcript changed"
    And effective saved words contain "We now use PyTorch."
    And saved heard words contain "cube flow"
    And the native task status is "needs_input"
