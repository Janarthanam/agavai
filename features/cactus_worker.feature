@cactus_model
Feature: Installed Cactus engines use the product worker interfaces
  These checks need scripts/setup-cactus.sh and AGAVAI_CACTUS_TEST_DIR.
  They use recorded audio and schema-only model calls, without desktop actions.

  Scenario Outline: Whistle finalizes two utterances without leaking cancelled speech
    When I replay the speech fixture through the installed "<mode>" Whistle worker
    Then both finalized transcripts contain the meeting notes and document request
    Examples:
      | mode |
      | streaming |
      | batch |

  Scenario: Needle normalizes native tool calls and unsupported requests
    When I ask the installed Needle engine to open a browser and explain physics
    Then the native tool call targets the browser and the explanation escalates

  Scenario: The task evaluator records native Needle exchanges
    When I evaluate the browser task using the installed Needle engine
    Then the simulated browser task succeeds and its model exchange is recorded
