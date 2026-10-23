Feature: Select speech and brain engines independently
  Engine-specific code lives behind speech and brain interfaces. A finished
  request runs once; small-model success never invokes a larger model.

  Scenario: Whistle and Needle are selected without changing TTS
    Given an engine config selecting Whistle and Needle
    When I load the engine config
    Then the selected engines and independent environments are preserved

  Scenario Outline: Incompatible configurations fail before capture
    Given an engine config with "<setting>"
    When I load the engine config
    Then engine configuration fails with "<message>"
    Examples:
      | setting | message |
      | unknown speech | Unknown ASR |
      | whistle native | manual |
      | whistle gpu | cpu |
      | zero deadline | deadline |
      | unknown brain | Unknown brain |
      | missing brain model | model_path |

  Scenario Outline: Streaming and batch speech finish the pending tail once
    When a "<mode>" Whistle adapter receives two chunks and a short tail
    Then the final speech text contains the tail exactly once
    And "<mode>" partial behavior is respected
    Examples:
      | mode |
      | streaming |
      | batch |

  Scenario: Cancelling Whistle discards the previous turn
    When I cancel Whistle after a partial and start another utterance
    Then only the second utterance is finalized

  Scenario: Enter flushes the worker before submitting the voice request
    Given a chat UI in a temp runtime dir
    When Enter finishes a real worker with a pending speech tail
    Then the submitted line is "open the browser"
    And the voice request is submitted once

  Scenario: Escape cancels a batch worker without running recognition
    Given a chat UI in a temp runtime dir
    When Escape cancels a real batch worker
    Then the voice request is not submitted
    And batch recognition was not finalized

  Scenario: A worker that never finishes fails within its deadline
    Given a chat UI in a temp runtime dir
    When Enter finishes an unresponsive speech worker
    Then the voice request is not submitted
    And the snapshot phase should be "error"

  Scenario: Small tool model succeeds while the larger runtime is down
    Given a chat UI in a temp runtime dir
    When the small engine handles a browser request
    Then only the small engine and the browser tool run

  Scenario Outline: Small-model inability escalates once
    Given a chat UI in a temp runtime dir
    When the small engine returns "<outcome>" for an unsupported request
    Then the larger engine answers with the same request history
    Examples:
      | outcome |
      | empty |
      | unsupported |
      | explicit escalation |
      | runtime error |

  Scenario: Empty output without a larger engine is a failure
    Given a chat UI in a temp runtime dir
    When the only brain engine returns an empty response
    Then the reply does not claim completion

  Scenario: Escalation preserves completed actions without repeating them
    Given a chat UI in a temp runtime dir
    When the small engine launches the browser then escalates
    Then the browser is launched once despite the larger engine repeating its call

  Scenario: Malformed arguments cannot reach desktop tools
    Given a chat UI in a temp runtime dir
    When the small engine requests a browser launch without required arguments
    Then no desktop tool is executed

  Scenario: Needle grounding failures become unsupported requests
    When Needle reports an ungrounded date in a tool argument
    Then the Needle response is unsupported

  Scenario Outline: The llama launcher selects the configured role
    Given an engine config selecting Whistle and Needle
    When I inspect the llama launcher for role "<role>"
    Then the launcher contains "<setting>"
    Examples:
      | role | setting |
      | service | MODEL=/qwen.gguf |
      | large | PORT=19000 |
      | small | ENGINE=none |

  Scenario: A failing larger engine does not recurse into escalation
    Given a chat UI in a temp runtime dir
    When both configured brain engines fail
    Then each brain was attempted once and the failure is visible

  Scenario: A batch Enter shows transcription while waiting for final text
    Given a chat UI in a temp runtime dir
    When Enter finalizes a real batch speech worker
    Then the voice request is submitted once
    And the batch worker was finalized while the UI was transcribing

  Scenario: A registered speech adapter is selectable without changing capture
    When I register and select an additional speech adapter
    Then configuration and the speech factory use that adapter

  Scenario: A registered brain adapter answers through the existing turn loop
    Given a chat UI in a temp runtime dir
    When I register and select an additional brain adapter
    Then its answer completes without invoking llama-server

  Scenario: Empty final text never submits an earlier partial
    Given a chat UI in a temp runtime dir
    When the recognizer replaces a partial with an empty final transcript
    Then the voice request is not submitted
