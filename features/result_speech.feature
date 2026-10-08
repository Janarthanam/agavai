Feature: Result speech uses readable names
  Exact filenames remain on the canvas. Speech uses readable labels and
  the model is asked for a brief summary when a list is shown.

  Scenario Outline: Technical filenames become readable speech
    When I prepare a spoken label for a "<kind>" titled "<title>" at "<path>"
    Then the result label is "<label>"

    Examples:
      | kind   | title                 | path                         | label              |
      | file   | Meeting_Notes-2026.md | /tmp/Meeting_Notes-2026.md    | Meeting Notes 2026 |
      | file   | résumé-final.PDF     | /tmp/résumé-final.PDF        | résumé final       |
      | file   | Budget.v2.pdf        | /tmp/Budget.v2.pdf           | Budget.v2          |
      | folder | Project_Notes        | /tmp/Project_Notes           | Project Notes      |
      | image  | Ship At Sea          | /tmp/01_ship-at-sea.jpg      | Ship At Sea        |
      | file   | Release 1.2          | /tmp/release-notes.md        | Release 1.2        |
      | file   | Summary.PDF          | /tmp/report.pdf              | Summary            |
      | file   | Budget Notes.pdf     | /tmp/Budget Notes.pdf         | Budget Notes       |
      | video  | demo-video.mp4       | /tmp/demo-video.mp4          | demo video         |

  Scenario: Known filenames and paths are shortened without altering other filenames
    Given a chat UI in a temp runtime dir
    When file results contain technical names and the reply echoes filenames and paths
    Then speech uses readable labels while the canvas keeps exact names

  Scenario: An unlisted file path is spoken without an extension
    When I prepare speech for "Open /tmp/meeting-notes.pdf." without a canvas
    Then the result speech is "Open meeting notes."

  Scenario: Replacing one result name does not change the next result label
    When I prepare speech for "/tmp/first.md and /tmp/Notes" from these results
      | kind   | title   | path          |
      | file   | Notes   | /tmp/first.md |
      | folder | Archive | /tmp/Notes    |
    Then the result speech is "Notes and Archive"
