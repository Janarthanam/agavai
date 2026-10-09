Feature: Configure before installing the service
  Scenario Outline: Configure before the selected downloads and installation
    When I run setup selecting "<choice>"
    Then setup operations are "<operations>"
    And setup returns 0

    Examples:
      | choice | operations |
      | all | configure,download-model,download-asr,download-tts,install |
      | llm | configure,download-model,install |
      | voice | configure,download-asr,download-tts,install |
      | none | configure,install |

  Scenario: Invalid selection changes nothing
    When I run setup selecting "invalid"
    Then setup operations are empty
    And setup returns 2

  Scenario: No terminal requires a model selection
    When I run setup with no selection
    Then setup operations are empty
    And setup returns 2

  Scenario: Configuration failure stops downloads and installation
    When configuration fails during setup
    Then setup operations are "configure"
    And setup returns 1

  Scenario: Download failure stops installation
    When a model download fails during setup
    Then setup operations are "configure,download-model"
    And setup returns 1

  Scenario: Explicit acceptance still validates existing configuration
    When I run setup accepting existing configuration
    Then setup operations are "configure --check,install"
    And setup returns 0

  Scenario Outline: Reject incomplete configuration before any service changes
    When I install with "<state>" configuration
    Then no service commands have run
    And setup returns 1

    Examples:
      | state |
      | missing |
      | malformed |
      | missing binary |
      | missing model |

  Scenario: Service activation follows configuration and app installation
    When I install with "ready" configuration
    Then the service is installed and restarted
    And setup returns 0

  Scenario: Report a service restart failure
    When service restart fails during installation
    Then the service is installed and restarted
    And setup returns 1

  Scenario: Save configuration in the editor before installing the service
    When I configure through the installation editor
    Then the edited configuration is saved
    And the service is installed and restarted
    And setup returns 0

  Scenario: Cancelling the editor prevents service installation
    When the installation editor fails
    Then no service commands have run
    And setup returns 1
