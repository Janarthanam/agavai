@brain_comparison
Feature: Compare installed brains through the complete assistant turn
  This opt-in experiment measures model decisions rather than requiring a
  particular accuracy score. Models run locally; all desktop effects are simulated.
  Set AGAVAI_BRAIN_COMPARISON_OUT and AGAVAI_CACTUS_TEST_DIR to run it.

  Background:
    Given local Qwen and Needle are available for comparison
    And the brain comparison includes these evaluation cases
      | id                               |
      | desktop.launch.browser           |
      | desktop.dnd.on                   |
      | desktop.wallpaper.next           |
      | desktop.volume.up                |
      | desktop.time                     |
      | brain.fact.france                |
      | brain.negation.browser           |
      | brain.negation.dnd               |
      | messy.falsestart.browser          |
      | messy.selfcorrect.reminder        |
      | judgment.ask.reminder             |
      | judgment.decline.shutdown         |
      | multi.dim-dnd                     |
      | conversation.brightness.correct  |

  Scenario Outline: Measure each brain policy against the same requests
    When I run the complete assistant with the "<profile>" brain policy
    Then every comparison case has recorded model exchanges and a valid outcome
    And the brain comparison made no outbound connection

    Examples:
      | profile                |
      | qwen-routed            |
      | qwen-all               |
      | needle-routed-qwen-all  |
      | needle-all-qwen-all     |
