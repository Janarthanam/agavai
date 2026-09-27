Feature: Listening OSD payload
  If the bottom OSD is used, Listening must stay on screen until closed.

  Scenario: Listening OSD uses duration 0
    When I show the listening OSD
    Then the OSD command should be omarchy shell osd show
    And the OSD message should be "Listening"
    And the OSD icon should be "microphone"
    And the OSD duration should be 0
