Feature: Model services follow the configuration
  Speech, Needle and Kokoro workers start with each listening session.
  Only llama-server brain roles run as user services, and sync keeps them
  in step with config.toml.

  Scenario: Needle without a larger brain stops the llama-server
    Given the services config "needle only"
    And "agavai-llm.service" is running
    When I sync the services
    Then the service changes are "disable --now agavai-llm.service"
    And sync reports "agavai-llm.service: stopped; no brain role needs it"
    And sync returns 0

  Scenario: Adding a llama fallback starts its service
    Given the services config "needle with qwen fallback"
    When I sync the services
    Then the service changes are "enable --now agavai-llm.service"
    And sync reports "started for brain.large (qwen3-4b-instruct)"
    And sync returns 0

  Scenario: Changing the fallback model restarts the running service
    Given the services config "needle with qwen fallback"
    And "agavai-llm.service" is running with an older model
    When I sync the services
    Then the service changes are "restart agavai-llm.service"
    And sync reports "its settings changed"

  Scenario: Unchanged settings leave the running service alone
    Given the services config "needle with qwen fallback"
    And "agavai-llm.service" is running with the configured settings
    When I sync the services
    Then no service changes were made
    And sync reports "settings unchanged"
    And sync returns 0

  Scenario: A server started by the launcher is recognised as current
    Given the services config "needle with qwen fallback"
    And "agavai-llm.service" was started by the launcher
    When I sync the services
    Then no service changes were made
    And sync reports "settings unchanged"

  Scenario: Two llama roles run two services
    Given the services config "two llama roles"
    When I sync the services
    Then the service changes are "enable --now agavai-llm.service;enable --now agavai-llm@large.service"
    And sync reports "agavai-llm@large.service: started for brain.large (big)"

  Scenario Outline: Problems are reported before any service changes
    Given the services config "<profile>"
    And "agavai-llm.service" is running
    When I sync the services
    Then no service changes were made
    And sync reports "<message>"
    And sync returns 1
    Examples:
      | profile | message |
      | invalid | Unknown brain backend |
      | missing fallback model | brain.large model is missing |
      | uninstalled unit | agavai-llm.service is not installed |
      | another config file | unset AGAVAI_CONFIG |

  Scenario: The status view changes nothing
    Given the services config "needle with qwen fallback"
    When I show the services
    Then no service changes were made
    And sync reports "agavai-llm.service: needed for brain.large (qwen3-4b-instruct on 127.0.0.1:18766), inactive"
    And sync reports "agavai-config.path: inactive"

  Scenario: Saving config.toml runs a sync
    Then the config watcher runs "agavai services sync" when config.toml changes
    And the larger llama role has its own service instance
