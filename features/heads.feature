Feature: Tool heads and routing
  Qwen only sees schemas from the selected head. Jev chooses the head when
  configured; keyword fallback works offline.

  Scenario: Screensaver images select the wallpaper head
    Given the keyword router
    When I route the utterance "show me all the images of screensaver"
    Then the selected heads should include "wallpaper"
    And the selected tool names should include "wallpaper_list"
    And the selected tool names should include "wallpaper_set"

  Scenario: Next wallpaper selects the wallpaper head
    Given the keyword router
    When I route the utterance "next wallpaper"
    Then the selected heads should include "wallpaper"
    And the selected tool names should include "wallpaper_next"
    And the selected tool names should not include "set_volume"

  Scenario: Volume up does not load wallpaper tools
    Given the keyword router
    When I route the utterance "turn the volume up"
    Then the selected heads should include "audio"
    And the selected tool names should include "set_volume"
    And the selected tool names should not include "wallpaper_set"

  Scenario: Greeting selects no tools
    Given the keyword router
    When I route the utterance "hello there"
    Then there should be 0 selected heads

  Scenario: Mocked Jev wallpaper choice
    Given a Jev response choosing head "wallpaper"
    When I route the utterance "set the wallpaper to ship at sea"
    Then the selected heads should include "wallpaper"

  Scenario: Jev chit-chat still keeps an explicit screensaver request
    Given a Jev response choosing head "chat"
    When I route the utterance "show me all the images of screensaver"
    Then the selected heads should include "wallpaper"
    And the selected tool names should include "wallpaper_list"

  Scenario: Mocked Jev chit-chat choice selects no tools
    Given a Jev response choosing head "chat"
    When I route the utterance "hello there"
    Then there should be 0 selected heads

  Scenario: Missing OpenRouter key falls back to keyword
    Given router backend jev with no api key
    When I route the utterance "next wallpaper"
    Then the selected heads should include "wallpaper"

  Scenario: wallpaper_set rejects parent paths
    When I set wallpaper to "../etc/passwd"
    Then the tool result should contain "invalid wallpaper path"

  Scenario: Taking notes selects the recordings head
    Given the keyword router
    When I route the utterance "take notes"
    Then the selected heads should include "recordings"
    And the selected tool names should include "start_recording"
