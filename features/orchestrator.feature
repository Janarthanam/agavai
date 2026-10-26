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
    And no context decision was requested

  Scenario: A follow-up sends the earlier conversation and keeps the image tools
    Given a chat UI in a temp runtime dir
    And the chat UI uses the keyword router
    And llama-server replies "set the image you want as your screensaver"
    When I run a turn with text "show me all the images of screensaver" on the chat UI
    Then the spoken reply should be "set the image you want as your screensaver"
    Given the router selects no heads
    And the context response is "follow_up"
    And llama-server replies "Setting ship at sea."
    When I continue the turn with text "ship at sea"
    Then the spoken reply should be "Setting ship at sea."
    And the model messages included "show me all the images of screensaver"
    And the follow-up model was offered "wallpaper_set"

  Scenario: A file listing is spoken by name, not full path
    Given a chat UI in a temp runtime dir
    And llama-server calls "search_files" with a notes folder, image, and file, then reads their paths
    When I run a turn with text "show me the files" on the chat UI
    Then the spoken reply should be "Here are Notes, ship at sea, and notes."
    And the model tool text should not contain the notes path

  Scenario: Think tags are stripped from model text
    Then stripping think tags from "hello" yields "hello"
    And stripping think tags from "pre<think>secret</think>post" yields "prepost"

  Scenario: A list answer opens on the canvas and only its summary is spoken
    Given a chat UI in a temp runtime dir
    And the router selects no heads
    And llama-server shows this answer
      """
      {"title": "Planets", "markdown": "- Mercury\n- Venus\n- Earth", "summary": "Here are the planets, in order from the Sun."}
      """
    When I run a turn with text "list the planets" on the chat UI
    Then the spoken reply should be "Here are the planets, in order from the Sun."
    And the canvas shows the answer "Planets" with "<p>• Venus</p>"
    And the model was asked once and offered only "show_answer"
    And the model was given the chat instructions
    And the remembered conversation keeps the shown Markdown

  Scenario: An ordinary answer stays spoken without a canvas
    Given a chat UI in a temp runtime dir
    And the router selects no heads
    And llama-server replies "Paris is the capital of France."
    When I run a turn with text "what is the capital of France" on the chat UI
    Then the spoken reply should be "Paris is the capital of France."
    And the model was offered "show_answer"
    And the model was given the chat instructions
    And the canvas is empty

  Scenario: Desktop turns keep their tool budget for desktop tools
    Given a chat UI in a temp runtime dir
    And the chat UI uses the keyword router
    And llama-server replies "Opened the browser."
    When I run a turn with text "open the browser" on the chat UI
    Then the model was offered "launch"
    And the model was not offered "show_answer"
    And the model was given the desktop instructions

  Scenario: A chat turn that reaches for a desktop tool gets the desktop instructions on the retry
    Given a chat UI in a temp runtime dir
    And the router selects no heads
    And llama-server calls "wallpaper_next" then "wallpaper_next" then replies "Next wallpaper."
    When I run a turn with text "next wallpaper" on the chat UI
    Then the spoken reply should be "Next wallpaper."
    And the tool "wallpaper_next" should have been called once
    And the model was given the chat instructions, then the desktop instructions

  Scenario: A turn without an event consumer is not offered a structured answer
    Given the router selects no heads
    And llama-server shows this answer
      """
      {"title": "Planets", "markdown": "- Mercury", "summary": "Here are the planets."}
      """
    When I run a turn with text "list the planets"
    Then the model was not offered "show_answer"
    And the model was given the desktop instructions
    And the spoken reply should be "The model requested a tool unavailable in this turn: show_answer"

  Scenario: An incomplete on-screen answer is an error, not a blank canvas
    Given a chat UI in a temp runtime dir
    And the router selects no heads
    And llama-server shows this answer
      """
      {"title": "Planets", "markdown": "- Mercury", "summary": " "}
      """
    When I run a turn with text "list the planets" on the chat UI
    Then the snapshot phase should be "error"
    And the canvas is empty
