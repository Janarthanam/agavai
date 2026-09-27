Feature: Configurable on-device model
  The GGUF is selected from config, not hardcoded in systemd.

  Scenario: Builtin default is qwen3-4b-instruct
    Given an empty oma-voice config
    When I load the config
    Then the model id should be "qwen3-4b-instruct"
    And the model path should end with "Qwen3-4B-Instruct-2507-Q4_K_M.gguf"

  Scenario: A named model in toml is selected
    Given a config that defines model "tiny" at "tiny.gguf" with ctx 2048 and 3 gpu layers
    When I load the config
    Then the model id should be "tiny"
    And the model path should end with "tiny.gguf"
    And ctx size should be 2048
    And n gpu layers should be 3

  Scenario: model_path overrides the catalog id
    Given a config with model "qwen3-4b-instruct" and model_path "override.gguf"
    When I load the config
    Then the model path should end with "override.gguf"
    And the model path should be marked overridden

  Scenario: OMA_VOICE_MODEL overrides the path
    Given a config with model "qwen3-4b-instruct"
    And environment OMA_VOICE_MODEL points at "env.gguf"
    When I load the config
    Then the model path should end with "env.gguf"

  Scenario: model set writes the id and drops model_path
    Given a config with model "qwen3-4b-instruct" and an extra model "other" at "other.gguf"
    When I set the model id to "other"
    Then the model id should be "other"
    And the config file should set model to "other"
    And the config file should not contain "model_path"

  Scenario: Unknown model ids are rejected
    Given a config with model "qwen3-4b-instruct"
    Then setting the model id to "nope" should fail

  Scenario: dump-llm quotes paths with spaces
    Given a config that defines model "spaced" at "my model.gguf"
    When I dump llm env
    Then the llm env should contain "MODEL_ID=spaced"
    And the llm env should contain "my model.gguf"
