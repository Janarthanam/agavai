Feature: Recordings keep the audio, a timed transcript, and corrections
  A recording captures the microphone continuously. Speech is content: only
  an isolated "Agavai stop", "pause", "resume", or "mark" acts. Every way of
  stopping saves the recording. The recognizer here is scripted, and the
  folder, audio encoding, and snapshot are real.

  Background:
    Given a chat UI in a temp runtime dir
    And recordings are kept in a temp folder

  Scenario: A recording keeps the audio and every line with its time
    When I record while the microphone hears
      """
      audio 2000
      interim the canary ships
      peek
      eou 300 1900 the canary ships on thursday
      audio 1500
      eou 2100 3400 widen it on monday
      peek
      request toggle
      """
    Then while recording the overlay showed the partial "the canary ships"
    And while recording the overlay showed the line "00:01" "widen it on monday"
    And the recording is saved with its audio compressed
    And the recording lasts 3.5 seconds
    And the recording keeps these lines
      | start_ms | text                         |
      | 0        | the canary ships on thursday |
      | 1900     | widen it on monday           |
    And the transcript file lists "[00:01] widen it on monday"
    And the overlay shows the saved recording for review
    And the assistant state is "idle"

  Scenario: Only an isolated "Agavai stop" stops; a longer sentence is content
    When I record while the microphone hears
      """
      audio 1000
      eou 0 900 agavai stop the server before deploying
      audio 1000
      eou 1000 1800 Agavai, stop.
      audio 3000
      """
    Then the recording lasts 2 seconds
    And the recording keeps these lines
      | start_ms | text                                  |
      | 0        | agavai stop the server before deploying |

  Scenario: Pausing keeps nothing until "Agavai resume" is heard
    When I record while the microphone hears
      """
      audio 1000
      eou 0 900 before the pause
      request pause
      audio 2000
      eou 1100 2500 this part stays private
      eou 2600 2900 agavai resume
      audio 1000
      eou 3100 3900 after the pause
      request toggle
      """
    Then the recording lasts 2 seconds
    And the recording keeps these lines
      | start_ms | text             |
      | 0        | before the pause |
      | 900      | after the pause  |
    And the recording pauses at 1000 ms

  Scenario: Marks keep the moment they were made
    When I record while the microphone hears
      """
      audio 1500
      request mark
      audio 1000
      eou 1600 2400 agavai mark
      audio 500
      request toggle
      """
    Then the recording keeps marks at 1500 and 2500 ms
    And the transcript file lists "⚑ [00:01] Mark"

  Scenario: Dismissing the overlay stops and still saves the recording
    When I record while the microphone hears
      """
      audio 1000
      eou 0 900 keep this
      dismiss
      """
    Then the recording is saved with its audio compressed
    And the recording keeps these lines
      | start_ms | text      |
      | 0        | keep this |
    And the overlay does not show the saved recording

  Scenario: Agavai stop on the command line saves the recording
    When I record while the microphone hears
      """
      audio 1000
      sigterm
      """
    Then the recording is saved with its audio compressed
    And the overlay shows the saved recording for review

  Scenario: Audio keeps recording when the live transcript stops
    When I record while the microphone hears
      """
      audio 1000
      eou 0 900 heard live
      asr_lost
      peek
      audio 2000
      request toggle
      """
    Then while recording the overlay showed that the live transcript stopped
    And the recording lasts 3 seconds
    And the recording keeps these lines
      | start_ms | text       |
      | 0        | heard live |

  Scenario: A microphone that goes away ends the recording and keeps it
    When I record while the microphone hears
      """
      audio 1000
      """
    Then the recording is saved with its audio compressed
    And the snapshot shows the error "The microphone stopped, so the recording was saved."

  Scenario: A recording that captured nothing leaves no folder behind
    When I record while the microphone hears
      """
      request toggle
      """
    Then no recording folder is left
    And the snapshot shows the error "Nothing was recorded."

  Scenario: Without ffmpeg the uncompressed audio is kept
    Given ffmpeg is not installed
    When I record while the microphone hears
      """
      audio 1000
      request toggle
      """
    Then the recording keeps its uncompressed audio and says why

  Scenario: A recording a crash interrupted is finished on the next start
    Given a recording a crash left with 1.5 seconds of audio and a cut-off journal
    When I record while the microphone hears
      """
      audio 1000
      request toggle
      """
    Then the interrupted recording is finished and marked recovered
    And the interrupted recording keeps its line "before the crash"

  Scenario: A correction lies over the heard words and can be undone
    When I record while the microphone hears
      """
      audio 1000
      eou 0 900 the jobs run on cube flow
      request toggle
      """
    And I correct line 1 to "The jobs run on Kubeflow."
    Then the recording keeps these lines
      | start_ms | text                      |
      | 0        | The jobs run on Kubeflow. |
    And the transcript file lists "[00:00] The jobs run on Kubeflow."
    And line 1 still keeps what was heard, "the jobs run on cube flow"
    When I correct line 1 to "the jobs run on cube flow"
    Then line 1 has no correction

  Scenario: A toggle while the assistant listens records, then the assistant listens again
    When the assistant is listening and a recording is toggled on and then off
    Then the recording is saved with its audio compressed
    And the assistant went back to listening with the review on screen

  Scenario: A recording session from the shortcut closes the microphone when it stops
    When I record while the microphone hears
      """
      audio 1000
      request toggle
      """
    Then the recording session ended
    And the snapshot phase should be "idle"

  Scenario: The record command starts a recording session when nothing is running
    When I run "agavai record" with nothing running
    Then a detached recording session was started

  Scenario: The record command sends its action to a running recording
    When I run "agavai record mark" while a recording is running
    Then the command exits with 0
    And the running recording was asked to "mark"

  Scenario: The record command does not signal a listener that is still starting
    When I run "agavai record" while a listener is still starting
    Then the command exits with 0
    And no listener was signalled

  Scenario: Pausing with nothing recording is an error
    When I run "agavai record pause" with nothing running
    Then the command exits with 1

  Scenario: Saying "take notes" records right after the reply, then the assistant listens again
    When the assistant hears "take notes" and the model starts a recording
    Then the recording is saved with its audio compressed
    And the assistant went back to listening with the review on screen

  Scenario: Saved recordings are listed newest first, by title
    Given a saved recording "Standup" from "2026-10-22T09:00:00" lasting 90 seconds
    And a saved recording "Lecture" from "2026-10-23T10:02:00" lasting 3130 seconds
    When the assistant lists the recordings
    Then the canvas lists the recordings
      | title    | subtitle                  |
      | Lecture  | Fri 23 Oct, 10:02 · 52:10 |
      | Standup  | Thu 22 Oct, 09:00 · 01:30 |
    And the model hears the recordings by title, without their folders

  Scenario: The overlay corrects a line through the command line, only inside the recordings folder
    When I record while the microphone hears
      """
      audio 1000
      eou 0 900 the jobs run on cube flow
      request toggle
      """
    And the overlay corrects line 1 to "The jobs run on Kubeflow." through the command line
    Then the command exits with 0
    And the recording keeps these lines
      | start_ms | text                      |
      | 0        | The jobs run on Kubeflow. |
    When the overlay corrects a line in a folder outside the recordings folder
    Then the command exits with 1
