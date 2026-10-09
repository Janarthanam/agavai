Feature: Native voice widget and result browser
  The overlay and app consume real session snapshots rather than demo fixtures.

  Scenario: Listening clears the previous request and results
    Given a chat UI in a temp runtime dir
    When the user says "old request"
    And tool "search_files" returns this full result
      """
      ["/tmp/notes.md"]
      """
    And the UI starts listening
    Then the native snapshot has no results or prior turns

  Scenario: Partial words revise the current listening utterance
    Given a chat UI in a temp runtime dir
    When the UI starts listening
    And recognition updates the words to "find my node"
    And recognition updates the words to "find my notes"
    Then the native transcript is "find my notes" and is partial

  Scenario: Final recognition replaces the partial words
    Given a chat UI in a temp runtime dir
    When the UI starts listening
    And recognition updates the words to "find node"
    And the user says "find notes"
    And recognition updates the words to "late partial"
    Then the native transcript is "find notes" and is final

  Scenario: File search produces selectable mixed media items
    Given a chat UI in a temp runtime dir
    When the user says "find my media"
    And tool "search_files" returns this full result
      """
      ["/tmp/notes.md", "/tmp/mountain view.png", "/tmp/demo.webm"]
      """
    Then the native result kinds are "file,image,video"
    And the native result 1 URI contains "mountain%20view.png"

  Scenario: An empty search gives an explicit empty result browser
    Given a chat UI in a temp runtime dir
    When tool "search_files" returns this full result
      """
      []
      """
    Then the native result kinds are ""
    And the native result title is "Files"

  Scenario: Theme browsing recognizes the actual tool output
    Given a chat UI in a temp runtime dir
    When tool "list_themes" returns this full result
      """
      {"current":"Tokyo Night","available":["Tokyo Night","Matte Black"]}
      """
    Then the native result title is "Themes"
    And the native result 0 subtitle is "Current theme"

  Scenario: The answer is rendered as formatted text
    Given a chat UI in a temp runtime dir
    When the assistant says "Here is **your answer**."
    Then the native answer contains "<b>your answer</b>"

  Scenario: HTML result formatting removes scripts and remote embeds
    Given a chat UI in a temp runtime dir
    When tool "desktop_help" returns this full result
      """
      {"kind":"html","text":"<h2>Answer</h2><script>steal()</script><img src='https://example.com/x'><b onclick='steal()'>Useful</b><a href='javascript:steal()'>Unsafe</a>"}
      """
    Then the native rich result contains "<b>Useful</b>"
    And the native rich result excludes "steal"
    And the native rich result excludes "<img"

  Scenario: A long tool result reaches the preview before model truncation
    Given a chat UI in a temp runtime dir
    When a mocked model searches for 30 matching files
    Then the native browser has 30 items
    And the model received a bounded tool result

  Scenario: The selected document opens through a fixed argument list
    Given a chat UI in a temp runtime dir
    And a native document result exists
    When I open native result 0 in the current session
    Then the native opener launches the selected document

  Scenario: A selected folder opens in the file manager
    Given a chat UI in a temp runtime dir
    And a native folder result exists
    When I open native result 0 in the current session
    Then the native result kinds are "folder"
    And the native opener launches the selected document

  Scenario: A stale selection cannot open a previous session's file
    Given a chat UI in a temp runtime dir
    And a native document result exists
    When I open native result 0 in the stale session
    Then the native opener launches nothing

  Scenario: Executable results cannot be opened from the preview
    Given a chat UI in a temp runtime dir
    When the user says "find a launcher"
    And tool "search_files" returns this full result
      """
      ["/tmp/run.desktop"]
      """
    And I open native result 0 in the current session
    Then the native opener launches nothing

  Scenario: Dismissal prevents late work from replacing the cancelled snapshot
    Given a chat UI in a temp runtime dir
    When the UI starts listening
    And the native session is cancelled
    And the assistant says "Late answer"
    Then the native snapshot label is "Cancelled"
    And the native session is marked cancelled

  Scenario: A new listening request works after cancellation
    Given a chat UI in a temp runtime dir
    When the UI starts listening
    And the native session is cancelled
    And the UI starts listening
    Then the snapshot phase should be "listening"
    And the native session is not marked cancelled

  Scenario: Follow-up listening keeps the screensaver images
    Given a chat UI in a temp runtime dir
    When the user says "show me all the images of screensaver"
    And tool "wallpaper_list" returns this full result
      """
      [{"name":"Ship At Sea","path":"/tmp/ship-at-sea.jpg"}]
      """
    And the assistant says "set the image you want as your screensaver"
    And the UI listens for a follow-up
    Then the snapshot phase should be "listening"
    And the native result title is "Images"
    And the native result kinds are "image"
    And the last assistant line should contain "screensaver"
    And the last user line should be "show me all the images of screensaver"

  Scenario: Leaving listening turns off the mic indicator
    Given a chat UI in a temp runtime dir
    When the UI starts listening
    And the mic input level is -20 dB
    And the user says "hello"
    Then the native microphone level is absent
