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

  Scenario: Needle selects the audio head without keyword overlap
    Given a Needle router returning "volume" with "none" fallback
    When I route the utterance "increase playback level"
    Then the selected heads should include "audio"
    And the selected tool names should include "set_volume"
    And the selected tool names should not include "wallpaper_set"
    And Needle was offered every registered tool for selection only

  Scenario: Needle can select installed agents
    Given a Needle router returning "agents" with "none" fallback
    When I route the utterance "what assistants are available"
    Then the selected heads should include "agents"
    And the selected tool names should include "list_agents"

  Scenario: Needle deduplicates tool groups and retains the two-head limit
    Given a Needle router returning "multiple" with "none" fallback
    When I route the utterance "open a browser and turn up the sound"
    Then there should be 2 selected heads
    And the selected heads should include "audio"
    And the selected heads should include "launch"

  Scenario Outline: Needle failures and no matches follow the configured fallback
    Given a Needle router returning "<outcome>" with "<fallback>" fallback
    When I route the utterance "turn the volume up"
    Then there should be <count> selected heads
    Examples:
      | outcome | fallback | count |
      | empty | keyword | 1 |
      | empty | none | 0 |
      | error | keyword | 1 |
      | error | none | 0 |
      | malformed | keyword | 1 |
      | unknown | none | 0 |
