Feature: Parsing model tool calls
  llama-server may emit OpenAI tool_calls or leaked Qwen XML.

  Scenario: OpenAI-style tool_calls are used as-is
    When I parse an OpenAI tool call named "launch"
    Then the first parsed tool name should be "launch"

  Scenario: Qwen XML tool_call is recovered
    When I parse Qwen XML for tool "to_workspace" with workspace 2
    Then there should be 1 parsed tool call
    And the first parsed tool name should be "to_workspace"
    And the first parsed tool workspace should be 2

  Scenario: Plain assistant text is not a tool call
    When I parse plain assistant text "hello"
    Then there should be 0 parsed tool calls

  Scenario: Pinned sampling is sent only when configured
    When I send a chat request with default sampling
    Then the request should not contain "seed"
    And the request should not contain "cache_prompt"
    When I send a chat request with seed 42 and the prompt cache off
    Then the request "seed" should be 42
    And the request "cache_prompt" should be false
