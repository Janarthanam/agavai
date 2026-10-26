Feature: The harness publishes events without a graphical UI
  A collector, native UI adapter or future persistence writer uses the same boundary.

  Background:
    Given a headless harness with a local scripted language service

  Scenario: A language request runs with graphical imports forbidden
    When a separate headless process asks the language service
    Then that process publishes serializable ordered events without importing the UI
    And no headless UI snapshot was created

  Scenario Outline: A caller can cancel capture without a graphical signal
    When the headless caller cancels during "<mode>" capture
    Then headless capture closes without committing a model request
    And no headless UI snapshot was created

    Examples:
      | mode      |
      | assistant |
      | recording |

  Scenario: A headless consumer can confirm an action
    Given the action service prepares a browser confirmation
    When the harness receives "open the browser but confirm first"
    Then the headless task status is "awaiting_confirmation"
    And no harness desktop action was dispatched
    When the harness receives "yes"
    Then the collector received one complete browser outcome
    And harness events have ordered session and request identity
    And no headless UI snapshot was created

  Scenario: A task change is explicit in the event stream
    Given a completed harness screen task and an unrelated request
    When the harness receives "open the browser"
    Then the new request moves to its own task in the event stream
    And no headless UI snapshot was created

  Scenario: Structured answers carry content rather than rendered HTML
    Given the language service returns a structured planets answer
    When the harness receives "list the planets"
    Then the collector received the complete planets answer
    And no headless UI snapshot was created

  Scenario: Corrected recording sources are observable without a canvas
    Given a saved harness recording with "We use cube flow for training."
    When the harness receives "summarize the last recording"
    And the harness receives "replace cube flow with Kubeflow"
    Then the collector observed a source revision change and stale derived output
    And effective saved words contain "Kubeflow"
    And no headless UI snapshot was created

  Scenario: Cancellation fences all late model events
    Given a language request waiting to propose a browser launch
    When the harness request is cancelled during inference
    Then no harness desktop action was dispatched
    And late inference cannot publish another harness event
    And the headless task status is "cancelled"
    And no headless UI snapshot was created

  Scenario: A side effect reports its actual outcome even when cancellation arrives
    Given the action service proposes a browser launch
    When the request is cancelled while that desktop action runs
    Then the collector received one complete browser outcome
    And the headless task status is "cancelled"
    And the cancelled request published no reply

  Scenario: A consumer cannot change action arguments through an event payload
    Given the action service proposes a browser launch
    And the collector changes action event payloads
    When the harness receives "open the browser"
    Then only the originally proposed browser launch was dispatched
    And no headless UI snapshot was created

  Scenario: A consumer failure before dispatch is visible and executes nothing
    Given the action service proposes a browser launch
    And the collector rejects "tool_started" events
    When the headless harness attempts "open the browser"
    Then the consumer failure reaches its caller
    And no harness desktop action was dispatched

  Scenario: A consumer cannot change a prepared confirmation's nested arguments
    Given the action service prepares a browser confirmation
    And the collector changes action event payloads
    When the harness receives "open the browser but confirm first"
    And the harness receives "yes"
    Then only the originally proposed browser launch was dispatched

  Scenario: A source reader cannot misclassify a consumer failure as bad input
    Given a saved harness recording with "We use Kubeflow for training."
    And the collector rejects "answer" events
    When the headless harness attempts "summarize the last recording"
    Then the consumer failure reaches its caller
    And no harness desktop action was dispatched

  Scenario: Recording controls and capture events work without a UI
    Given a language request waiting to propose a browser launch
    When a recording shortcut arrives during model inference
    Then recording starts before that language request finishes
    And the saved recording is bound to the harness
    And the collector observed recording lifecycle events
    And no headless UI snapshot was created
