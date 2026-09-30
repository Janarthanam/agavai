Feature: Launchable desktop app
  The desktop launcher, bar icon and shortcut share a single overlay.

  Scenario: The desktop entry is named Agavai
    Then the desktop file should exist
    And the desktop file should contain "Name=Agavai"
    And the desktop file should contain "agavai app"
    And the desktop file should contain "Icon=agavai"

  Scenario: The bar widget and icon files ship with the plugin
    Then the plugin manifest should declare kind "bar-widget"
    And the plugin folder should contain "agavai.png"
    And the plugin folder should contain "BarWidget.qml"

  Scenario: agavai app is a CLI command
    When I run "python3 -m agavai app --help"
    Then the command output should contain "Start Agavai listening"
