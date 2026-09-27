Feature: Allowlisted desktop tools
  The voice agent may only run named Omarchy/Hyprland tools.
  There is no generic shell.

  Scenario: Unknown tools are rejected
    When I call the tool "rm_rf" with empty arguments
    Then the tool result should contain "unknown"

  Scenario: Launch only accepts enumerated apps
    When I launch target "bash"
    Then the tool result should contain "unknown target"

  Scenario: Launching the browser uses omarchy-launch-browser
    Given the launch binary "omarchy-launch-browser" is on PATH
    When I launch target "browser"
    Then the tool result should be "launched browser"
    And the launched program should be "omarchy-launch-browser"

  Scenario Outline: Workspace numbers are bounded
    When I switch to workspace <n>
    Then the tool result should contain "must be 1-20"

    Examples:
      | n  |
      | 0  |
      | 99 |

  Scenario Outline: play_url rejects non-http schemes
    When I play url "<url>"
    Then the tool result should contain "http"

    Examples:
      | url                    |
      | file:///etc/passwd     |
      | javascript:alert(1)    |

  Scenario: File search requires a real query
    When I call the tool "search_files" with query "a"
    Then the tool result should contain "query"
