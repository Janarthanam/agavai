Feature: Clients consume explicit harness turn outcomes
  Background:
    Given a headless harness with a local scripted language service

  Scenario: A headless answer has one finalized result and trace
    When the harness receives "explain gravity"
    Then the turn result status is "answered"
    And the returned result agrees with its final event and durable trace
    And the turn result contains 0 executions
    And no headless UI snapshot was created

  Scenario: A caller without an event sink still receives a typed answer
    Given the result client has no event sink
    When the harness receives "explain gravity"
    Then the turn result status is "answered"
    And the returned result agrees with its durable trace

  Scenario: Structured content is returned separately from speech
    Given the language service returns a structured planets answer
    When the harness receives "list the planets"
    Then the turn result contains the raw planets answer and its spoken summary
    And the returned result agrees with its final event and durable trace

  Scenario: Recording answers use the same result contract
    Given a saved harness recording with "We use Kubeflow for training."
    When the harness receives "summarize the last recording"
    Then the turn result contains a recording answer
    And the returned result agrees with its final event and durable trace

  Scenario: A source requiring clarification returns needs_input
    Given two saved harness recordings
    When the harness receives "summarize the recording"
    Then the turn result status is "needs_input"
    And the turn result contains 0 executions
    And the returned result agrees with its final event and durable trace

  Scenario: Confirmation and execution are distinct returned outcomes
    Given the action service prepares a browser confirmation
    When the harness receives "open the browser but confirm first"
    Then the turn result status is "awaiting_confirmation"
    And the turn result contains 0 executions
    And the returned result agrees with its final event and durable trace
    When the result client remembers this outcome
    And the harness receives "yes"
    Then the turn result status is "answered"
    And the turn result contains 1 executions
    And the returned result agrees with its final event and durable trace
    And the previous result remains unchanged

  Scenario: Blank input preserves confirmation without inventing a request
    Given the action service prepares a browser confirmation
    When the harness receives "open the browser but confirm first"
    And the result client remembers this outcome
    And the result client submits blank input
    Then the blank result requests input without committing a turn
    When the harness receives "yes"
    Then the turn result contains 1 executions

  Scenario: A held draft is explicitly silent and contains no old answer
    Given the language service returns a structured planets answer
    When the harness receives "list the planets"
    And the result client remembers this outcome
    And the harness receives "wait"
    And the harness receives "open the browser"
    Then the turn result status is "held"
    And the turn result has no speech or content
    And the turn result contains 0 executions
    And the previous result remains unchanged
    And the returned result agrees with its final event and durable trace

  Scenario: Task reset is a silent listening result
    When the harness receives "agavai"
    Then the turn result status is "listening"
    And the turn result has no speech or content
    And the returned result agrees with its final event and durable trace

  Scenario: Resume releases the hold with a listening result
    When the harness receives "wait"
    And the harness receives "resume"
    Then the turn result status is "listening"
    And the harness response contains "Ready"
    And the returned result agrees with its final event and durable trace

  Scenario: Cancellation during inference returns no action or speech
    Given a language request waiting to propose a browser launch
    When the harness request is cancelled during inference
    Then the turn result status is "cancelled"
    And the turn result has no speech or content
    And the turn result contains 0 executions
    And the returned result agrees with its final event and durable trace
    And late inference cannot publish another harness event

  Scenario: Cancellation retains an action that actually completed
    Given the action service proposes a browser launch
    When the request is cancelled while that desktop action runs
    Then the turn result status is "cancelled"
    And the turn result has no speech or content
    And the turn result contains 1 executions
    And the returned execution status is "ok"
    And the returned result agrees with its final event and durable trace

  Scenario Outline: Action failures retain their actual outcomes
    Given the action service proposes a browser launch
    And the desktop launch ends with "<outcome>"
    When the harness receives "open the browser"
    Then the turn result status is "<status>"
    And the returned execution status is "<outcome>"
    And the returned result agrees with its final event and durable trace

    Examples:
      | outcome | status  |
      | error   | failed  |
      | unknown | unknown |

  Scenario: Model failure returns failed without inventing executions
    Given the language service proposes a screen read for a reasoning request
    When the harness receives "explain gravity"
    Then the turn result status is "failed"
    And the turn result contains 0 executions
    And the returned result agrees with its final event and durable trace

  Scenario: Exhausted model steps return incomplete
    Given the action model exhausts its tool rounds
    When the harness receives "open the browser"
    Then the turn result status is "incomplete"
    And the turn result contains 1 executions
    And the returned result agrees with its final event and durable trace

  Scenario: Results never include executions from a prior request
    Given the action service proposes a browser launch
    When the harness receives "open the browser"
    And the result client remembers this outcome
    And the harness receives "agavai"
    Then the turn result contains 0 executions
    And the previous result remains unchanged
    And the returned result agrees with its final event and durable trace

  Scenario: Consumer mutations cannot rewrite the returned result
    Given the language service returns a structured planets answer
    And the collector changes finalized result payloads
    When the harness receives "list the planets"
    Then the turn result contains the raw planets answer and its spoken summary
    And the returned result agrees with its durable trace
    When the result client modifies returned content
    Then the harness output and durable answer remain unchanged

  Scenario: Terminal event delivery failure reaches the caller
    Given the collector rejects "task_status" events
    When the headless harness attempts "explain gravity"
    Then the consumer failure reaches its caller

  Scenario: A resumed result identifies only the new request
    Given the action service proposes a browser launch
    When the harness receives "open the browser"
    And the result client remembers this outcome
    And the harness closes and resumes its session
    And the harness receives "agavai"
    Then the turn result status is "listening"
    And the turn result contains 0 executions
    And the resumed result advances the trace without changing the previous result
    And the returned result agrees with its final event and durable trace

  Scenario Outline: Voice clients speak only the returned speech
    Given the language service returns a structured planets answer
    When the voice result client receives "<text>"
    Then the result client speaks "<speech>"

    Examples:
      | text             | speech                |
      | list the planets | Here are the planets. |
      | agavai           |                       |

  Scenario: A cancelled voice turn keeps completed effects without speaking
    Given the action service proposes a browser launch
    And the result client cancels as the desktop launch completes
    When the voice result client receives "open the browser"
    Then the result client speaks ""
    And the result client retains a cancelled turn with a successful execution

  Scenario Outline: The typed CLI preserves speech output and silence
    Given the language service returns a structured planets answer
    When the typed result client asks "<text>"
    Then the result client speaks "<speech>"
    And the typed result client prints "<speech>"

    Examples:
      | text             | speech                |
      | list the planets | Here are the planets. |
      | agavai           |                       |

  Scenario: A cancelled typed turn prints and speaks nothing
    Given the action service proposes a browser launch
    And the result client cancels as the desktop launch completes
    When the typed result client asks "open the browser"
    Then the result client speaks ""
    And the typed result client prints ""
    And the result client retains a cancelled turn with a successful execution
