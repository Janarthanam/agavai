Feature: Local tool loop
  The on-device model may call tools, then speak a short reply.

  Scenario: Empty speech is ignored
    When I run a turn with text "   "
    Then the spoken reply should be "I did not hear anything."

  Scenario: Down llama-server is reported instead of inventing actions
    Given llama-server is down
    When I run a turn with text "open the browser"
    Then the spoken reply should contain "not running"

  Scenario: A tool call is executed then the model speaks
    Given llama-server will call "launch" then reply "Opened the browser."
    When I run a turn with text "open the browser"
    Then the spoken reply should be "Opened the browser."
    And the tool "launch" should have been called once

  Scenario: A head the router skipped is attached when the model asks for it
    Given the router selects no heads
    And llama-server calls "wallpaper_next" then "wallpaper_next" then replies "Next wallpaper."
    When I run a turn with text "next wallpaper"
    Then the spoken reply should be "Next wallpaper."
    And the tool "wallpaper_next" should have been called once
    And the model should have been offered "wallpaper_next" only after the retry

  Scenario: A choice prompt waits for a follow-up and a finished action does not
    Then a follow-up is expected for "set the image you want as your screensaver"
    And a follow-up is not expected for "Wallpaper set to ship at sea."

  Scenario: Asking to see screensaver images shows them before the reply
    Given a chat UI in a temp runtime dir
    And the chat UI uses the keyword router
    And llama-server replies "Which image do you want?"
    And wallpaper listing returns a ship image
    When I run a turn with text "show me all the images of screensaver" on the chat UI
    Then the spoken reply should be "Which image do you want?"
    And the tool "wallpaper_list" should have been called once
    And the native result title is "Images"

  Scenario: A follow-up sends the earlier conversation and keeps the image tools
    Given a chat UI in a temp runtime dir
    And the chat UI uses the keyword router
    And llama-server replies "set the image you want as your screensaver"
    When I run a turn with text "show me all the images of screensaver" on the chat UI
    Then the spoken reply should be "set the image you want as your screensaver"
    Given the router selects no heads
    And llama-server replies "Setting ship at sea."
    When I continue the turn with text "ship at sea"
    Then the spoken reply should be "Setting ship at sea."
    And the model messages included "show me all the images of screensaver"
    And the follow-up model was offered "wallpaper_set"

  Scenario: Think tags are stripped from model text
    Then stripping think tags from "hello" yields "hello"
    And stripping think tags from "pre<think>secret</think>post" yields "prepost"
