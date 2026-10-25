Feature: Request log in the user journal
  Each layer of a request leaves a line in the user journal, tagged with the
  request it belongs to, so a request that went wrong can be traced afterwards.
  The default level records no user text; debug adds it.

  Scenario: Lines reach the journal socket tagged with their request
    Given a journal socket
    When the request log is set up and request 1 of session "a2bd4d6f9e1c" logs "router heads=files"
    Then the journal socket receives "<14>agavai: request=a2bd4d6f-1 router heads=files"

  Scenario: A typed request leaves one line per layer under one request id
    Given a chat UI in a temp runtime dir
    And the chat UI uses the keyword router
    And llama-server calls "search_files" and then replies "Your budget notes are on screen."
    And file search finds "/home/me/Documents/budget-notes.md"
    When I ask "find the budget notes"
    Then the request log for request 1 reads
      | line                                                                  |
      | turn start continue=False                                             |
      | router backend=keyword source=keyword heads=files                     |
      | llm tools=2 prompt_tokens=120 completion_tokens=12 calls=search_files |
      | tool name=search_files status=ok                                      |
      | llm tools=2 prompt_tokens=180 completion_tokens=9 calls=none          |
      | turn done                                                             |
      | tts engine=kokoro                                                     |
    And the request log does not contain "budget"

  Scenario: Debug logging adds what was said, the reply, and tool arguments and results
    Given a chat UI in a temp runtime dir
    And the chat UI uses the keyword router
    And debug logging
    And llama-server calls "search_files" and then replies "Your budget notes are on screen."
    And file search finds "/home/me/Documents/budget-notes.md"
    When I ask "find the budget notes"
    Then the request log contains "turn text "find the budget notes""
    And the request log contains "budget-notes.md"
    And the request log contains "turn reply "Your budget notes are on screen.""

  Scenario: Each capture in a listen session gets the next request number and says why it ended
    Given a chat UI in a temp runtime dir
    When an automatic session hears a request, noise, and a follow-up
    Then the listen log reads
      | request | line                                |
      | -       | session start                       |
      | 1       | asr end reason=eou words=3          |
      | 2       | asr end reason=empty words=0        |
      | 3       | asr end reason=eou words=4          |
      | 4       | asr end reason=stream_ended words=0 |
      | 4       | session end reason=stream ended     |

  Scenario: The recognizer reports its device and load time
    Given a chat UI in a temp runtime dir
    When streaming capture receives silence and speech without recognition output
    Then the request log contains "asr ready device=cpu load_secs="

  Scenario: A recognizer that cannot start leaves its reason
    Given a chat UI in a temp runtime dir
    When an automatic session cannot start the recognizer
    Then the request log contains "asr did not start: Streaming ASR model is not installed."
    And the request log contains "session end reason=recognizer did not start"

  Scenario: A turn that raises leaves its traceback
    Given a chat UI in a temp runtime dir
    When an automatic session's turn raises "router exploded"
    Then the request log contains "turn failed"
    And the request log contains "RuntimeError: router exploded"

  Scenario: The router says why it fell back
    Given a chat UI in a temp runtime dir
    And the Jev router has no OpenRouter key
    When the router picks heads for "show me the wallpapers"
    Then the request log contains "router backend=jev failed (RuntimeError: no OpenRouter key); fallback=keyword"
    And the request log contains "router backend=jev source=keyword heads=wallpaper"

  Scenario Outline: An invocation says whether it started a session
    Given a chat UI in a temp runtime dir
    When I invoke Agavai while it is "<phase>"
    Then the request log contains "invoke summoned the overlay; started_session=<started>"

    Examples:
      | phase     | started |
      | idle      | True    |
      | listening | False   |

  Scenario: A config that cannot load leaves its error for the hotkey
    Given a config with log level "verbose"
    When agavai status runs with that config
    Then the request log contains "config could not be loaded"
    And the request log contains "unknown [log] level 'verbose'"
