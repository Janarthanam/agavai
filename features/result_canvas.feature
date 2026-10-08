Feature: Commands publish a canvas presentation once per result
  A new result can open the canvas even when it has the same content as
  the previous result. Microphone and partial updates retain its identity.

  Scenario: Tool results give repeated identical canvases distinct identities
    Given a chat UI in a temp runtime dir
    When a file listing is published, retained during listening, and published again
    Then listening updates keep the canvas identity
    And repeated results get a new canvas identity with the same content

  Scenario: Direct canvas publication supports new results and clearing
    Given a chat UI in a temp runtime dir
    When the same explicit canvas is published twice and then cleared
    Then repeated results get a new canvas identity with the same content
    And the cleared canvas is absent
