Feature: MCP stdio tools
  Other agents discover the same allowlist over MCP.

  Scenario: Server announces agavai and lists safe tools
    When I send MCP initialize
    Then the MCP server name should be "agavai"
    When I send MCP tools/list
    Then MCP should list the tool "launch"
    And MCP should list the tool "list_windows"
    And MCP should not list the tool "shell"

  Scenario: MCP refuses unknown tools
    When I call MCP tool "exec"
    Then the MCP text result should contain "unknown tool"
