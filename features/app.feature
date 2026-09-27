Feature: Launchable desktop app
  Agavai must show up in the app launcher as a real window, not only an overlay.

  Scenario: The desktop entry is named Agavai
    Then the desktop file should exist
    And the desktop file should contain "Name=Agavai"
    And the desktop file should contain "oma-voice app"

  Scenario: oma-voice app is a CLI command
    When I run "python3 -m oma_voice app --help"
    Then the command output should contain "Open the Agavai window"
