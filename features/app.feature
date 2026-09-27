Feature: Launchable desktop app
  Agavai must show up in the app launcher as a real window, not only an overlay.

  Scenario: The desktop entry is named Agavai
    Then the desktop file should exist
    And the desktop file should contain "Name=Agavai"
    And the desktop file should contain "agavai app"

  Scenario: agavai app is a CLI command
    When I run "python3 -m agavai app --help"
    Then the command output should contain "Open the Agavai window"
