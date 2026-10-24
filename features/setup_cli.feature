Feature: Choose, download and explain the models from the command line
  agavai setup picks a model for each role, downloads what is missing, rewrites
  only the role tables, syncs the model services and explains the result.

  Scenario: Needle as the small brain with no larger brain needs no llama-server
    Given a Qwen and Parakeet setup with agavai-llm running
    When I run agavai setup with "--speech whistle --small needle --large none --yes"
    Then the downloads were "setup-cactus.sh"
    And the config selects Whistle and a Needle small brain that routes itself, with no larger brain
    And the other config tables are unchanged
    And the previous config is kept as a backup
    And the setup service changes are "disable --now agavai-llm.service"
    And setup prints "In one inference it is both router and agent"
    And setup prints "No llama-server runs at all."
    And the setup command returns 0

  Scenario: Adding a Qwen fallback downloads it only when it is missing
    Given a Needle-only setup without Qwen downloaded
    When I run agavai setup with "--large qwen3-4b-instruct --yes"
    Then the downloads were "download-model.sh qwen3-4b-instruct"
    And setup prints "writes [brain.large] keeps every other table"
    And the config has a "qwen3-4b-instruct" larger brain on port 18766
    And the setup service changes are "enable --now agavai-llm.service"
    And setup prints "takes over with the same history and tool groups from word matching"
    And the setup command returns 0

  Scenario: Moving the small brain from Needle to Qwen routes with word matching
    Given a Needle-only setup without Qwen downloaded
    When I run agavai setup with "--small qwen3-4b-instruct --yes"
    Then the downloads were "download-model.sh qwen3-4b-instruct"
    And the config routes with "keyword" for a "qwen3-4b-instruct" small brain
    And the setup service changes are "enable --now agavai-llm.service"
    And the setup command returns 0

  Scenario: Two llama brains get separate ports and services
    Given a Qwen and Parakeet setup with a second GGUF
    When I run agavai setup with "--large big --yes"
    Then no downloads ran
    And the config has a "big" larger brain on port 18767
    And the setup service changes are "restart agavai-llm.service;enable --now agavai-llm@large.service"
    And the setup command returns 0

  Scenario: A custom model outside the catalog does not block changing another role
    Given a Needle setup whose larger brain is a custom GGUF path
    When I run agavai setup with "--router keyword --yes"
    Then no downloads ran
    And setup prints "writes [router] keeps every other table"
    And the setup command returns 0

  Scenario: Answering the guided questions in a terminal
    Given a Qwen and Parakeet setup with agavai-llm running
    When I answer the setup questions with "whistle,needle,,none,y"
    Then setup prints "Speech input: what turns your voice into text"
    And setup prints "Needle chooses among all 35 tools itself, in the same inference."
    And the downloads were "setup-cactus.sh"
    And the config selects Whistle and a Needle small brain that routes itself, with no larger brain
    And the setup command returns 0

  Scenario: A dry run changes nothing
    Given a Qwen and Parakeet setup with agavai-llm running
    When I run agavai setup with "--small needle --large none --dry-run"
    Then no downloads ran
    And the config is unchanged
    And no setup service changes were made
    And setup prints "Download: needle3"
    And setup prints "Dry run: nothing changed."
    And the setup command returns 0

  Scenario: Without a terminal setup asks for --yes before changing anything
    Given a Qwen and Parakeet setup with agavai-llm running
    When I run agavai setup with "--small needle"
    Then no downloads ran
    And the config is unchanged
    And setup prints "Run again with --yes to apply"
    And the setup command returns 2

  Scenario: A failed download leaves the configuration and services alone
    Given a Qwen and Parakeet setup with agavai-llm running
    And the Cactus download fails
    When I run agavai setup with "--speech whistle --small needle --large none --yes"
    Then the config is unchanged
    And no setup service changes were made
    And setup prints "setup-cactus.sh failed"
    And the setup command returns 1

  Scenario: An unknown model is rejected before anything changes
    Given a Qwen and Parakeet setup with agavai-llm running
    When I run agavai setup with "--large mystery --yes"
    Then no downloads ran
    And the config is unchanged
    And setup prints "larger brain must be none or one of qwen3-4b-instruct"
    And the setup command returns 1

  Scenario: Listing and downloading models
    Given a Qwen and Parakeet setup with agavai-llm running
    When I run agavai "download"
    Then setup prints "needle3"
    And setup prints "not installed"
    When I run agavai "download needle3"
    Then the downloads were "setup-cactus.sh"

  Scenario Outline: explain describes the flow for each profile
    Given a Qwen and Parakeet setup with agavai-llm running
    When I explain the "<profile>" profile
    Then setup prints "<phrase>"
    Examples:
      | profile | phrase |
      | config.needle.toml | In one inference it is both router and agent |
      | config.needle.toml | agavai-llm.service for brain.large (qwen3-4b-instruct) |
      | config.needle-router.toml | Needle 3 in a brain worker picks up to two tool groups |
      | config.example.toml | A tool request takes two model steps |
