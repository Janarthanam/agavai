Feature: Accurate version and pipeline help
  Help describes the loaded session and distinguishes configuration from execution.
  Model and router HTTP services are local scripted boundary fixtures; Agavai runs normally.

  Scenario Outline: A real request publishes the pipeline that ran
    Given pipeline help services with "<policy>" tools, "<router>" routing and "<outcome>" primary
    And speech input configured as "<endpoint>"
    And an old snapshot claims a different version and pipeline
    When the pipeline help CLI asks for the time
    Then pipeline help identifies this version and the loaded stages
    And pipeline help execution matches the HTTP requests and completed action

    Examples:
      | policy | router  | outcome  | endpoint |
      | routed | jev     | fails    | vad      |
      | all    | jev     | succeeds | manual   |
      | routed | none    | succeeds | native   |
      | routed | keyword | succeeds | native   |

  Scenario: A listener reports the speech fallback actually selected
    Given pipeline help services with "routed" tools, "keyword" routing and "succeeds" primary
    And speech input configured as "native"
    When the pipeline help listener handles a committed request without speech assets
    Then pipeline help execution matches the HTTP requests and completed action
    And pipeline help reports notification-only speech

  Scenario: Speech configuration and actual speech use the same preference order
    Given pipeline help services with "routed" tools, "keyword" routing and "succeeds" primary
    And speech input configured as "native"
    And pipeline help prefers eSpeak with a runnable speech command
    When the pipeline help CLI asks for the time
    Then pipeline help reports the preferred speech engine and fallback order

  @native_overlay
  Scenario: Help opens from the native overlay without replacing the session
    Given pipeline help services with "routed" tools, "jev" routing and "fails" primary
    And speech input configured as "vad"
    When the pipeline help CLI asks for the time
    And I inspect pipeline help in the native overlay
    Then the native help interaction checks pass
